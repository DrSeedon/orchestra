"""#379 T2 — activation listener CLOEXEC and queued-listener handoff."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys


_HARNESS = r'''
import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import uvloop


source_fd = int(sys.argv[1])
node = sys.argv[2]
if source_fd != 3:
    os.dup2(source_fd, 3, inheritable=True)
    os.close(source_fd)

# Three real systemd-shaped entries: listener plus both sides Orchestra retains for one
# adopted agent. Move temporary pipe ends high before occupying canonical LISTEN_FDS slots.
agent_sources = []
agent_peers = []
for _ in range(2):
    read_end, write_end = os.pipe()
    source = fcntl.fcntl(read_end, fcntl.F_DUPFD_CLOEXEC, 20)
    peer = fcntl.fcntl(write_end, fcntl.F_DUPFD_CLOEXEC, 20)
    os.close(read_end)
    os.close(write_end)
    agent_sources.append(source)
    agent_peers.append(peer)
for target_fd, source in zip((4, 5), agent_sources):
    os.dup2(source, target_fd, inheritable=True)
    os.close(source)
for fd in (3, 4, 5):
    os.set_inheritable(fd, True)
os.environ["LISTEN_PID"] = str(os.getpid())
os.environ["LISTEN_FDS"] = "3"
os.environ["LISTEN_FDNAMES"] = (
    "orchestra.socket:agent.alpha.stdin:agent.alpha.stdout"
)

listener = socket.fromfd(3, socket.AF_INET, socket.SOCK_STREAM)
address = listener.getsockname()
listener.close()
listener_inode = os.fstat(3).st_ino
expected_mapping = {
    "orchestra.socket": 3,
    "agent.alpha.stdin": 4,
    "agent.alpha.stdout": 5,
}
activation_targets = {
    name: os.readlink(f"/proc/self/fd/{fd}")
    for name, fd in expected_mapping.items()
}

# Production delivery seam: importing app.main must seal LISTEN_FDS before lifespan can
# auto-resume a Codex backend or start any MCP/TG child.
import app.main  # noqa: F401,E402
from app import fdstore  # noqa: E402


def owns(pid, targets):
    found = []
    for fd in (Path("/proc") / str(pid) / "fd").iterdir():
        try:
            target = os.readlink(fd)
            if target in targets:
                found.append([int(fd.name), target])
        except OSError:
            pass
    return found


def recv_q():
    wanted = f"{address[1]:04X}"
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        for line in table.read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1].rsplit(":", 1)[-1].upper() == wanted and fields[3] == "0A":
                return int(fields[4].split(":")[1], 16)
    return None


server_code = r"""
import uvicorn

async def app(scope, receive, send):
    if scope['type'] != 'http':
        return
    await receive()
    await send({'type': 'http.response.start', 'status': 200,
                'headers': [(b'content-length', b'2')]})
    await send({'type': 'http.response.body', 'body': b'ok'})

uvicorn.run(app, fd=3, loop='uvloop', lifespan='off', log_level='warning', access_log=False)
"""

holder = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(10)"],
    pass_fds=(3,),
)
clients = []
server = None
try:
    holder_fds = owns(holder.pid, {activation_targets["orchestra.socket"]})
    for _ in range(350):
        client = socket.create_connection(address, timeout=2)
        clients.append(client)
    queue_before = recv_q()

    server = subprocess.Popen(
        [sys.executable, "-c", server_code],
        pass_fds=(3,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    status = ""
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(address, timeout=1) as client:
                client.sendall(b"GET / HTTP/1.1\r\nHost: local\r\nConnection: close\r\n\r\n")
                status = client.recv(4096).split(b"\r\n", 1)[0].decode()
            break
        except OSError:
            time.sleep(0.02)
    queue_after = recv_q()

    async def child_census():
        node_proc = await asyncio.create_subprocess_exec(
            node, "-e", "setTimeout(() => {}, 1000)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        mcp_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(1)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.05)
        result = {
            "node": owns(node_proc.pid, set(activation_targets.values())),
            "mcp_python": owns(mcp_proc.pid, set(activation_targets.values())),
        }
        for proc in (node_proc, mcp_proc):
            proc.terminate()
            await proc.wait()
        return result

    unexpected = asyncio.run(child_census(), loop_factory=uvloop.new_event_loop)
    print(json.dumps({
        "activation_targets_before": activation_targets,
        "activation_fds": {
            name: {
                "fd": fd,
                "inheritable": os.get_inheritable(fd),
                "target": os.readlink(f"/proc/self/fd/{fd}"),
            }
            for name, fd in expected_mapping.items()
        },
        "acquired_mapping": fdstore.acquire_fds(),
        "listener_still_open": os.fstat(3).st_ino == listener_inode,
        "explicit_holder_fds": holder_fds,
        "queue_before": queue_before,
        "fresh_status": status,
        "queue_after": queue_after,
        "unexpected_child_owners": unexpected,
    }), flush=True)
finally:
    for client in clients:
        client.close()
    if server is not None and server.poll() is None:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=2)
    holder.terminate()
    holder.wait(timeout=2)
    for fd in agent_peers:
        os.close(fd)
'''


def test_t2_cloexec_census_and_queued_listener_with_explicit_legacy_holder():
    node = shutil.which("node")
    assert node, "production Node launcher is required for the real child census"

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2048)
    os.set_inheritable(listener.fileno(), True)
    try:
        run = subprocess.run(
            [sys.executable, "-c", _HARNESS, str(listener.fileno()), node],
            pass_fds=(listener.fileno(),),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    finally:
        listener.close()

    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.strip().splitlines()[-1])

    assert result["explicit_holder_fds"], "combined arm did not create a real leaked duplicate"
    assert result["queue_before"] == 350
    assert result["fresh_status"] == "HTTP/1.1 200 OK"
    assert result["queue_after"] == 0
    assert result["listener_still_open"] is True, "CLOEXEC must not close the acceptor's FD"
    assert result["acquired_mapping"] == {
        "orchestra.socket": 3,
        "agent.alpha.stdin": 4,
        "agent.alpha.stdout": 5,
    }
    assert all(
        row["inheritable"] is False
        for row in result["activation_fds"].values()
    ), f"systemd LISTEN_FDS remained inheritable: {result['activation_fds']}"
    assert all(
        row["target"]
        for row in result["activation_fds"].values()
    ), "CLOEXEC must preserve every listener/agent descriptor"
    assert {
        name: row["target"]
        for name, row in result["activation_fds"].items()
    } == result["activation_targets_before"], (
        "seal closed or replaced a listener/agent descriptor instead of setting CLOEXEC"
    )
    assert result["unexpected_child_owners"] == {"node": [], "mcp_python": []}, (
        "listener inode leaked outside the acceptor/explicit holder: "
        f"{result['unexpected_child_owners']}"
    )


def test_t2_seal_call_precedes_manager_import_mechanically():
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    tree = ast.parse(source)
    fdstore_imports = [
        index for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.ImportFrom)
        and statement.module == "app"
        and any(alias.name == "fdstore" and alias.asname == "_fdstore" for alias in statement.names)
    ]
    seal_calls = [
        index for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == "_fdstore"
        and statement.value.func.attr == "seal_activation_fds"
    ]
    manager_imports = [
        index for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.ImportFrom)
        and statement.module == "app.deps"
        and any(alias.name == "manager" for alias in statement.names)
    ]

    assert len(fdstore_imports) == 1, "app.main must import app.fdstore as _fdstore exactly once"
    assert len(seal_calls) == 1, "app.main must execute one real top-level CLOEXEC seal call"
    assert len(manager_imports) == 1, "app.main manager import seam changed unexpectedly"
    assert fdstore_imports[0] < seal_calls[0] < manager_imports[0], (
        "activation descriptors are sealed only after manager import-time spawn becomes possible"
    )
