"""JSONL session store — resumable, crash-tolerant history.

The JSONL file is the source of truth for resume. Each line is one OpenAI-format
message dict (role/content/tool_calls/tool_call_id) plus optional meta entries.
A partial trailing line (crash mid-write) is skipped on load, never fatal, and is cut
off on disk so the next append starts on a clean line.
"""

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path


class SessionStore:
    """One JSONL file per session. Batched append, atomic compact snapshot, tolerant load.

    Concurrency: a single asyncio.Lock guards append/flush so overlapping
    disconnect/interrupt/turn-persistence cannot interleave a partial line.
    """

    def __init__(self, session_dir: str, session_id: str | None = None):
        self._dir = Path(session_dir)
        self.session_id = session_id or self.new_session_id()
        self._path = self._dir / f"{self.session_id}.jsonl"
        self._lock = asyncio.Lock()
        self._fh = None

    @staticmethod
    def new_session_id() -> str:
        # uuid4 — no Date.now()/clock dependency for determinism in tests.
        return uuid.uuid4().hex

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_open(self) -> None:
        if self._fh is None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8")

    async def append(self, entry: dict) -> None:
        """Append one JSON entry as a single LF-terminated line, flushed to disk."""
        await self.append_messages([entry])

    async def append_messages(self, messages: list[dict]) -> None:
        """Append a batch with one flush/fsync instead of one disk barrier per message."""
        if not messages:
            return
        lines = [json.dumps(message, ensure_ascii=False) + "\n" for message in messages]
        async with self._lock:
            self._ensure_open()
            fh = self._fh
            assert fh is not None
            fh.writelines(lines)
            fh.flush()
            os.fsync(fh.fileno())

    async def replace_messages(self, messages: list[dict]) -> None:
        """Atomically replace the JSONL snapshot after context compaction.

        Append-only persistence would resurrect discarded history on the next process
        start. The temp file lives beside the target so os.replace stays atomic.
        """
        async with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            if self._fh is not None:
                self._fh.flush()
                os.fsync(self._fh.fileno())
                self._fh.close()
                self._fh = None

            tmp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self._dir,
                    prefix=f".{self.session_id}.", suffix=".tmp", delete=False,
                ) as tmp:
                    tmp_path = tmp.name
                    for message in messages:
                        tmp.write(json.dumps(message, ensure_ascii=False) + "\n")
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_path, self._path)
                tmp_path = None
                dir_fd = os.open(self._dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            finally:
                if tmp_path is not None:
                    try:
                        os.unlink(tmp_path)
                    except FileNotFoundError:
                        pass

    def load(self) -> list[dict]:
        """Read JSONL → messages; tolerate only a crash-truncated final record.

        Corruption in the middle means later history cannot be trusted and is loud.
        Only OpenAI-message-shaped entries (have a supported role) are returned.
        """
        if not self._path.exists():
            return []
        out: list[dict] = []
        data = self._path.read_bytes()
        lines = data.splitlines(keepends=True)
        nonempty = [i for i, line in enumerate(lines) if line.strip()]
        last_nonempty = nonempty[-1] if nonempty else -1
        offset = 0
        repair_at: int | None = None
        for index, raw in enumerate(lines):
            start, offset = offset, offset + len(raw)
            ln = raw.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln.decode("utf-8"))
            except (ValueError, TypeError) as exc:
                if index == last_nonempty:
                    # Crash mid-write. Cut the torn record off the DISK too: the next
                    # append would otherwise glue its JSON to it, and the following load
                    # would find that glued line in the middle and refuse the whole file.
                    repair_at = start
                    continue
                raise RuntimeError(
                    f"corrupt harness session {self.session_id}: invalid JSONL line {index + 1}"
                ) from exc
            if isinstance(obj, dict) and obj.get("role") in ("user", "assistant", "tool", "system"):
                out.append(obj)
        if repair_at is not None:
            self._repair_tail(truncate_to=repair_at)
        elif data and not data.endswith(b"\n"):
            # A complete last record without its LF: terminate it before anything is appended.
            self._repair_tail(terminate=True)
        return out

    def _repair_tail(self, *, truncate_to: int | None = None, terminate: bool = False) -> None:
        with open(self._path, "r+b") as f:
            if truncate_to is not None:
                f.truncate(truncate_to)
                f.seek(0, os.SEEK_END)
                if truncate_to and not self._ends_with_lf(f):
                    f.write(b"\n")
            elif terminate:
                f.seek(0, os.SEEK_END)
                f.write(b"\n")
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def _ends_with_lf(f) -> bool:
        end = f.tell()
        if end == 0:
            return True
        f.seek(end - 1)
        last = f.read(1)
        f.seek(0, os.SEEK_END)
        return last == b"\n"

    async def close(self) -> None:
        async with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                    os.fsync(self._fh.fileno())
                finally:
                    self._fh.close()
                    self._fh = None
