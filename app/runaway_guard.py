r"""Сторож одного прожорливого процесса в дереве Orchestra.

Зачем отдельный механизм при живом `MemoryHigh=8G` на юните: cgroup-лимит
наказывает ВСЁ дерево. 04.09.2026 `awk`, написанный Luna в ходе `codex_review`
(вложенный квантификатор `([^|]*\|){8}` на файле в 21 КБ), вырос до 7.9 ГБ —
cgroup упёрся в `MemoryHigh`, начал реклейм, и в своп уехали Orchestra, все
агентские CLI и TG-мост разом: iowait 68.7%, load 26 на 12 ядрах, свободной
памяти 280 МБ. Виновник при этом продолжал работать.

Почему не `RLIMIT_AS` на агентских CLI: они резервируют адресное пространство
десятками гигабайт при копеечном RSS (замер: `claude` VmPeak 9.27 ГиБ против
VmRSS 220 МБ), поэтому любой осмысленный потолок убил бы сам агент, а не его
выродившегося внука.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

logger = logging.getLogger("orchestra.runaway_guard")

INTERVAL_SECONDS = int(os.getenv("RUNAWAY_GUARD_INTERVAL", "20"))
LIMIT_BYTES = int(os.getenv("RUNAWAY_GUARD_LIMIT_MB", "2048")) * 1024 * 1024
STRIKES_TO_KILL = 2
ENABLED = os.getenv("RUNAWAY_GUARD_ENABLED", "1").strip().lower() in ("1", "true", "yes")
_CGROUP = "/sys/fs/cgroup/system.slice/orchestra.service/cgroup.procs"

# pid → сколько замеров подряд процесс превышает потолок
_STRIKES: dict[int, int] = {}


def _cgroup_pids() -> list[int]:
    """Точный список дерева от ядра. `ps` пришлось бы фильтровать по родителю."""
    try:
        with open(_CGROUP, encoding="ascii") as handle:
            return [int(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        return []


def _rss_bytes(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return handle.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _kill(pid: int) -> None:
    """SIGKILL сразу: процесс, съевший гигабайты, уже в `D` и на TERM не отвечает."""
    try:
        os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError) as error:
        logger.warning(f"runaway guard could not kill {pid}: {error}")


def _report(pid: int, rss: int, cmd: str) -> None:
    logger.error(
        f"runaway process killed: pid={pid} rss={rss / 1073741824:.2f}GiB "
        f"cmd={cmd[:400]}"
    )


def sweep_once(*, limit_bytes: int, self_pid: int) -> list[int]:
    """Один проход. Возвращает убитые pid."""
    killed: list[int] = []
    alive = set()
    for pid in _cgroup_pids():
        alive.add(pid)
        # Собственный процесс не трогаем никогда: его смерть — это отказ платформы,
        # а не лечение. Жирная Orchestra — повод для рестарта, но не для SIGKILL.
        if pid == self_pid:
            continue
        rss = _rss_bytes(pid)
        if rss < limit_bytes:
            _STRIKES.pop(pid, None)
            continue
        strikes = _STRIKES.get(pid, 0) + 1
        _STRIKES[pid] = strikes
        if strikes < STRIKES_TO_KILL:
            continue
        cmd = _cmdline(pid)
        _report(pid, rss, cmd)
        _kill(pid)
        _STRIKES.pop(pid, None)
        killed.append(pid)
    for gone in [pid for pid in _STRIKES if pid not in alive]:
        _STRIKES.pop(gone, None)
    return killed


async def run_loop() -> None:
    if not ENABLED:
        logger.info("runaway guard disabled (RUNAWAY_GUARD_ENABLED=0)")
        return
    self_pid = os.getpid()
    logger.info(
        f"runaway guard armed: limit={LIMIT_BYTES / 1073741824:.1f}GiB "
        f"interval={INTERVAL_SECONDS}s strikes={STRIKES_TO_KILL}"
    )
    while True:
        try:
            sweep_once(limit_bytes=LIMIT_BYTES, self_pid=self_pid)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(f"runaway guard sweep failed: {error}")
        await asyncio.sleep(INTERVAL_SECONDS)


def ensure_task(app) -> asyncio.Task:
    current = getattr(app.state, "runaway_guard_task", None)
    if current is not None and not current.done():
        return current
    task = asyncio.create_task(run_loop(), name="runaway-guard")
    app.state.runaway_guard_task = task
    return task
