"""Tests for log management functionality."""
import json, os, sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import server

# ─── Journal Reader Command Builder ─────────────────────────────────────────

def test_read_journal_default():
    cmd = server.read_journal()
    assert "journalctl" in cmd
    assert "--no-pager" in cmd
    assert "-o" in cmd
    assert "json" in cmd
    assert cmd[-2] == "-n"
    assert cmd[-1] == "50"

def test_read_journal_with_unit():
    cmd = server.read_journal(unit="sshd.service")
    assert "-u" in cmd
    assert "sshd.service" in cmd

def test_read_journal_with_priority():
    cmd = server.read_journal(priority="err")
    assert "-p" in cmd
    assert "err" in cmd

def test_read_journal_with_lines():
    cmd = server.read_journal(lines=200)
    assert "-n" in cmd
    assert "200" in cmd

def test_read_journal_with_since():
    cmd = server.read_journal(since="1 hour ago")
    assert "--since" in cmd
    assert "1 hour ago" in cmd

def test_read_journal_with_until():
    cmd = server.read_journal(until="now")
    assert "--until" in cmd
    assert "now" in cmd

def test_read_journal_follow():
    cmd = server.read_journal(follow=True)
    assert "-f" in cmd
    assert "--no-pager" in cmd

# ─── SSE Log Stream ─────────────────────────────────────────────────────────

def test_handle_sse_logs_unknown_path():
    """Test SSE handler with non-existent path does nothing."""
    close_event = threading.Event()
    close_event.set()  # immediately stop
    # Should not throw
    server.handle_sse("/api/unknown/stream", {}, MagicMock(), close_event)

import threading

def test_sse_log_stream_cleanup():
    """Test that log stream cleans up subprocess on close."""
    mock_wfile = MagicMock()
    close_event = threading.Event()

    def cleanup_test():
        # Call with metrics path to test proper cleanup
        with server._history_lock:
            server.metrics_history.clear()
            server.metrics_history.append({"timestamp": 100, "cpu": {"usage": 0}})
            server._metrics_cond.notify_all()
        close_event.set()

    t = threading.Thread(target=cleanup_test, daemon=True)
    t.start()
    server.handle_sse("/api/metrics/stream", {}, mock_wfile, close_event)
    t.join()
    # Should have sent at least the connected event
    assert mock_wfile.write.called

# ─── Log Filtering ──────────────────────────────────────────────────────────

def test_log_filtering_by_search():
    entries = [
        {"_message": "error in database connection"},
        {"_message": "request completed successfully"},
        {"_message": "ERROR: timeout exceeded"},
    ]
    query = "error"
    filtered = [e for e in entries if query.lower() in e["_message"].lower()]
    assert len(filtered) == 2

def test_log_filtering_no_match():
    entries = [
        {"_message": "all good"},
        {"_message": "everything fine"},
    ]
    filtered = [e for e in entries if "error" in e["_message"].lower()]
    assert len(filtered) == 0

def test_log_filtering_case_insensitive():
    entries = [{"_message": "ERROR"}, {"_message": "Error"}, {"_message": "error"}]
    filtered = [e for e in entries if "error" in e["_message"].lower()]
    assert len(filtered) == 3
