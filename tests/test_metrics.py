"""Tests for metrics collection and history."""
import json, os, sys, tempfile, time, threading
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import server

# ─── Test collect_metrics ───────────────────────────────────────────────────

@patch('server.os.path.exists')
@patch('server.subprocess.run')
def test_collect_metrics_basic(mock_run, mock_exists):
    mock_exists.side_effect = lambda p: True

    stat_data = "cpu  1000 0 500 500000 0 0 0 0 0 0\n"
    meminfo_data = "MemTotal:       16384000 kB\nMemFree:         8192000 kB\nMemAvailable:   8192000 kB\nBuffers:         1024000 kB\nCached:          2048000 kB\n"
    uptime_data = "168766.52 123456.78\n"

    def fake_open(fname, *a, **kw):
        if 'stat' in str(fname):
            return mock_open(read_data=stat_data).return_value
        elif 'meminfo' in str(fname):
            return mock_open(read_data=meminfo_data).return_value
        elif 'uptime' in str(fname):
            return mock_open(read_data=uptime_data).return_value
        elif 'net/dev' in str(fname):
            return mock_open(read_data="").return_value
        elif 'diskstats' in str(fname):
            return mock_open(read_data="").return_value
        return mock_open().return_value

    with patch('builtins.open', fake_open):
        mock_run.return_value = MagicMock(stdout="Filesystem     1B-blocks        Used   Available Use%\n/dev/sda1  500000000000 250000000000 250000000000 50%\n", stderr="", returncode=0)
        result = server.collect_metrics()

    assert "timestamp" in result
    assert "cpu" in result
    assert "memory" in result
    assert "disk" in result
    assert "load" in result
    assert "network" in result
    assert "uptime" in result
    assert result["uptime"] != ""

def test_collect_metrics_cpu_calculation():
    server._last_cpu = None
    cpu = server._get_cpu_percent()
    assert cpu == 0

    server._last_cpu = [1000, 0, 500, 490000]
    with patch('builtins.open', mock_open(read_data="cpu  1050 0 520 491000 0 0 0 0 0 0\n")):
        cpu = server._get_cpu_percent()
        assert 6.0 <= cpu <= 7.0

@patch('server.os.path.exists', return_value=False)
@patch('server.subprocess.run')
def test_collect_metrics_no_proc(mock_run, mock_exists):
    mock_run.return_value = MagicMock(stdout="", stderr="error", returncode=-1)
    result = server.collect_metrics()
    assert result["cpu"]["usage"] == 0
    assert result["memory"] == {}

def test_collect_metrics_no_temp():
    with patch('server.Path.glob', return_value=[]):
        result = server.collect_metrics()
        assert result["temperature"] is None

# ─── Test Metrics History ──────────────────────────────────────────────────

def test_metrics_history_maxlen():
    assert server.MAX_HISTORY == 120

def test_metrics_history_append():
    with server._history_lock:
        server.metrics_history.clear()
        server.metrics_history.append({"timestamp": 100, "cpu": {"usage": 50}})
        server.metrics_history.append({"timestamp": 105, "cpu": {"usage": 60}})
        assert len(server.metrics_history) == 2
        server.metrics_history.clear()

def test_metrics_history_ring():
    with server._history_lock:
        server.metrics_history.clear()
        for i in range(150):
            server.metrics_history.append({"timestamp": i})
        assert len(server.metrics_history) == server.MAX_HISTORY
        assert server.metrics_history[0]["timestamp"] == 30
        assert server.metrics_history[-1]["timestamp"] == 149
        server.metrics_history.clear()

# ─── Test Health Score ─────────────────────────────────────────────────────

def test_compute_health_perfect():
    metrics = {"cpu": {"usage": 0}, "memory": {"percent": 0}, "disk": {"percent": "0"}, "temperature": 40}
    score = server.compute_health(metrics)
    assert score >= 95

def test_compute_health_partial():
    metrics = {"cpu": {"usage": 50}, "memory": {"percent": 50}}
    score = server.compute_health(metrics)
    assert 45 <= score <= 55

def test_compute_health_critical():
    metrics = {"cpu": {"usage": 100}, "memory": {"percent": 100}, "disk": {"percent": "100"}, "temperature": 95}
    score = server.compute_health(metrics)
    assert score <= 25

def test_compute_health_empty():
    assert server.compute_health({}) == 100

def test_compute_health_no_temp():
    metrics = {"cpu": {"usage": 10}, "memory": {"percent": 20}, "disk": {"percent": "30"}}
    score = server.compute_health(metrics)
    assert 80 <= score <= 95

# ─── Test Alerts ───────────────────────────────────────────────────────────

def test_get_active_alerts_none():
    metrics = {"cpu": {"usage": 10}, "memory": {"percent": 20}, "disk": {"percent": "30"}, "temperature": 40}
    alerts = server.get_active_alerts(metrics)
    assert len(alerts) == 0

def test_get_active_alerts_cpu_warning():
    metrics = {"cpu": {"usage": 85}, "memory": {"percent": 20}, "disk": {"percent": "30"}}
    alerts = server.get_active_alerts(metrics)
    types = [a["type"] for a in alerts]
    assert "cpu" in types
    assert any(a["severity"] == "warning" for a in alerts if a["type"] == "cpu")

def test_get_active_alerts_cpu_critical():
    metrics = {"cpu": {"usage": 98}, "memory": {"percent": 20}, "disk": {"percent": "30"}}
    alerts = server.get_active_alerts(metrics)
    cpu_alerts = [a for a in alerts if a["type"] == "cpu"]
    assert any(a["severity"] == "critical" for a in cpu_alerts)

def test_get_active_alerts_memory_warning():
    metrics = {"cpu": {"usage": 10}, "memory": {"percent": 88}, "disk": {"percent": "30"}}
    alerts = server.get_active_alerts(metrics)
    mem_alerts = [a for a in alerts if a["type"] == "memory"]
    assert len(mem_alerts) > 0

def test_get_active_alerts_disk():
    metrics = {"cpu": {"usage": 10}, "memory": {"percent": 20}, "disk": {"percent": "90"}}
    alerts = server.get_active_alerts(metrics)
    disk_alerts = [a for a in alerts if a["type"] == "disk"]
    assert len(disk_alerts) > 0

def test_get_active_alerts_temperature():
    metrics = {"cpu": {"usage": 10}, "memory": {"percent": 20}, "disk": {"percent": "30"}, "temperature": 85}
    alerts = server.get_active_alerts(metrics)
    temp_alerts = [a for a in alerts if a["type"] == "temperature"]
    assert len(temp_alerts) > 0

def test_get_active_alerts_multiple():
    metrics = {"cpu": {"usage": 90}, "memory": {"percent": 95}, "disk": {"percent": "98"}, "temperature": 92}
    alerts = server.get_active_alerts(metrics)
    assert len(alerts) >= 4

# ─── Test Alert Thresholds ─────────────────────────────────────────────────

def test_alert_thresholds_defaults():
    assert server.alert_thresholds["cpu_warn"] == 80
    assert server.alert_thresholds["cpu_crit"] == 95
    assert server.alert_thresholds["mem_warn"] == 85
    assert server.alert_thresholds["mem_crit"] == 95
    assert server.alert_thresholds["disk_warn"] == 85
    assert server.alert_thresholds["disk_crit"] == 95

# ─── Test Disk I/O Parsing ─────────────────────────────────────────────────

def test_collect_metrics_disk_io_parsing():
    diskstat_content = """   8       0 sda 10000 2000 500000 3000 5000 1000 250000 1500 0 2000 4500
   8       1 sda1 5000 1000 250000 1500 2500 500 125000 750 0 1000 2250
 259       0 nvme0n1 20000 4000 1000000 6000 10000 2000 500000 3000 0 4000 9000
"""
    stat_data = "cpu  1000 0 500 500000 0 0 0 0 0 0\n"
    meminfo_data = "MemTotal:       16384000 kB\nMemFree:         8192000 kB\nMemAvailable:   8192000 kB\n"
    uptime_data = "123456.78 65432.10\n"

    def fake_open(fname, *a, **kw):
        if 'diskstats' in str(fname):
            return mock_open(read_data=diskstat_content).return_value
        elif 'stat' in str(fname):
            return mock_open(read_data=stat_data).return_value
        elif 'meminfo' in str(fname):
            return mock_open(read_data=meminfo_data).return_value
        elif 'uptime' in str(fname):
            return mock_open(read_data=uptime_data).return_value
        return mock_open().return_value

    with patch('builtins.open', fake_open):
        with patch('server.os.path.exists', return_value=True):
            with patch('server.subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
                result = server.collect_metrics()
                assert "sda" in result["disk_io"]
                assert result["disk_io"]["sda"]["reads"] == 10000
                assert result["disk_io"]["sda"]["writes"] == 5000
                assert "nvme0n1" in result["disk_io"]
                assert "sda1" not in result["disk_io"]

def test_parse_int_disk_percent():
    assert server.parse_int("50%") == 50
