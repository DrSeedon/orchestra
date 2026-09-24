"""Real Uvicorn shutdown behavior while a dashboard SSE request is still open."""

import http.client
import os
import shlex
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "deploy" / "orchestra.service"
SERVICE_TEMPLATE = ROOT / "deploy" / "orchestra.service.template"
SHUTDOWN_LIMIT_S = 8


def _graceful_timeout_from_execstart(service: Path) -> int | None:
    for line in service.read_text(encoding="utf-8").splitlines():
        if not line.startswith("ExecStart="):
            continue
        argv = shlex.split(line.partition("=")[2])
        for index, arg in enumerate(argv[:-1]):
            if arg == "--timeout-graceful-shutdown":
                return int(argv[index + 1])
        return None
    raise AssertionError(f"ExecStart missing from {service}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_dashboard(port: int, process: subprocess.Popen, output_path: Path) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"uvicorn exited during startup ({process.returncode}):\n"
                f"{output_path.read_text(errors='replace')[-3000:]}"
            )
        try:
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                client.request("GET", "/api/orchestrators")
                response = client.getresponse()
                response.read()
                if response.status == 200:
                    return
            finally:
                client.close()
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError(f"uvicorn did not start:\n{output_path.read_text(errors='replace')[-3000:]}")


def test_sigterm_exits_with_open_dashboard_sse(tmp_path):
    db_path = tmp_path / "orchestra.db"
    task_repository = tmp_path / "tasks"
    catalog_path = tmp_path / "projects.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    catalog_path.write_text("version: 1\nprojects: []\n", encoding="utf-8")
    port = _free_port()

    timeout_s = _graceful_timeout_from_execstart(SERVICE)
    template_timeout_s = _graceful_timeout_from_execstart(SERVICE_TEMPLATE)
    assert timeout_s == template_timeout_s and timeout_s is not None
    uvicorn_call = (
        "import sys, types; "
        "sys.modules['pytest'] = types.ModuleType('pytest'); "
        "import uvicorn; "
        "uvicorn.run('app.main:app', host='127.0.0.1', port=int(sys.argv[1]), "
        "log_level='error', access_log=False, timeout_graceful_shutdown="
        "(int(sys.argv[2]) if sys.argv[2] else None))"
    )
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "PYTHONPATH": str(ROOT),
        "PYTHONUNBUFFERED": "1",
        "ORCHESTRA_DB_PATH": str(db_path),
        "ORCHESTRA_TASK_REPOSITORY": str(task_repository),
        "ORCHESTRA_PROJECT_CATALOG": str(catalog_path),
        "ORCHESTRA_PROJECT_CATALOG_ROOT": str(tmp_path / "scopes"),
        "WORKSPACE_DIR": str(workspace),
        "SSH_TUNNELS": "",
        "GIT_AUTHOR_NAME": "V-630 test",
        "GIT_AUTHOR_EMAIL": "v630-test@example.invalid",
        "GIT_COMMITTER_NAME": "V-630 test",
        "GIT_COMMITTER_EMAIL": "v630-test@example.invalid",
    }
    output_path = tmp_path / "uvicorn.log"
    with output_path.open("w+") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", uvicorn_call, str(port), str(timeout_s or "")],
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        connection = None
        try:
            _wait_for_dashboard(port, process, output_path)

            # Lifespan created this temporary schema. A completed session is enough for
            # the production SSE route to accept a real client without resuming a backend.
            with sqlite3.connect(db_path) as db:
                db.execute(
                    "INSERT INTO sessions (id, name, scope, cwd, model, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("shutdown-test", "shutdown-test", str(workspace), str(workspace),
                     "claude-sonnet-4-6", "completed", "2026-09-24T00:00:00+00:00"),
                )

            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            connection.request(
                "GET", f"/api/sessions/shutdown-test/stream?scope={workspace}"
            )
            response = connection.getresponse()
            assert response.status == 200
            assert response.getheader("content-type", "").startswith("text/event-stream")
            assert response.read(1), "SSE response did not begin streaming"

            started = time.monotonic()
            process.send_signal(15)
            try:
                returncode = process.wait(timeout=SHUTDOWN_LIMIT_S)
            except subprocess.TimeoutExpired:
                raise AssertionError(
                    f"SIGTERM did not stop Uvicorn within {SHUTDOWN_LIMIT_S}s with SSE open; "
                    f"graceful timeout configured as {timeout_s!r}s"
                )
            elapsed = time.monotonic() - started
            assert returncode in (0, -15), output_path.read_text(errors="replace")[-3000:]
            assert elapsed < SHUTDOWN_LIMIT_S
        finally:
            if connection is not None:
                connection.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
