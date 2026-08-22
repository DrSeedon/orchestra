"""JSONL session store — append-only history, resumable, crash-tolerant.

The JSONL file is the source of truth for resume. Each line is one OpenAI-format
message dict (role/content/tool_calls/tool_call_id) plus optional meta entries.
A partial trailing line (crash mid-write) is skipped on load, never fatal.
"""

import asyncio
import json
import os
import uuid
from pathlib import Path


class SessionStore:
    """One JSONL file per session. Append-only, fsync on close, tolerant load.

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
        line = json.dumps(entry, ensure_ascii=False)
        async with self._lock:
            self._ensure_open()
            fh = self._fh
            assert fh is not None
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    async def append_messages(self, messages: list[dict]) -> None:
        for m in messages:
            await self.append(m)

    def load(self) -> list[dict]:
        """Read JSONL → list of message dicts. A broken trailing line is skipped
        (crash tolerance); other malformed lines are skipped with no fatal error.
        Only OpenAI-message-shaped entries (have a 'role') are returned."""
        if not self._path.exists():
            return []
        out: list[dict] = []
        with open(self._path, encoding="utf-8") as f:
            lines = f.readlines()
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except (ValueError, TypeError):
                # malformed (likely a partial trailing line from a crash) — skip
                continue
            if isinstance(obj, dict) and obj.get("role") in ("user", "assistant", "tool", "system"):
                out.append(obj)
        return out

    async def close(self) -> None:
        async with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                    os.fsync(self._fh.fileno())
                finally:
                    self._fh.close()
                    self._fh = None
