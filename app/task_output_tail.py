"""Live tail of Claude Code shell-task output files into the in-memory broker.

Claude Code CLI runs every Bash call that lasts more than a few seconds as a task
(`TaskStartedMessage`, task_type ``local_bash``) and writes the command's stdout/stderr
straight into ``<tmp>/claude-<uid>/<cwd-slug>/<session>/tasks/<task_id>.output`` while it
runs — for foreground calls and for ``run_in_background`` alike (measured 13.10.2026, CLI
bundled with claude-agent-sdk 0.2.164: the running command's own stdout *is* that file).
The SDK does not stream that output, so this module polls the file and publishes new bytes
as ephemeral ``tool_stream`` payloads. Nothing here is written to the DB.
"""
import asyncio
import codecs
import glob
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
READ_LIMIT = 64 * 1024          # bytes published per poll at most
INITIAL_TAIL = 16 * 1024        # attaching late → start from the tail, not from byte 0
FIND_TIMEOUT = 30.0             # file never appeared → give up
MISSING_GRACE = 10.0            # file vanished (CLI deletes it after the call) → stop
MAX_LIFETIME = 6 * 3600.0
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _tmp_roots() -> list[Path]:
    roots = []
    override = os.environ.get("CLAUDE_CODE_TMPDIR")
    for base in filter(None, (override, "/tmp")):
        roots.append(Path(base) / f"claude-{os.getuid()}")
    return roots


def find_output_file(task_id: str, sdk_session_id: str = "") -> Path | None:
    if not _SAFE_ID.match(task_id or ""):
        return None
    session_part = sdk_session_id if _SAFE_ID.match(sdk_session_id or "") else "*"
    for root in _tmp_roots():
        patterns = [str(root / "*" / session_part / "tasks" / f"{task_id}.output")]
        if session_part != "*":
            patterns.append(str(root / "*" / "*" / "tasks" / f"{task_id}.output"))
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                return Path(matches[0])
    return None


async def tail_task_output(publish, task_id: str, tool_use_id: str,
                           sdk_session_id: str = "", poll: float = POLL_SECONDS) -> None:
    """Publish appended output until cancelled, the file disappears, or the lifetime cap."""
    started = time.monotonic()
    path: Path | None = None
    offset = 0
    missing_since: float | None = None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while time.monotonic() - started < MAX_LIFETIME:
        if path is None:
            path = find_output_file(task_id, sdk_session_id)
            if path is None:
                if time.monotonic() - started > FIND_TIMEOUT:
                    return
                await asyncio.sleep(poll)
                continue
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            missing_since = missing_since or time.monotonic()
            if time.monotonic() - missing_since > MISSING_GRACE:
                return
            await asyncio.sleep(poll)
            continue
        missing_since = None
        if size < offset:
            offset = 0  # truncated/rewritten
        if offset == 0 and size > INITIAL_TAIL:
            offset = size - INITIAL_TAIL
        if size > offset:
            with path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read(READ_LIMIT)
            offset += len(data)
            text = decoder.decode(data)
            if text:
                publish({"type": "tool_stream", "content": text,
                         "tool_use_id": tool_use_id, "subagent_id": task_id})
            if size > offset:
                continue  # more than READ_LIMIT pending — catch up without sleeping
        await asyncio.sleep(poll)


class TaskOutputTails:
    """Per-session owner of the tail tasks: one per running ``local_bash`` task."""

    def __init__(self, publish):
        self._publish = publish
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, task_id: str, tool_use_id: str, sdk_session_id: str = "") -> None:
        if not task_id or task_id in self._tasks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(
            tail_task_output(self._publish, task_id, tool_use_id, sdk_session_id))
        self._tasks[task_id] = task
        task.add_done_callback(lambda done, tid=task_id: self._forget(tid, done))

    def _forget(self, task_id: str, task: asyncio.Task) -> None:
        if self._tasks.get(task_id) is task:
            del self._tasks[task_id]
        if not task.cancelled() and task.exception() is not None:
            logger.warning("task output tail %s failed: %r", task_id, task.exception())

    def stop(self, task_id: str) -> None:
        task = self._tasks.pop(task_id, None)
        if task:
            task.cancel()

    def stop_all(self) -> None:
        for task_id in list(self._tasks):
            self.stop(task_id)

    def active(self) -> set[str]:
        return set(self._tasks)
