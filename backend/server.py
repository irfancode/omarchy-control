#!/usr/bin/env python3
"""Omarchy Control — Web-based desktop management for Omarchy/Hyprland.
Zero dependencies — uses only Python stdlib."""

import json, os, subprocess, traceback, time, threading, signal
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
from collections import deque
from datetime import datetime

PORT = int(os.environ.get("OMARCHY_CONTROL_PORT", 8765))
HOME = Path.home()
CONFIG_HYPR = HOME / ".config" / "hypr"
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# ─── Metrics History ─────────────────────────────────────────────────────────
MAX_HISTORY = 120
metrics_history = deque(maxlen=MAX_HISTORY)
_history_lock = threading.Lock()
_metrics_cond = threading.Condition(_history_lock)
_collector_started = False
_server_shutdown = False

# ─── Alert Thresholds ───────────────────────────────────────────────────────
alert_thresholds = {
    "cpu_warn": 80, "cpu_crit": 95,
    "mem_warn": 85, "mem_crit": 95,
    "disk_warn": 85, "disk_crit": 95,
    "temp_warn": 80, "temp_crit": 90,
}
_alert_lock = threading.Lock()

# ─── Helpers ────────────────────────────────────────────────────────────────

def run(*args, timeout=10):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "command not found", -1
    except subprocess.TimeoutExpired:
        return "", "timeout", -1

def read_file(path):
    try: return Path(path).read_text()
    except Exception: return ""

def write_file(path, content):
    try: Path(path).write_text(content); return True
    except Exception: return False

def json_resp(data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode()
    return (status, {"Content-Type": "application/json"}, body)

def json_resp_cors(data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode()
    return (status, {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}, body)

def api_error(msg, status=400):
    return json_resp({"ok": False, "error": msg}, status)

def sse_msg(data, event=None):
    msg = ""
    if event:
        msg += f"event: {event}\n"
    msg += f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    return msg.encode()

def parse_int(val, default=0):
    try:
        s = str(val).strip().rstrip('%')
        if '.' in s: return int(float(s))
        return int(s)
    except (ValueError, TypeError, AttributeError): return default

# ─── Metrics Collection ─────────────────────────────────────────────────────

_last_cpu = None

def _get_cpu_percent():
    global _last_cpu
    if not os.path.exists("/proc/stat"):
        return 0
    with open("/proc/stat") as f:
        parts = f.readline().strip().split()[1:5]
    cur = [int(x) for x in parts]
    if _last_cpu:
        prev_total = sum(_last_cpu)
        cur_total = sum(cur)
        total_delta = cur_total - prev_total
        idle_delta = cur[3] - _last_cpu[3]
        if total_delta > 0:
            result = round((1 - idle_delta / total_delta) * 100, 1)
            _last_cpu = cur
            return result
    _last_cpu = cur
    return 0

def collect_metrics():
    cpu_usage = _get_cpu_percent()
    mem = {}
    if os.path.exists("/proc/meminfo"):
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1); v = int(v.strip().split()[0]) // 1024
                if k == "MemTotal": mem["total"] = v
                elif k == "MemAvailable": mem["available"] = v
                elif k == "MemFree": mem["free"] = v
                elif k == "Buffers": mem["buffers"] = v
                elif k == "Cached": mem["cached"] = v
        if "total" in mem:
            mem["used"] = mem["total"] - mem.get("available", 0)
            mem["percent"] = round(mem["used"] / mem["total"] * 100, 1)

    disk = {}
    try:
        r = subprocess.run(["df", "-B1", "/"], capture_output=True, text=True, timeout=5)
        p = r.stdout.strip().split("\n")[1].split()
        disk.update(total=int(p[1])//(1024**3), used=int(p[2])//(1024**3),
                    available=int(p[3])//(1024**3), percent=p[4].rstrip("%"))
    except Exception:
        pass

    ld, _, _ = run("cat", "/proc/loadavg")
    load = ld.split()[:3] if ld else []

    net = {}
    if os.path.exists("/proc/net/dev"):
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" in line:
                    iface, data = line.split(":")
                    iface = iface.strip()
                    if iface == "lo": continue
                    parts = data.strip().split()
                    if len(parts) >= 10:
                        net[iface] = {
                            "rx_bytes": parse_int(parts[0]),
                            "tx_bytes": parse_int(parts[8]),
                            "rx_packets": parse_int(parts[1]),
                            "tx_packets": parse_int(parts[9]),
                        }

    disk_io = {}
    if os.path.exists("/proc/diskstats"):
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 14:
                    name = parts[2]
                    if name.startswith(("sd", "vd")):
                        rest = name[2:] if name.startswith("sd") else name[2:]
                        # sda → rest='a', sda1 → rest='a1', only partition if trailing digits
                        if rest and rest[-1].isdigit() and any(c.isalpha() for c in rest):
                            continue  # partition
                    elif name.startswith("nvme"):
                        if "p" in name and name.rsplit("p", 1)[-1].isdigit():
                            continue  # partition (e.g., nvme0n1p1)
                    elif name.startswith("mmcblk"):
                        if "p" in name:
                            continue  # partition (e.g., mmcblk0p1)
                    else:
                        continue  # not a recognized disk type
                    disk_io[name] = {
                        "reads": parse_int(parts[3]),
                        "reads_merged": parse_int(parts[4]),
                        "read_sectors": parse_int(parts[5]),
                        "read_time": parse_int(parts[6]),
                        "writes": parse_int(parts[7]),
                        "writes_merged": parse_int(parts[8]),
                        "write_sectors": parse_int(parts[9]),
                        "write_time": parse_int(parts[10]),
                    }

    temp = None
    try:
        tz_paths = sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
        for tz in tz_paths:
            try:
                val = int(tz.read_text().strip()) / 1000
                if temp is None: temp = val
            except Exception:
                pass
    except Exception:
        pass

    upt = 0
    if os.path.exists("/proc/uptime"):
        upt = float(open("/proc/uptime").read().split()[0])
    days, rem = divmod(upt, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60

    snapshot = {
        "timestamp": time.time(),
        "cpu": {"usage": cpu_usage},
        "memory": mem,
        "disk": disk,
        "load": load,
        "network": net,
        "disk_io": disk_io,
        "temperature": temp,
        "uptime": f"{int(days)}d {int(hours)}h {int(mins)}m",
    }

    with _history_lock:
        if metrics_history:
            prev = metrics_history[-1]
            dt = snapshot["timestamp"] - prev["timestamp"]
            if dt > 0:
                net_rates = {}
                for iface, cur in net.items():
                    if iface in prev.get("network", {}):
                        p = prev["network"][iface]
                        net_rates[iface] = {
                            "rx_rate": round((cur["rx_bytes"] - p["rx_bytes"]) / dt, 1),
                            "tx_rate": round((cur["tx_bytes"] - p["tx_bytes"]) / dt, 1),
                            "rx_pkt_rate": round((cur["rx_packets"] - p["rx_packets"]) / dt, 1),
                            "tx_pkt_rate": round((cur["tx_packets"] - p["tx_packets"]) / dt, 1),
                        }
                snapshot["network_rates"] = net_rates

                disk_rates = {}
                for dname, cur in disk_io.items():
                    if dname in prev.get("disk_io", {}):
                        p = prev["disk_io"][dname]
                        disk_rates[dname] = {
                            "read_rate": round((cur["reads"] - p["reads"]) / dt, 1),
                            "write_rate": round((cur["writes"] - p["writes"]) / dt, 1),
                            "read_sector_rate": round((cur["read_sectors"] - p["read_sectors"]) / dt, 1),
                            "write_sector_rate": round((cur["write_sectors"] - p["write_sectors"]) / dt, 1),
                        }
                snapshot["disk_io_rates"] = disk_rates
    return snapshot

def compute_health(metrics):
    scores = []
    if "cpu" in metrics and "usage" in metrics["cpu"]:
        scores.append(max(0, 100 - metrics["cpu"]["usage"]))
    if "memory" in metrics and "percent" in metrics["memory"]:
        scores.append(max(0, 100 - metrics["memory"]["percent"]))
    if "disk" in metrics and "percent" in metrics["disk"]:
        scores.append(max(0, 100 - parse_int(metrics["disk"]["percent"])))
    if metrics.get("temperature") is not None:
        t = metrics["temperature"]
        if t > 90: scores.append(10)
        elif t > 80: scores.append(30)
        elif t > 70: scores.append(60)
        elif t > 60: scores.append(80)
        else: scores.append(95)
    return round(sum(scores) / len(scores), 1) if scores else 100

def get_active_alerts(metrics):
    alerts = []
    cpu = metrics.get("cpu", {}).get("usage", 0)
    mem = metrics.get("memory", {}).get("percent", 0)
    disk_pct = parse_int(metrics.get("disk", {}).get("percent", 0))
    temp = metrics.get("temperature")

    with _alert_lock:
        if cpu >= alert_thresholds["cpu_crit"]:
            alerts.append({"type": "cpu", "severity": "critical", "value": cpu, "message": f"CPU at {cpu}%"})
        elif cpu >= alert_thresholds["cpu_warn"]:
            alerts.append({"type": "cpu", "severity": "warning", "value": cpu, "message": f"CPU at {cpu}%"})

        if mem >= alert_thresholds["mem_crit"] and mem > 0:
            alerts.append({"type": "memory", "severity": "critical", "value": mem, "message": f"Memory at {mem}%"})
        elif mem >= alert_thresholds["mem_warn"] and mem > 0:
            alerts.append({"type": "memory", "severity": "warning", "value": mem, "message": f"Memory at {mem}%"})

        if disk_pct >= alert_thresholds["disk_crit"] and disk_pct > 0:
            alerts.append({"type": "disk", "severity": "critical", "value": disk_pct, "message": f"Disk at {disk_pct}%"})
        elif disk_pct >= alert_thresholds["disk_warn"] and disk_pct > 0:
            alerts.append({"type": "disk", "severity": "warning", "value": disk_pct, "message": f"Disk at {disk_pct}%"})

        if temp is not None:
            if temp >= alert_thresholds["temp_crit"]:
                alerts.append({"type": "temperature", "severity": "critical", "value": temp, "message": f"Temperature {temp}°C"})
            elif temp >= alert_thresholds["temp_warn"]:
                alerts.append({"type": "temperature", "severity": "warning", "value": temp, "message": f"Temperature {temp}°C"})
    return alerts

def metrics_collector_loop():
    global _collector_started
    _collector_started = True
    time.sleep(1)
    while not _server_shutdown:
        try:
            snapshot = collect_metrics()
            snapshot["health"] = compute_health(snapshot)
            snapshot["alerts"] = get_active_alerts(snapshot)
            with _history_lock:
                metrics_history.append(snapshot)
                _metrics_cond.notify_all()
        except Exception:
            traceback.print_exc()
        for _ in range(50):
            if _server_shutdown:
                break
            time.sleep(0.1)

# ─── Log Reader ─────────────────────────────────────────────────────────────

def read_journal(unit=None, priority=None, lines=50, since=None, until=None, follow=False):
    cmd = ["journalctl", "--no-pager", "-o", "json"]
    if follow:
        cmd = ["journalctl", "-f", "-o", "json", "--no-pager"]
    if unit:
        cmd.extend(["-u", unit])
    if priority:
        cmd.extend(["-p", priority])
    if lines and not follow:
        cmd.extend(["-n", str(lines)])
    if since:
        cmd.extend(["--since", since])
    if until:
        cmd.extend(["--until", until])
    return cmd

def parse_log_line(line):
    try:
        entry = json.loads(line)
        ts = entry.get("__REALTIME_TIMESTAMP", "")
        if ts:
            try:
                ts_sec = int(ts) / 1000000
                entry["_time"] = datetime.fromtimestamp(ts_sec).strftime("%H:%M:%S")
                entry["_date"] = datetime.fromtimestamp(ts_sec).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                entry["_time"] = ts
                entry["_date"] = ts
        else:
            entry["_time"] = ""
            entry["_date"] = ""
        entry["_message"] = entry.get("MESSAGE", "")
        entry["_priority"] = entry.get("PRIORITY", "6")
        entry["_unit"] = entry.get("_SYSTEMD_UNIT", entry.get("SYSLOG_IDENTIFIER", "unknown"))
        prio_map = {"0": "emerg", "1": "alert", "2": "crit", "3": "err",
                     "4": "warning", "5": "notice", "6": "info", "7": "debug"}
        entry["_priority_str"] = prio_map.get(entry["_priority"], "info")
        return entry
    except json.JSONDecodeError:
        return None

# ─── API Handlers ───────────────────────────────────────────────────────────

def handle_api(path, params, body):
    # ── System ──────────────────────────────────────────────────────────
    if path == "/api/system/info":
        hn, _, _ = run("hostname")
        kr, _, _ = run("uname", "-r")
        upt = 0
        if os.path.exists("/proc/uptime"):
            upt = float(open("/proc/uptime").read().split()[0])
        d, r = divmod(upt, 86400)
        h, r = divmod(r, 3600)
        m = r // 60
        return json_resp({"hostname": hn, "os": "Omarchy (Arch Linux)", "kernel": kr,
                          "uptime": f"{int(d)}d {int(h)}h {int(m)}m", "desktop": "Hyprland"})

    if path == "/api/system/stats":
        return json_resp(collect_metrics())

    if path == "/api/system/action":
        if not body: return api_error("no body")
        action = body.get("action")
        cmds = {"lock": ["omarchy", "system", "lock"], "logout": ["omarchy", "system", "logout"],
                "reboot": ["omarchy", "system", "reboot"], "shutdown": ["omarchy", "system", "shutdown"],
                "update": ["omarchy", "update"]}
        if action in cmds:
            try:
                subprocess.Popen(cmds[action])
            except FileNotFoundError:
                pass
            return json_resp({"ok": True, "action": action})
        return api_error("unknown action")

    if path == "/api/system/updates":
        o, _, _ = run("omarchy", "update", "available")
        return json_resp({"available": bool(o), "version": o or None})

    # ── System: Processes ───────────────────────────────────────────────
    if path == "/api/system/processes":
        sort_by = params.get("sort", ["cpu"])[0]
        limit = min(parse_int(params.get("limit", ["50"])[0], 50), 200)
        try:
            r = subprocess.run(
                ["ps", f"--sort=-%{sort_by}", "axo", "pid,ppid,user,%cpu,%mem,rss,vsz,stat,start,time,comm:30,args:80"],
                capture_output=True, text=True, timeout=5
            )
            lines = r.stdout.strip().split("\n")
            if len(lines) < 2:
                return json_resp({"processes": []})
            procs = []
            for line in lines[1:limit+1]:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    procs.append({
                        "pid": parts[0], "ppid": parts[1], "user": parts[2],
                        "cpu": parts[3], "mem": parts[4], "rss": parts[5],
                        "vsz": parts[6], "stat": parts[7], "start": parts[8],
                        "time": parts[9], "command": parts[10][:80],
                    })
            return json_resp({"processes": procs, "total": len(procs)})
        except Exception as e:
            return api_error(str(e))

    if path == "/api/system/kill":
        if not body: return api_error("no body")
        pid = body.get("pid", "")
        signal_num = body.get("signal", 15)
        try:
            subprocess.run(["kill", f"-{signal_num}", str(pid)], capture_output=True, text=True, timeout=5)
            return json_resp({"ok": True})
        except Exception as e:
            return api_error(str(e))

    # ── System: Metrics History ─────────────────────────────────────────
    if path == "/api/system/metrics/history":
        with _history_lock:
            data = list(metrics_history)
        return json_resp({"history": data, "count": len(data)})

    # ── System: Health ──────────────────────────────────────────────────
    if path == "/api/system/health":
        with _history_lock:
            snapshot = metrics_history[-1] if metrics_history else collect_metrics()
        health = compute_health(snapshot) if snapshot else 100
        alerts = get_active_alerts(snapshot) if snapshot else []
        return json_resp({"health": health, "alerts": alerts, "status": "healthy" if health >= 70 else "degraded" if health >= 40 else "critical"})

    # ── System: Alerts config ───────────────────────────────────────────
    if path == "/api/system/alerts":
        if body:
            with _alert_lock:
                for k in alert_thresholds:
                    if k in body:
                        alert_thresholds[k] = parse_int(body[k], alert_thresholds[k])
            return json_resp({"ok": True, "thresholds": dict(alert_thresholds)})
        return json_resp({"thresholds": dict(alert_thresholds)})

    # ── System: Network I/O ─────────────────────────────────────────────
    if path == "/api/system/network":
        with _history_lock:
            data = list(metrics_history)
        ifaces = set()
        for snap in data:
            for iface in snap.get("network_rates", {}):
                ifaces.add(iface)
        result = {}
        for iface in sorted(ifaces):
            result[iface] = []
            for snap in data:
                rates = snap.get("network_rates", {}).get(iface, {})
                result[iface].append({
                    "t": snap["timestamp"],
                    "rx": rates.get("rx_rate", 0),
                    "tx": rates.get("tx_rate", 0),
                })
        return json_resp({"interfaces": list(ifaces), "series": result})

    # ── System: Disk I/O ────────────────────────────────────────────────
    if path == "/api/system/disk-io":
        with _history_lock:
            data = list(metrics_history)
        disks = set()
        for snap in data:
            for dname in snap.get("disk_io_rates", {}):
                disks.add(dname)
        result = {}
        for dname in sorted(disks):
            result[dname] = []
            for snap in data:
                rates = snap.get("disk_io_rates", {}).get(dname, {})
                result[dname].append({
                    "t": snap["timestamp"],
                    "reads": rates.get("read_rate", 0),
                    "writes": rates.get("write_rate", 0),
                })
        return json_resp({"disks": list(disks), "series": result})

    # ── System: Temperature ─────────────────────────────────────────────
    if path == "/api/system/temperature":
        temps = []
        try:
            for tz in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
                try:
                    val = int(tz.read_text().strip()) / 1000
                    type_path = tz.parent / f"{tz.stem}/type"
                    ttype = type_path.read_text().strip() if type_path.exists() else tz.stem
                    temps.append({"name": ttype, "temp": val})
                except Exception:
                    pass
        except Exception:
            pass
        return json_resp({"temperatures": temps})

    # ── Logs ────────────────────────────────────────────────────────────
    if path == "/api/logs":
        unit = params.get("unit", [None])[0]
        priority = params.get("priority", [None])[0]
        lines = parse_int(params.get("lines", [50])[0], 50)
        since = params.get("since", [None])[0]
        until = params.get("until", [None])[0]
        search = params.get("search", [None])[0]
        cmd = read_journal(unit=unit, priority=priority, lines=min(lines, 500), since=since, until=until)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            entries = []
            for line in r.stdout.strip().split("\n"):
                if not line.strip(): continue
                entry = parse_log_line(line)
                if entry:
                    if search and search.lower() not in entry.get("_message", "").lower():
                        continue
                    entries.append(entry)
            return json_resp({"entries": entries, "count": len(entries), "command": " ".join(cmd)})
        except Exception as e:
            return api_error(str(e))

    # ── Logs: Units ─────────────────────────────────────────────────────
    if path == "/api/logs/units":
        try:
            r = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
                capture_output=True, text=True, timeout=10
            )
            units = []
            for line in r.stdout.strip().split("\n"):
                parts = line.split(None, 4)
                if len(parts) >= 1:
                    units.append(parts[0])
            return json_resp({"units": sorted(set(units))})
        except Exception as e:
            return api_error(str(e))

    # ── Version ─────────────────────────────────────────────────────────
    if path == "/api/version":
        o, _, _ = run("omarchy", "version")
        return json_resp({"version": o.strip() if o else "unknown"})

    # ── Hyprland ─────────────────────────────────────────────────────────
    if path == "/api/hyprland/configs":
        configs = {}
        for f in sorted(CONFIG_HYPR.glob("*.conf")):
            configs[f.stem] = {"path": str(f), "content": read_file(f)}
        return json_resp(configs)

    if path == "/api/hyprland/config":
        name = params.get("name", [""])[0]
        cf = CONFIG_HYPR / f"{name}.conf"
        if body and "content" in body:
            if write_file(cf, body["content"]):
                subprocess.Popen(["hyprctl", "reload"])
                return json_resp({"ok": True})
            return api_error("write failed", 500)
        return json_resp({"name": name, "content": read_file(cf)})

    if path == "/api/hyprland/keybindings":
        o, _, _ = run("omarchy", "menu", "keybindings", "--print")
        return json_resp({"bindings": o.split("\n") if o else []})

    if path == "/api/hyprland/info":
        o, _, _ = run("hyprctl", "version")
        return json_resp({"version": o})

    if path == "/api/hyprland/looknfeel":
        return json_resp({"content": read_file(CONFIG_HYPR / "looknfeel.conf")})

    # ── Waybar ───────────────────────────────────────────────────────────
    if path == "/api/waybar/config":
        return json_resp({"content": read_file(HOME / ".config/waybar/config.jsonc")})

    # ── Themes ───────────────────────────────────────────────────────────
    if path == "/api/themes":
        o, _, _ = run("omarchy", "theme", "list")
        c, _, _ = run("omarchy", "theme", "current")
        tl = [t.strip() for t in o.split("\n") if t.strip()] if o else []
        return json_resp({"themes": tl, "current": c.strip()})

    if path == "/api/themes/set" and body:
        run("omarchy", "theme", "set", body.get("name", ""))
        return json_resp({"ok": True})

    if path == "/api/themes/bg-next":
        subprocess.Popen(["omarchy", "theme", "bg", "next"])
        return json_resp({"ok": True})

    if path == "/api/themes/bg-current":
        o, _, _ = run("omarchy", "theme", "bg", "current")
        return json_resp({"background": o.strip() if o else None})

    # ── Fonts ────────────────────────────────────────────────────────────
    if path == "/api/fonts":
        o, _, _ = run("omarchy", "font", "list")
        c, _, _ = run("omarchy", "font", "current")
        fl = [f.strip() for f in o.split("\n") if f.strip()] if o else []
        return json_resp({"fonts": fl, "current": c.strip()})

    if path == "/api/fonts/set" and body:
        run("omarchy", "font", "set", body.get("name", ""))
        return json_resp({"ok": True})

    # ── Services ─────────────────────────────────────────────────────────
    if path == "/api/services":
        items = {"waybar": "waybar", "walker": "walker", "hyprland": "hyprctl",
                 "hypridle": "hypridle", "mako": "mako", "swayosd": "swayosd"}
        result = {}
        for name, svc in items.items():
            o, e, c = run("omarchy", "restart", svc)
            result[name] = {"status": "ok" if c == 0 else "error", "output": o or e}
        return json_resp(result)

    if path == "/api/services/restart" and body:
        name = body.get("service", "")
        o, e, c = run("omarchy", "restart", name)
        return json_resp({"ok": c == 0, "service": name, "output": o or e})

    if path == "/api/services/status":
        items = {"waybar": "waybar", "walker": "walker",
                 "hypridle": "hypridle", "mako": "mako", "swayosd": "swayosd"}
        result = {}
        for name, svc in items.items():
            o, _, _ = run("systemctl", "--user", "is-active", svc)
            result[name] = o if o else "unknown"
        return json_resp(result)

    # ── Toggles ──────────────────────────────────────────────────────────
    if path == "/api/toggles":
        items = {"nightlight": "nightlight", "idle": "idle",
                 "notification-silencing": "notification-silencing", "hybrid-gpu": "hybrid-gpu"}
        result = {}
        for k, v in items.items():
            out, _, _ = run("omarchy", "toggle", "enabled", v)
            result[k] = out == "true"
        return json_resp(result)

    if path == "/api/toggles/set" and body:
        name = body.get("name", "")
        subprocess.Popen(["omarchy", "toggle", name])
        return json_resp({"ok": True})

    # ── Packages ─────────────────────────────────────────────────────────
    if path == "/api/packages":
        return json_resp({"packages": []})

    if path == "/api/packages/add" and body:
        name = body.get("name", "")
        o, e, c = run("omarchy", "pkg", "add", name)
        return json_resp({"ok": c == 0, "package": name, "output": o or e})

    # ── Control: Restart server ──────────────────────────────────────────
    if path == "/api/control/restart":
        subprocess.Popen(["omarchy", "restart", "control"])
        return json_resp({"ok": True})

    return json_resp({"error": "not found"}, 404)


def handle_sse(path, params, wfile, close_event):
    try:
        if path == "/api/metrics/stream":
            wfile.write(b"event: connected\ndata: {}\n\n")
            wfile.flush()
            while not close_event.is_set():
                with _metrics_cond:
                    _metrics_cond.wait(timeout=2)
                    if close_event.is_set():
                        break
                    if not metrics_history:
                        continue
                    snapshot = metrics_history[-1]
                try:
                    msg = f"event: metrics\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                    wfile.write(msg.encode())
                    wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
            return

        if path == "/api/logs/stream":
            unit = params.get("unit", [None])[0]
            priority = params.get("priority", [None])[0]
            wfile.write(b"event: connected\ndata: {}\n\n")
            wfile.flush()
            cmd = ["journalctl", "-f", "-o", "json", "--no-pager", "-n", "10"]
            if unit:
                cmd.extend(["-u", unit])
            if priority:
                cmd.extend(["-p", priority])
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, bufsize=1)
                for line in proc.stdout:
                    if close_event.is_set():
                        break
                    line = line.strip()
                    if not line:
                        continue
                    entry = parse_log_line(line)
                    if entry:
                        msg = f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
                        wfile.write(msg.encode())
                        wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    pass
            return

    except Exception:
        traceback.print_exc()

# ─── HTTP Handler ───────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(FRONTEND), **kw)

    def do_GET(self):
        parsed = urlparse(self.path)
        sse_paths = {"/api/metrics/stream", "/api/logs/stream"}

        if parsed.path in sse_paths:
            close_event = threading.Event()
            def check_close():
                while not close_event.is_set():
                    try:
                        self.rfile.read(1)
                    except Exception:
                        close_event.set()
                        break
            monitor = threading.Thread(target=check_close, daemon=True)
            monitor.start()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                params = parse_qs(parsed.query)
                handle_sse(parsed.path, params, self.wfile, close_event)
            except Exception:
                traceback.print_exc()
            finally:
                close_event.set()
            return

        if parsed.path.startswith("/api/"):
            try:
                params = parse_qs(parsed.query)
                status, headers, body = handle_api(parsed.path, params, None)
            except Exception as e:
                traceback.print_exc()
                status, headers, body = 500, {"Content-Type": "application/json"}, json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(status)
            for k, v in headers.items(): self.send_header(k, v)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            path = parsed.path
            if path == "/":
                path = "/index.html"
            filepath = FRONTEND / path.lstrip("/")
            if filepath.is_file() and (filepath.parent == FRONTEND or FRONTEND in filepath.parents):
                data = filepath.read_bytes()
                ctype = "text/html" if path.endswith(".html") else \
                        "text/css" if path.endswith(".css") else \
                        "application/javascript" if path.endswith(".js") else \
                        "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw) if raw else {}
                status, headers, resp = handle_api(parsed.path, {}, body)
            except Exception as e:
                traceback.print_exc()
                status, headers, resp = 500, {"Content-Type": "application/json"}, json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(status)
            for k, v in headers.items(): self.send_header(k, v)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *a):
        print(f"[{self.log_date_time_string()}] {a[0]} {a[1]} {a[2]}")

# ─── Main ───────────────────────────────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    def _handle_signal(s, f):
        global _server_shutdown
        _server_shutdown = True
        os._exit(0)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    collector = threading.Thread(target=metrics_collector_loop, daemon=True)
    collector.start()
    while not _collector_started:
        time.sleep(0.1)

    httpd = ThreadedHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"🚀  Omarchy Control running at http://localhost:{PORT}")
    print(f"    Dashboard  → http://localhost:{PORT}/")
    print(f"    API        → http://localhost:{PORT}/api/system/info")
    print(f"    Metrics SSE → http://localhost:{PORT}/api/metrics/stream")
    print(f"    Logs SSE   → http://localhost:{PORT}/api/logs/stream")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.shutdown()
