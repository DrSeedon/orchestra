#!/usr/bin/env python3
"""Local, non-systemd reproducer for #379's socket and uvloop invariants."""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

import uvloop


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    await receive()
    body = b"ok"
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


def _serve_fd(fd: int) -> None:
    import uvicorn

    config = uvicorn.Config(
        app,
        fd=fd,
        loop="uvloop",
        lifespan="off",
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()


def _inspect_fd(fd: int, hold_seconds: float) -> None:
    try:
        stat = os.fstat(fd)
        duplicated = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
        result = {
            "open": True,
            "inode": stat.st_ino,
            "sockname": duplicated.getsockname(),
        }
        duplicated.close()
    except OSError as error:
        result = {"open": False, "errno": error.errno}
    print(json.dumps(result), flush=True)
    if hold_seconds:
        time.sleep(hold_seconds)


def _new_listener(*, inheritable: bool = False) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2048)
    os.set_inheritable(listener.fileno(), inheritable)
    return listener


async def _inheritance_arm(loop_name: str, inheritable: bool) -> dict:
    listener = _new_listener(inheritable=inheritable)
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            __file__,
            "--inspect-fd",
            str(listener.fileno()),
            stdout=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None
        child = json.loads((await process.stdout.readline()).decode())
        await process.wait()
        return {
            "loop": loop_name,
            "inheritable": inheritable,
            "parent_fd": listener.fileno(),
            "parent_inode": os.fstat(listener.fileno()).st_ino,
            "child": child,
        }
    finally:
        listener.close()


def inheritance_matrix() -> list[dict]:
    rows = []
    for name, factory in (
        ("asyncio", asyncio.new_event_loop),
        ("uvloop", uvloop.new_event_loop),
    ):
        for inheritable in (True, False):
            rows.append(asyncio.run(
                _inheritance_arm(name, inheritable),
                loop_factory=factory,
            ))
    return rows


def _listen_recv_q(port: int) -> int | None:
    wanted = f"{port:04X}"
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        for line in table.read_text().splitlines()[1:]:
            fields = line.split()
            local_port = fields[1].rsplit(":", 1)[-1].upper()
            if local_port == wanted and fields[3] == "0A":
                _tx, rx = fields[4].split(":")
                return int(rx, 16)
    return None


def _fresh_http(port: int, timeout: float) -> tuple[str, float]:
    started = time.monotonic()
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as client:
        client.settimeout(timeout)
        client.sendall(b"GET / HTTP/1.1\r\nHost: local\r\nConnection: close\r\n\r\n")
        response = b""
        while b"\r\n" not in response:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
    return response.split(b"\r\n", 1)[0].decode(errors="replace"), time.monotonic() - started


def queued_restart_probe(pending: int = 350) -> dict:
    listener = _new_listener()
    port = listener.getsockname()[1]
    clients: list[socket.socket] = []
    server = None
    try:
        for _ in range(pending):
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2)
            client.connect(("127.0.0.1", port))
            clients.append(client)

        queue_before = _listen_recv_q(port)
        server = subprocess.Popen(
            [sys.executable, __file__, "--serve-fd", str(listener.fileno())],
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        deadline = time.monotonic() + 5
        last_error = ""
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"server exited early: {(server.stderr.read() if server.stderr else '')[-2000:]}")
            try:
                status, latency = _fresh_http(port, 1)
                break
            except OSError as error:
                last_error = f"{type(error).__name__}: {error}"
                time.sleep(0.02)
        else:
            raise RuntimeError(f"fresh HTTP never completed: {last_error}")

        return {
            "requested_pending": pending,
            "recv_q_before_new_acceptor": queue_before,
            "fresh_status": status,
            "fresh_latency_ms": round(latency * 1000, 1),
            "recv_q_after_new_acceptor": _listen_recv_q(port),
        }
    finally:
        for client in clients:
            client.close()
        if server is not None and server.poll() is None:
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        listener.close()


async def _recycle_arm(inheritable: bool) -> dict:
    listener = _new_listener(inheritable=inheritable)
    address = listener.getsockname()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        __file__,
        "--inspect-fd",
        str(listener.fileno()),
        "--hold-seconds",
        "10",
        stdout=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    child = json.loads((await process.stdout.readline()).decode())
    listener.close()

    replacement = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    replacement.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        try:
            replacement.bind(address)
            while_child_alive = "bind-ok"
        except OSError as error:
            while_child_alive = f"bind-error:{error.errno}:{errno.errorcode.get(error.errno, '?')}"
    finally:
        replacement.close()

    process.terminate()
    await process.wait()

    after = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    after.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        after.bind(address)
        after_child_exit = "bind-ok"
    except OSError as error:
        after_child_exit = f"bind-error:{error.errno}:{errno.errorcode.get(error.errno, '?')}"
    finally:
        after.close()

    return {
        "inheritable": inheritable,
        "child": child,
        "rebind_while_child_alive": while_child_alive,
        "rebind_after_child_exit": after_child_exit,
    }


def recycle_matrix() -> list[dict]:
    return [
        asyncio.run(_recycle_arm(inheritable), loop_factory=uvloop.new_event_loop)
        for inheritable in (True, False)
    ]


async def _executor_timeout_probe() -> dict:
    release = threading.Event()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, release.wait)
    timer = threading.Timer(0.5, release.set)
    timer.start()
    started = time.monotonic()
    await loop.shutdown_default_executor(0.05)
    elapsed = time.monotonic() - started
    timer.join()
    return {
        "requested_timeout_ms": 50,
        "worker_release_ms": 500,
        "observed_wait_ms": round(elapsed * 1000, 1),
        "future_done": future.done(),
    }


def executor_timeout_probe() -> dict:
    return asyncio.run(_executor_timeout_probe(), loop_factory=uvloop.new_event_loop)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect-fd", type=int)
    parser.add_argument("--hold-seconds", type=float, default=0)
    parser.add_argument("--serve-fd", type=int)
    args = parser.parse_args()
    if args.inspect_fd is not None:
        _inspect_fd(args.inspect_fd, args.hold_seconds)
        return
    if args.serve_fd is not None:
        _serve_fd(args.serve_fd)
        return

    print(json.dumps({
        "inheritance_matrix": inheritance_matrix(),
        "queued_restart": queued_restart_probe(),
        "recycle_matrix": recycle_matrix(),
        "uvloop_executor_timeout": executor_timeout_probe(),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
