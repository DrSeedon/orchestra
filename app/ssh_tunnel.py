import asyncio
import logging
import os

logger = logging.getLogger("ssh-tunnel")

_proc: asyncio.subprocess.Process | None = None
_running = False
_host = ""
_local_port = 0
_remote_port = 0
_task: asyncio.Task | None = None


async def start_tunnel():
    global _host, _local_port, _remote_port, _task

    _host = os.getenv("SSH_TUNNEL_HOST", "")
    key = os.getenv("SSH_TUNNEL_KEY", "")
    _local_port = int(os.getenv("SSH_TUNNEL_LOCAL_PORT", "12338"))
    _remote_port = int(os.getenv("SSH_TUNNEL_REMOTE_PORT", "18080"))

    if not _host:
        logger.info("SSH tunnel disabled (no SSH_TUNNEL_HOST)")
        return
    if not key:
        logger.error("SSH_TUNNEL_HOST set but SSH_TUNNEL_KEY missing")
        return

    _task = asyncio.create_task(_tunnel_loop(_host, key, _local_port, _remote_port))
    logger.info(f"SSH tunnel starting: localhost:{_local_port} -> {_host}:{_remote_port}")


async def _tunnel_loop(host: str, key: str, local_port: int, remote_port: int):
    global _proc, _running
    while True:
        try:
            _proc = await asyncio.create_subprocess_exec(
                "ssh", "-N",
                "-L", f"{local_port}:127.0.0.1:{remote_port}",
                "-i", key,
                "-o", "StrictHostKeyChecking=no",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", "ExitOnForwardFailure=yes",
                f"root@{host}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _running = True
            logger.info(f"SSH tunnel connected (pid={_proc.pid})")
            _, stderr = await _proc.communicate()
            _running = False
            if stderr:
                logger.warning(f"SSH tunnel exited: {stderr.decode().strip()}")
            else:
                logger.warning("SSH tunnel exited")
        except asyncio.CancelledError:
            if _proc and _proc.returncode is None:
                _proc.terminate()
            _running = False
            return
        except Exception as e:
            _running = False
            logger.error(f"SSH tunnel error: {e}")
        logger.info("SSH tunnel reconnecting in 5s...")
        await asyncio.sleep(5)


async def stop_tunnel():
    global _proc, _running, _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    if _proc and _proc.returncode is None:
        _proc.terminate()
    _proc = None
    _running = False
    logger.info("SSH tunnel stopped")


def tunnel_status() -> dict:
    return {
        "running": _running,
        "host": _host,
        "local_port": _local_port,
        "remote_port": _remote_port,
        "pid": _proc.pid if _proc and _proc.returncode is None else None,
    }
