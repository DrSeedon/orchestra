"""SSH tunnel manager — multiple tunnels with auto-restart.

Config via SSH_TUNNELS env var (pipe-separated fields, comma-separated entries):
  SSH_TUNNELS=name|local_port|host|remote_port|key_path,...

Example:
  SSH_TUNNELS=ezhik|12340|194.87.250.243|18080|/path/to/key,timeweb|12341|147.45.101.84|3128|
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("ssh-tunnel")

RECONNECT_DELAY = 5
KILL_GRACE = 3  # seconds to wait after terminate() before SIGKILL
DEFAULT_KEY = os.path.expanduser("~/.ssh/id_ed25519")


@dataclass
class Tunnel:
    name: str
    local_port: int
    host: str
    remote_port: int
    key_path: str
    proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    task: asyncio.Task | None = field(default=None, repr=False)
    running: bool = False


_tunnels: list[Tunnel] = []


async def _kill_stale(t: Tunnel):
    """Kill orphan ssh forwards for THIS tunnel left by prior runs / network changes.

    WHY: on network switch or non-graceful restart the old `ssh -N -L` process
    lingers holding the port in a half-dead state → new tunnel can't bind →
    proxy silently returns HTTP 000. Match pins the FULL forward spec
    ({local}:127.0.0.1:{remote}) + host so it only kills our own tunnel def —
    never a same-local-port forward owned by something else, and 12340 never
    matches 123400.
    """
    pattern = f"ssh -N -L {t.local_port}:127.0.0.1:{t.remote_port} .*root@{t.host}"
    try:
        proc = await asyncio.create_subprocess_exec(
            "pkill", "-f", pattern,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0:
            logger.info(f"killed stale ssh on :{t.local_port} ({t.name})")
    except Exception as e:
        logger.warning(f"stale cleanup failed for :{t.local_port}: {e}")


def _parse_tunnels() -> list[Tunnel]:
    raw = os.getenv("SSH_TUNNELS", "")
    if not raw:
        return _parse_legacy()
    tunnels = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|")
        if len(parts) < 4:
            logger.warning(f"SSH tunnel config invalid (need 4+ fields): {entry}")
            continue
        name = parts[0].strip()
        local_port = int(parts[1].strip())
        host = parts[2].strip()
        remote_port = int(parts[3].strip())
        key = parts[4].strip() if len(parts) > 4 and parts[4].strip() else DEFAULT_KEY
        tunnels.append(Tunnel(name=name, local_port=local_port, host=host,
                              remote_port=remote_port, key_path=key))
    return tunnels


def _parse_legacy() -> list[Tunnel]:
    host = os.getenv("SSH_TUNNEL_HOST", "")
    if not host:
        return []
    key = os.getenv("SSH_TUNNEL_KEY", DEFAULT_KEY)
    local = int(os.getenv("SSH_TUNNEL_LOCAL_PORT", "12338"))
    remote = int(os.getenv("SSH_TUNNEL_REMOTE_PORT", "18080"))
    return [Tunnel(name="legacy", local_port=local, host=host,
                   remote_port=remote, key_path=key)]


async def _tunnel_loop(t: Tunnel):
    while True:
        try:
            t.proc = await asyncio.create_subprocess_exec(
                "ssh", "-N",
                "-L", f"{t.local_port}:127.0.0.1:{t.remote_port}",
                "-i", t.key_path,
                "-o", "StrictHostKeyChecking=no",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", "ExitOnForwardFailure=yes",
                f"root@{t.host}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            t.running = True
            logger.info(f"tunnel {t.name} started pid={t.proc.pid} "
                        f"(:{t.local_port} → {t.host}:{t.remote_port})")
            _, stderr = await t.proc.communicate()
            t.running = False
            msg = stderr.decode().strip() if stderr else ""
            logger.warning(f"tunnel {t.name} died pid={t.proc.pid}"
                           f"{': ' + msg if msg else ''}")
        except asyncio.CancelledError:
            if t.proc and t.proc.returncode is None:
                t.proc.terminate()
                try:
                    await asyncio.wait_for(t.proc.wait(), timeout=KILL_GRACE)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    t.proc.kill()
            t.running = False
            return
        except Exception as e:
            t.running = False
            logger.error(f"tunnel {t.name} error: {e}")
        logger.info(f"tunnel {t.name} reconnecting in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


async def start_tunnel():
    global _tunnels
    _tunnels = _parse_tunnels()
    if not _tunnels:
        logger.info("SSH tunnels: none configured")
        return
    await asyncio.gather(*(_kill_stale(t) for t in _tunnels))
    for t in _tunnels:
        t.task = asyncio.create_task(_tunnel_loop(t))
    names = ", ".join(f"{t.name}(:{t.local_port})" for t in _tunnels)
    logger.info(f"SSH tunnels starting: {names}")


async def stop_tunnel():
    for t in _tunnels:
        if t.task:
            t.task.cancel()
            try:
                await t.task
            except asyncio.CancelledError:
                pass
            t.task = None
        if t.proc and t.proc.returncode is None:
            t.proc.terminate()
            try:
                await asyncio.wait_for(t.proc.wait(), timeout=KILL_GRACE)
            except asyncio.TimeoutError:
                # terminate() ignored (ssh hung on dead route) → force SIGKILL
                logger.warning(f"tunnel {t.name} pid={t.proc.pid} ignored SIGTERM, SIGKILL")
                t.proc.kill()
        t.proc = None
        t.running = False
    logger.info(f"SSH tunnels stopped ({len(_tunnels)})")


def tunnel_status() -> list[dict]:
    return [
        {
            "name": t.name,
            "running": t.running,
            "host": t.host,
            "local_port": t.local_port,
            "remote_port": t.remote_port,
            "pid": t.proc.pid if t.proc and t.proc.returncode is None else None,
        }
        for t in _tunnels
    ]
