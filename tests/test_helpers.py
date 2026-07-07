"""Tests for backend helper functions."""
import json, os, sys, tempfile, subprocess, time, threading
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import server

def test_json_resp():
    status, headers, body = server.json_resp({"ok": True})
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    data = json.loads(body)
    assert data == {"ok": True}

def test_json_resp_with_status():
    status, headers, body = server.json_resp({"error": "bad"}, 400)
    assert status == 400
    data = json.loads(body)
    assert data == {"error": "bad"}

def test_api_error():
    status, headers, body = server.api_error("test error", 404)
    assert status == 404
    data = json.loads(body)
    assert data == {"ok": False, "error": "test error"}

def test_api_error_default():
    status, headers, body = server.api_error("msg")
    assert status == 400

def test_read_file_exists():
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("hello world")
        tmp = f.name
    try:
        content = server.read_file(tmp)
        assert content == "hello world"
    finally:
        os.unlink(tmp)

def test_read_file_not_exists():
    content = server.read_file("/nonexistent/path")
    assert content == ""

def test_write_file():
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        tmp = f.name
    try:
        result = server.write_file(tmp, "new content")
        assert result is True
        assert Path(tmp).read_text() == "new content"
    finally:
        os.unlink(tmp)

def test_write_file_fails():
    result = server.write_file("/nonexistent/dir/file.txt", "content")
    assert result is False

def test_parse_int_valid():
    assert server.parse_int("42") == 42
    assert server.parse_int("0") == 0
    assert server.parse_int("-5") == -5

def test_parse_int_invalid():
    assert server.parse_int("abc") == 0
    assert server.parse_int(None) == 0
    assert server.parse_int("") == 0

def test_parse_int_float_string():
    assert server.parse_int("12.5") == 12

def test_parse_int_percent():
    assert server.parse_int("50%") == 50
    assert server.parse_int("12.5%") == 12

def test_run_success():
    out, err, rc = server.run("echo", "hello")
    assert out == "hello"
    assert rc == 0

def test_run_not_found():
    out, err, rc = server.run("nonexistent_cmd_xyz")
    assert rc == -1
    assert "command not found" in err

def test_run_timeout():
    out, err, rc = server.run("sleep", "5", timeout=1)
    assert rc == -1
    assert "timeout" in err

def test_sse_msg():
    data = {"key": "value"}
    msg = server.sse_msg(data)
    assert b"data:" in msg
    assert json.loads(msg.decode().split("data:")[1].strip()) == data

def test_sse_msg_with_event_type():
    data = {"key": "value"}
    msg = server.sse_msg(data, event="update")
    decoded = msg.decode()
    assert "event: update" in decoded
    assert "data:" in decoded

def test_json_resp_cors():
    status, headers, body = server.json_resp_cors({"ok": True})
    assert headers["Access-Control-Allow-Origin"] == "*"
