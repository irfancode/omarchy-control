"""Tests for API endpoint handlers."""
import json, os, sys, tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import server

# ─── System API ─────────────────────────────────────────────────────────────

@patch('server.run')
def test_system_info(mock_run):
    mock_run.side_effect = [
        ("myhost", "", 0),
        ("6.12.0-arch1-1", "", 0),
    ]
    with patch('os.path.exists', return_value=True):
        with patch('builtins.open', mock_open(read_data="123456.78 98765.43\n")):
            status, headers, body = server.handle_api("/api/system/info", {}, None)
            data = json.loads(body)
            assert data["hostname"] == "myhost"
            assert data["kernel"] == "6.12.0-arch1-1"
            assert data["os"] == "Omarchy (Arch Linux)"
            assert "uptime" in data
            assert "d" in data["uptime"]

def test_system_info_no_proc():
    with patch('os.path.exists', return_value=False):
        with patch('server.run') as mock_run:
            mock_run.side_effect = [("host", "", 0), ("6.0", "", 0)]
            status, headers, body = server.handle_api("/api/system/info", {}, None)
            data = json.loads(body)
            assert data["uptime"] == "0d 0h 0m"

@patch('server.run')
def test_system_updates_available(mock_run):
    mock_run.return_value = ("v2.0.0", "", 0)
    status, headers, body = server.handle_api("/api/system/updates", {}, None)
    data = json.loads(body)
    assert data["available"] is True
    assert data["version"] == "v2.0.0"

@patch('server.run')
def test_system_updates_none(mock_run):
    mock_run.return_value = ("", "", 0)
    status, headers, body = server.handle_api("/api/system/updates", {}, None)
    data = json.loads(body)
    assert data["available"] is False

@patch('server.subprocess.Popen')
def test_system_action_lock(mock_popen):
    status, headers, body = server.handle_api("/api/system/action", {}, {"action": "lock"})
    data = json.loads(body)
    assert data["ok"] is True
    assert data["action"] == "lock"

def test_system_action_invalid():
    status, headers, body = server.handle_api("/api/system/action", {}, {"action": "invalid"})
    assert status == 400
    data = json.loads(body)
    assert data["ok"] is False

def test_system_action_no_body():
    status, headers, body = server.handle_api("/api/system/action", {}, None)
    assert status == 400

# ─── Processes API ──────────────────────────────────────────────────────────

@patch('server.subprocess.run')
def test_system_processes(mock_run):
    ps_output = """  PID  PPID USER     %CPU %MEM   RSS   VSZ STAT START   TIME COMMAND                                        ARGS
    1     0 root      0.0  0.0 10000 200000 Ss   Jan01  0:00 /sbin/init                                       /sbin/init
  100     1 irfan     1.5  2.3 50000 1.5G S    Jul06  1:23 /usr/bin/python3                                  /usr/bin/python3 app.py
  200     1 irfan     0.5  1.0 30000 800M  R<   Jul06  0:45 nvim                                            nvim test.py
"""
    mock_run.return_value = MagicMock(stdout=ps_output, stderr="", returncode=0)

    status, headers, body = server.handle_api("/api/system/processes", {"sort": ["cpu"], "limit": ["10"]}, None)
    data = json.loads(body)
    assert "processes" in data
    assert len(data["processes"]) == 3
    assert data["processes"][0]["pid"] == "1"
    assert "nvim" in data["processes"][2]["command"]

@patch('server.subprocess.run')
def test_system_processes_error(mock_run):
    mock_run.side_effect = Exception("ps failed")
    status, headers, body = server.handle_api("/api/system/processes", {}, None)
    assert status == 400

# ─── Kill API ───────────────────────────────────────────────────────────────

@patch('server.subprocess.run')
def test_kill_process(mock_run):
    mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
    status, headers, body = server.handle_api("/api/system/kill", {}, {"pid": "123"})
    data = json.loads(body)
    assert data["ok"] is True

def test_kill_no_body():
    status, headers, body = server.handle_api("/api/system/kill", {}, None)
    assert status == 400

# ─── Health API ─────────────────────────────────────────────────────────────

def test_system_health():
    with server._history_lock:
        server.metrics_history.clear()
        server.metrics_history.append({
            "timestamp": 100, "cpu": {"usage": 10}, "memory": {"percent": 20},
            "disk": {"percent": "30"}, "temperature": 40
        })
    status, headers, body = server.handle_api("/api/system/health", {}, None)
    data = json.loads(body)
    assert data["health"] >= 80
    assert data["status"] == "healthy"
    server.metrics_history.clear()

# ─── Alerts Config API ──────────────────────────────────────────────────────

def test_alerts_get():
    status, headers, body = server.handle_api("/api/system/alerts", {}, None)
    data = json.loads(body)
    assert "thresholds" in data
    assert data["thresholds"]["cpu_warn"] == 80

def test_alerts_set():
    status, headers, body = server.handle_api("/api/system/alerts", {}, {"cpu_warn": 70})
    data = json.loads(body)
    assert data["ok"] is True
    assert data["thresholds"]["cpu_warn"] == 70
    server.alert_thresholds["cpu_warn"] = 80

# ─── Temperature API ────────────────────────────────────────────────────────

def test_temperature_api_no_sensors():
    with patch('server.Path.glob', return_value=[]):
        status, headers, body = server.handle_api("/api/system/temperature", {}, None)
        data = json.loads(body)
        assert data["temperatures"] == []

# ─── 404 ────────────────────────────────────────────────────────────────────

def test_not_found():
    status, headers, body = server.handle_api("/api/nonexistent", {}, None)
    assert status == 404

# ─── Version API ────────────────────────────────────────────────────────────

@patch('server.run')
def test_version(mock_run):
    mock_run.return_value = ("v1.0.0", "", 0)
    status, headers, body = server.handle_api("/api/version", {}, None)
    data = json.loads(body)
    assert data["version"] == "v1.0.0"

# ─── Hyprland API ───────────────────────────────────────────────────────────

def test_hyprland_configs_empty():
    """Test when no config files exist."""
    orig = server.CONFIG_HYPR
    server.CONFIG_HYPR = Path("/tmp/nonexistent_hypr_dir_xyz")
    try:
        status, headers, body = server.handle_api("/api/hyprland/configs", {}, None)
        data = json.loads(body)
        assert data == {}
    finally:
        server.CONFIG_HYPR = orig

# ─── Logs API ───────────────────────────────────────────────────────────────

@patch('server.subprocess.run')
def test_logs_api(mock_run):
    log_entry = json.dumps({
        "__REALTIME_TIMESTAMP": "1700000000000000",
        "MESSAGE": "test log message",
        "PRIORITY": "6",
        "_SYSTEMD_UNIT": "test.service",
        "SYSLOG_IDENTIFIER": "test"
    })
    mock_run.return_value = MagicMock(stdout=log_entry + "\n" + log_entry, stderr="", returncode=0)

    status, headers, body = server.handle_api("/api/logs", {"lines": ["10"]}, None)
    data = json.loads(body)
    assert len(data["entries"]) == 2
    assert data["entries"][0]["_message"] == "test log message"
    assert data["entries"][0]["_priority_str"] == "info"

@patch('server.subprocess.run')
def test_logs_api_with_search(mock_run):
    log1 = json.dumps({"__REALTIME_TIMESTAMP": "1700000000000000", "MESSAGE": "error in module", "PRIORITY": "3", "_SYSTEMD_UNIT": "test.service"})
    log2 = json.dumps({"__REALTIME_TIMESTAMP": "1700000000000001", "MESSAGE": "everything ok", "PRIORITY": "6", "_SYSTEMD_UNIT": "test.service"})
    mock_run.return_value = MagicMock(stdout=log1 + "\n" + log2, stderr="", returncode=0)

    status, headers, body = server.handle_api("/api/logs", {"lines": ["10"], "search": ["error"]}, None)
    data = json.loads(body)
    assert len(data["entries"]) == 1
    assert "error" in data["entries"][0]["_message"]

@patch('server.subprocess.run')
def test_logs_units(mock_run):
    mock_run.return_value = MagicMock(stdout="test.service    loaded active running Test\nsshd.service    loaded active running SSH\n", stderr="", returncode=0)

    status, headers, body = server.handle_api("/api/logs/units", {}, None)
    data = json.loads(body)
    assert "test.service" in data["units"]
    assert "sshd.service" in data["units"]

# ─── Log Parsing ────────────────────────────────────────────────────────────

def test_parse_log_line():
    line = json.dumps({
        "__REALTIME_TIMESTAMP": "1700000000000000",
        "MESSAGE": "test message",
        "PRIORITY": "3",
        "_SYSTEMD_UNIT": "ssh.service",
        "SYSLOG_IDENTIFIER": "sshd"
    })
    entry = server.parse_log_line(line)
    assert entry is not None
    assert entry["_message"] == "test message"
    assert entry["_priority_str"] == "err"
    assert entry["_unit"] == "ssh.service"
    assert "_time" in entry
    assert "_date" in entry

def test_parse_log_line_invalid_json():
    entry = server.parse_log_line("not json")
    assert entry is None

def test_parse_log_line_empty():
    entry = server.parse_log_line("")
    assert entry is None

def test_parse_log_line_priority_mapping():
    for prio, expected in [("0", "emerg"), ("1", "alert"), ("2", "crit"), ("3", "err"),
                           ("4", "warning"), ("5", "notice"), ("6", "info"), ("7", "debug")]:
        line = json.dumps({"MESSAGE": "test", "PRIORITY": prio, "__REALTIME_TIMESTAMP": "0"})
        entry = server.parse_log_line(line)
        assert entry["_priority_str"] == expected, f"Priority {prio} should map to {expected}"

def test_parse_log_line_default_priority():
    line = json.dumps({"MESSAGE": "test", "__REALTIME_TIMESTAMP": "0"})
    entry = server.parse_log_line(line)
    assert entry["_priority_str"] == "info"
