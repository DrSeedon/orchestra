#!/usr/bin/env python3
"""Run the laptop's OAuth-authenticated agy through a session-owned SSH SOCKS.

Authorized by Maxim on 2026-11-05; see contabo.md for the measured canary.
No credentials are read or copied. This does not change T3 provider settings.
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


HOME_DIR = Path.home()
AGY = HOME_DIR / ".local/share/antigravity-contabo/agy-real"
STATUS = HOME_DIR / f".cache/antigravity/contabo-sessions/{os.getpid()}.json"
SERVER = "kesha@158.220.127.161"
SESSION: dict[str, object] = {}


def save_status(state: str, **values: object) -> None:
    SESSION.update(values)
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_name(f".{STATUS.name}.{os.getpid()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({**SESSION, "state": state, "updated": time.time(), "pid": os.getpid()}, stream)
    os.replace(temporary, STATUS)


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def stop_on_parent_death() -> None:
    # Linux PR_SET_PDEATHSIG: the SSH listener also closes if this wrapper dies.
    if ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() == 1:
        os._exit(125)


def handle_signal(number: int, _frame: object) -> None:
    raise SystemExit(128 + number)


def main() -> int:
    os.nice(15)
    try:
        Path("/proc/self/oom_score_adj").write_text("1000")
    except OSError:
        pass
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, handle_signal)

    tunnel = None
    client = None
    result = 1
    try:
        if not AGY.is_file():
            print(f"Antigravity CLI не найден: {AGY}", file=sys.stderr)
            return 1
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        tunnel = subprocess.Popen(
            [
                "ssh", "-N", "-T", "-D", f"127.0.0.1:{port}",
                "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=8",
                "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=2",
                SERVER,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=stop_on_parent_death,
        )
        deadline = time.monotonic() + 12
        while True:
            if tunnel.poll() is not None:
                print("Не удалось открыть SSH-туннель Contabo. Проверь доступ по SSH.", file=sys.stderr)
                return 1
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    print("Истекло время открытия SSH-туннеля Contabo.", file=sys.stderr)
                    return 1
                time.sleep(0.1)

        env = os.environ.copy()
        for key in (
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_GENAI_USE_VERTEXAI",
        ):
            env.pop(key, None)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env[key] = f"socks5://127.0.0.1:{port}"
        env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
        print("Antigravity · Contabo: SSH-туннель открыт.", file=sys.stderr, flush=True)
        client = subprocess.Popen([str(AGY), *sys.argv[1:]], env=env)
        save_status("running", tunnel_pid=tunnel.pid, client_pid=client.pid, proxy_port=port)
        while True:
            try:
                result = client.wait(timeout=1)
                return result
            except subprocess.TimeoutExpired:
                if tunnel.poll() is not None:
                    print("SSH-туннель Contabo закрылся. Antigravity остановлен.", file=sys.stderr)
                    return 1
    except KeyboardInterrupt:
        result = 130
        return result
    except OSError as error:
        print(f"Не удалось запустить Antigravity через Contabo: {error}", file=sys.stderr)
        return 1
    finally:
        for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(number, signal.SIG_IGN)
        stop(client)
        stop(tunnel)
        save_status("closed", exit_code=result)


if __name__ == "__main__":
    sys.exit(main())
