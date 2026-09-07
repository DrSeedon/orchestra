"""Server diagnostics must not block the HTTP loop when output exceeds a pipe."""
import subprocess
import sys
import urllib.request

import pytest

from tests import test_frontend as frontend


def test_dashboard_server_handles_output_larger_than_pipe(tmp_path, monkeypatch):
    popen = subprocess.Popen
    script = """
import http.server, os, sys
os.write(1, b'x' * 262144)
server = http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), http.server.SimpleHTTPRequestHandler)
server.serve_forever()
"""

    def start(args, **kwargs):
        port = args[args.index("--port") + 1]
        return popen([sys.executable, "-c", script, port], **kwargs)

    monkeypatch.setattr(frontend.subprocess, "Popen", start)
    monkeypatch.setattr(frontend, "_DASHBOARD_START_TIMEOUT_S", 5)
    proc, origin = frontend._start_dashboard_server(tmp_path / "test.db")
    try:
        with urllib.request.urlopen(origin, timeout=2) as response:
            assert response.status == 200
        assert len(frontend._dashboard_output_tail(proc)) <= 4000
    finally:
        frontend._stop_dashboard_server(proc)
    assert proc.poll() is not None
    assert proc.stdout.closed


def test_dashboard_server_preserves_failure_tail(tmp_path, monkeypatch):
    popen = subprocess.Popen
    marker = "diagnostic-end"

    def start(args, **kwargs):
        return popen([sys.executable, "-c", f"print('x' * 262144 + {marker!r}); raise SystemExit(7)"], **kwargs)

    monkeypatch.setattr(frontend.subprocess, "Popen", start)
    monkeypatch.setattr(frontend, "_DASHBOARD_START_TIMEOUT_S", 5)
    with pytest.raises(RuntimeError, match="exited 7") as exc:
        frontend._start_dashboard_server(tmp_path / "test.db")
    assert marker in str(exc.value)
    assert len(str(exc.value)) < 4200
