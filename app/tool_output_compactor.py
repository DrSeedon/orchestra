"""Deterministic first-delivery previews and process-local, expiring raw archives.

Errors and the final summary outrank the preview budget. The archive contains the
original text, never the filtered preview. No persisted conversation is rewritten.
"""

from __future__ import annotations

import io
import hashlib
import json
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Iterable, TextIO

DEFAULT_PREVIEW_CHARS = 12_000
MAX_PAGE_CHARS = 30_000
_IMPORTANT = re.compile(r"error|fail(?:ed|ure)?|traceback|exception|exit[_ ]?code", re.I)


@dataclass(frozen=True)
class CompactPreview:
    preview: str
    total_chars: int
    omitted_chars: int


def compact_lines(lines: Iterable[str], budget: int = DEFAULT_PREVIEW_CHARS) -> CompactPreview:
    """Stream RTK runs plus head/error/tail selection with bounded ordinary text.

    Exact repeated non-error lines are folded. Diff headers, grep paths and build
    summaries survive in the head/tail; every error line and traceback survives,
    even when this makes the preview exceed its soft budget.
    """
    budget = max(32, budget)
    edge = budget // 3
    head: dict[int, tuple[str, int]] = {}
    head_raw_sizes: dict[int, int] = {}
    tail: deque[tuple[int, str, int]] = deque()
    important: dict[int, tuple[str, int]] = {}
    short: list[str] = []
    total = tail_chars = head_chars = seq = 0
    previous = None
    repeated = 0
    traceback = False

    def retain(text: str, raw_chars: int, critical: bool = False) -> None:
        nonlocal seq, tail_chars, head_chars
        seq += 1
        if head_chars < edge:
            part = text[:edge - head_chars]
            head[seq] = (part, min(raw_chars, len(part)))
            head_raw_sizes[seq] = raw_chars
            head_chars += len(part)
        if critical:
            important[seq] = (text, raw_chars)
        # A single huge ordinary line must not make the preview unbounded.
        suffix = text[-edge:]
        tail.append((seq, suffix, min(raw_chars, len(suffix))))
        tail_chars += len(suffix)
        while len(tail) > 1 and tail_chars > edge:
            _, old, _ = tail.popleft()
            tail_chars -= len(old)

    for line in lines:
        total += len(line)
        if total <= budget:
            short.append(line)
        else:
            short.clear()
        critical = bool(_IMPORTANT.search(line))
        if "Traceback (most recent call last)" in line:
            traceback = True
        in_traceback = traceback
        if traceback and line.strip() and not line[0].isspace() and "Traceback" not in line:
            traceback = False
        if line == previous and not critical and not in_traceback:
            repeated += 1
            continue
        if repeated:
            retain(f"... [repeated {repeated} times]\n", 0)
            repeated = 0
        retain(line, len(line), critical or in_traceback)
        previous = line
    if repeated:
        retain(f"... [repeated {repeated} times]\n", 0)
    # Preserve every byte of short output, including trailing newlines, for API compatibility.
    if total <= budget:
        text = ''.join(short)
        return CompactPreview(text, total, 0)
    selected = dict(head)
    for n, text, size in tail:
        # A line selected as both a clipped head and tail must retain both edges.
        if n in selected and head_raw_sizes[n] > selected[n][1]:
            prefix, prefix_size = selected[n]
            raw_size = head_raw_sizes[n]
            if raw_size > prefix_size + size:
                selected[n] = (prefix + '\n... (truncated line) ...\n' + text, prefix_size + size)
            else:
                selected[n] = (prefix + text[prefix_size + size - raw_size:], raw_size)
        elif n not in selected:
            selected[n] = (text, size)
    selected.update(important)
    preview = []
    last = 0
    for n, (text, _) in sorted(selected.items()):
        if n > last + 1:
            preview.append('\n... (truncated) ...\n')
        preview.append(text)
        last = n
    retained = sum(size for _, size in selected.values())
    return CompactPreview(''.join(preview), total, max(0, total - retained))


def compact_text(text: str, budget: int = DEFAULT_PREVIEW_CHARS) -> CompactPreview:
    return compact_lines(io.StringIO(text), budget)


def tool_result_preview(text: str) -> str:
    """Expose the original status header to existing tool-error classifiers."""
    if not text.startswith('{'):
        return text
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text
    if (isinstance(value, dict) and value.get('result_id') and value.get('complete') is False
            and isinstance(value.get('preview'), str)):
        return value['preview']
    return text


@dataclass
class _ArchivedResult:
    owner: str
    stream: TextIO
    total_chars: int
    created_at: float
    cursor: int = 0


class ToolResultStore:
    """Bounded number of disk-backed archives; opaque IDs and workspace/session scope.

    Expiry/restart is explicit on read. Never imply that an evicted result is empty.
    Text cursors count Unicode characters, not UTF-8 bytes or text seek cookies.
    """

    def __init__(self, max_results: int = 64, ttl_seconds: float = 1800):
        self.max_results = max_results
        self.ttl_seconds = ttl_seconds
        self._results: OrderedDict[str, _ArchivedResult] = OrderedDict()
        self._lock = threading.RLock()
        self._id_salt = uuid.uuid4().bytes

    def _expire(self) -> None:
        now = time.monotonic()
        for key, value in list(self._results.items()):
            if now - value.created_at >= self.ttl_seconds:
                self._results.pop(key).stream.close()
        while len(self._results) > self.max_results:
            _, old = self._results.popitem(last=False)
            old.stream.close()

    def present(self, text: str, *, owner: str, budget: int = DEFAULT_PREVIEW_CHARS,
                reader_tool: str = "read_tool_result_page") -> str:
        return self.present_stream(io.StringIO(text), owner=owner, budget=budget, reader_tool=reader_tool)

    def present_stream(self, source: TextIO, *, owner: str,
                       budget: int = DEFAULT_PREVIEW_CHARS,
                       reader_tool: str = "read_tool_result_page") -> str:
        archive = tempfile.SpooledTemporaryFile(max_size=256_000, mode='w+t',
                                               encoding='utf-8', newline='')
        digest = hashlib.sha256(self._id_salt + owner.encode('utf-8') + b'\0')

        def tee():
            for line in source:
                digest.update(line.encode('utf-8'))
                archive.write(line)
                yield line

        try:
            result = compact_lines(tee(), budget)
            if result.omitted_chars == 0:
                archive.close()
                return result.preview
            # Stable for exact repeats in this store, opaque across restarts/owners.
            # This also preserves the existing repeat-result loop guard.
            result_id = digest.hexdigest()[:32]
            archive.seek(0)
            with self._lock:
                previous = self._results.pop(result_id, None)
                if previous:
                    previous.stream.close()
                self._results[result_id] = _ArchivedResult(owner, archive, result.total_chars, time.monotonic())
                self._expire()
            envelope = {
                "preview": result.preview, "result_id": result_id,
                "total_chars": result.total_chars, "omitted_chars": result.omitted_chars,
                "complete": False, "next_cursor": 0,
            }
            if budget >= 512:
                envelope.update(read_with=f"{reader_tool}(result_id, cursor=0, limit=12000)",
                                archive_ttl_seconds=self.ttl_seconds)
            elif reader_tool != "read_tool_result_page":
                envelope["read_with"] = reader_tool
            return json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))
        except BaseException:
            archive.close()
            raise

    def read(self, result_id: str, *, owner: str, cursor: int = 0,
             limit: int = DEFAULT_PREVIEW_CHARS) -> dict:
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError('cursor must be a nonnegative character offset')
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError('limit must be a positive character count')
        limit = min(limit, MAX_PAGE_CHARS)
        with self._lock:
            self._expire()
            entry = self._results.get(result_id)
            if entry is None or entry.owner != owner:
                raise ValueError('tool result unavailable: unknown, expired, or outside caller scope')
            if cursor > entry.total_chars:
                raise ValueError('cursor is beyond the end of the result')
            if cursor < entry.cursor:
                entry.stream.seek(0)
                entry.cursor = 0
            remaining = cursor - entry.cursor
            while remaining:
                skipped = entry.stream.read(min(remaining, 65536))
                remaining -= len(skipped)
            text = entry.stream.read(limit)
            end = cursor + len(text)
            entry.cursor = end
            return {"result_id": result_id, "text": text, "cursor": cursor,
                    "total_chars": entry.total_chars, "omitted_chars": entry.total_chars - len(text),
                    "complete": end == entry.total_chars,
                    "next_cursor": end if end < entry.total_chars else None}

    def close(self) -> None:
        with self._lock:
            for entry in self._results.values():
                entry.stream.close()
            self._results.clear()


TOOL_RESULTS = ToolResultStore()
