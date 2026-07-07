"""Integration tests for the HTTP server."""
import json, os, sys, threading, time, socket, http.client
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import server


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


class _SilentHandler(server.Handler):
    def log_message(self, fmt, *a):
        pass


class _TestServerContext:
    def __init__(self):
        self.port = _get_free_port()
        self.server = server.ThreadedHTTPServer(("127.0.0.1", self.port), _SilentHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.1)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.server.shutdown()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, json.loads(data) if data else {}
        finally:
            conn.close()

    def post(self, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {"Content-Type": "application/json"} if body else {}
            conn.request("POST", path, json.dumps(body) if body else None, headers)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, json.loads(data) if data else {}
        finally:
            conn.close()


@patch('server.run')
def test_integration_system_info(mock_run):
    mock_run.side_effect = [
        ("testhost", "", 0),
        ("6.0-arch", "", 0),
    ]
    with patch('os.path.exists', return_value=True):
        with patch('builtins.open', mock_open(read_data="123456.78\n")):
            status, headers, body = server.handle_api("/api/system/info", {}, None)
            data = json.loads(body)
            assert status == 200
            assert data["hostname"] == "testhost"


@patch('server.collect_metrics')
def test_integration_system_stats_no_proc(mock_metrics):
    mock_metrics.return_value = {
        "timestamp": 100, "cpu": {"usage": 0}, "memory": {},
        "disk": {}, "load": [], "network": {}, "disk_io": {},
        "temperature": None, "uptime": "0d 0h 0m"
    }
    status, headers, body = server.handle_api("/api/system/stats", {}, None)
    assert status == 200


@patch('server.collect_metrics')
def test_integration_health_endpoint(mock_metrics):
    mock_metrics.return_value = {
        "timestamp": 100, "cpu": {"usage": 10}, "memory": {"percent": 20},
        "disk": {"percent": "30"}, "load": ["0.5"], "network": {},
        "disk_io": {}, "temperature": 40, "uptime": "5d 0h 0m"
    }
    with server._history_lock:
        server.metrics_history.clear()
        server.metrics_history.append(mock_metrics.return_value)

    status, headers, body = server.handle_api("/api/system/health", {}, None)
    data = json.loads(body)
    assert status == 200
    assert "health" in data
    assert "status" in data
    assert "alerts" in data

    server.metrics_history.clear()


def test_sse_metrics_handler():
    with server._history_lock:
        server.metrics_history.clear()
        server.metrics_history.append({
            "timestamp": time.time(), "cpu": {"usage": 10},
            "memory": {"percent": 20}, "disk": {"percent": "30"},
            "load": ["0.5"], "network": {}, "disk_io": {},
            "temperature": 40, "uptime": "1d 0h 0m",
            "health": 100, "alerts": []
        })

    mock_wfile = MagicMock()
    close_event = threading.Event()
    close_event.set()

    server.handle_sse("/api/metrics/stream", {}, mock_wfile, close_event)
    server.metrics_history.clear()
    assert mock_wfile.write.called


def test_sse_options():
    status, headers, body = server.json_resp_cors({"ok": True})
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_frontend_path():
    expected = Path(__file__).resolve().parent.parent / "frontend"
    assert server.FRONTEND.resolve() == expected.resolve()
    assert (server.FRONTEND / "index.html").exists()
    assert (server.FRONTEND / "app.js").exists()
    assert (server.FRONTEND / "style.css").exists()


def test_frontend_config_path():
    assert str(server.CONFIG_HYPR) == str(Path.home() / ".config" / "hypr")


def test_server_live():
    with _TestServerContext() as srv:
        status, data = srv.get("/api/version")
        assert status == 200


def test_server_404():
    with _TestServerContext() as srv:
        status, data = srv.get("/api/nonexistent")
        assert status == 404
        assert "error" in data


def test_server_post():
    with _TestServerContext() as srv:
        status, data = srv.post("/api/system/action", {"action": "lock"})
        assert status == 200
        assert data.get("ok") is True
