#!/usr/bin/env python3
"""Omarchy Control — Web-based desktop management for Omarchy/Hyprland.
Zero dependencies — uses only Python stdlib."""

import json, os, subprocess, re, traceback
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("OMARCHY_CONTROL_PORT", 8765))
HOME = Path.home()
CONFIG_HYPR = HOME / ".config" / "hypr"
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

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

def api_error(msg, status=400):
    return json_resp({"ok": False, "error": msg}, status)

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
        cpu = {}
        if os.path.exists("/proc/stat"):
            with open("/proc/stat") as f:
                p = f.readline().strip().split()[1:5]
                t = sum(int(x) for x in p)
                cpu["usage"] = round((1 - int(p[3]) / t) * 100, 1) if t else 0
        mem = {}
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1); v = int(v.strip().split()[0]) // 1024
                    if k == "MemTotal": mem["total"] = v
                    elif k == "MemAvailable": mem["available"] = v
            if "total" in mem:
                mem["used"] = mem["total"] - mem.get("available", 0)
                mem["percent"] = round(mem["used"] / mem["total"] * 100, 1)
        disk = {}
        try:
            r = subprocess.run(["df", "-B1", "/"], capture_output=True, text=True)
            p = r.stdout.strip().split("\n")[1].split()
            disk.update(total=int(p[1])//(1024**3), used=int(p[2])//(1024**3),
                        available=int(p[3])//(1024**3), percent=p[4].rstrip("%"))
        except Exception: pass
        ld, _, _ = run("cat", "/proc/loadavg")
        return json_resp({"cpu": cpu, "memory": mem, "disk": disk, "load": ld.split()[:3] if ld else []})

    if path == "/api/system/action":
        if not body: return api_error("no body")
        action = body.get("action")
        cmds = {"lock": ["omarchy", "system", "lock"], "logout": ["omarchy", "system", "logout"],
                "reboot": ["omarchy", "system", "reboot"], "shutdown": ["omarchy", "system", "shutdown"],
                "update": ["omarchy", "update"]}
        if action in cmds:
            subprocess.Popen(cmds[action])
            return json_resp({"ok": True, "action": action})
        return api_error("unknown action")

    if path == "/api/system/updates":
        o, _, _ = run("omarchy", "update", "available")
        return json_resp({"available": bool(o), "version": o or None})

    # ── Version ──────────────────────────────────────────────────────────
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
        return json_resp({"packages": []})  # omarchy pkg list requires admin

    if path == "/api/packages/add" and body:
        name = body.get("name", "")
        o, e, c = run("omarchy", "pkg", "add", name)
        return json_resp({"ok": c == 0, "package": name, "output": o or e})

    return json_resp({"error": "not found"}, 404)

# ─── HTTP Handler ───────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(FRONTEND), **kw)

    def do_GET(self):
        parsed = urlparse(self.path)
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
            # Serve static files from FRONTEND
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
    """Handle requests in separate threads for concurrency."""
    allow_reuse_address = True

if __name__ == "__main__":
    httpd = ThreadedHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"🚀  Omarchy Control running at http://localhost:{PORT}")
    print(f"    Dashboard  → http://localhost:{PORT}/")
    print(f"    API        → http://localhost:{PORT}/api/system/info")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.shutdown()
