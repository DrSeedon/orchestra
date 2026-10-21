"""Import Claude Code local message usage without losing history when files rotate."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from app.db import _conn

logger = logging.getLogger(__name__)


def read_history(root: Path | None = None) -> tuple[dict[str, tuple], dict]:
    root = Path.home() / ".claude" / "projects" if root is None else Path(root)
    rows: dict[str, tuple] = {}
    stats = {"files": 0, "messages": 0, "malformed_lines": 0}
    if not root.is_dir():
        return rows, stats

    for path in sorted(root.glob("*/*.jsonl")):
        stats["files"] += 1
        project_fallback = path.parent.name
        file_rows: dict[str, tuple] = {}
        try:
            with path.open(encoding="utf-8", errors="replace") as source:
                for line in source:
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        stats["malformed_lines"] += 1
                        continue
                    message = record.get("message") if isinstance(record, dict) else None
                    if not isinstance(message, dict) or record.get("type") != "assistant":
                        continue
                    usage = message.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    message_id = message.get("id") or record.get("uuid")
                    timestamp = record.get("timestamp")
                    if not isinstance(message_id, str) or not message_id or not isinstance(timestamp, str) or len(timestamp) < 10:
                        continue
                    project = record.get("cwd")
                    if not isinstance(project, str) or not project:
                        project = project_fallback
                    values = []
                    for key in (
                        "input_tokens", "output_tokens", "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    ):
                        try:
                            values.append(max(0, int(usage.get(key, 0) or 0)))
                        except (TypeError, ValueError, OverflowError):
                            values.append(0)
                    file_rows[message_id] = (
                        timestamp[:10], project, str(message.get("model") or "unknown"),
                        *values,
                    )
        except OSError as error:
            logger.warning("Claude history file unreadable: %s (%s)", path, error)
            continue
        # Preserve V-998's rule: the last record for a message id wins.
        rows.update(file_rows)

    stats["messages"] = len(rows)
    if stats["malformed_lines"]:
        logger.warning(
            "Claude history skipped %d malformed JSONL line(s) across %d file(s)",
            stats["malformed_lines"], stats["files"],
        )
    return rows, stats


def collect_history_usage(root: Path | None = None) -> dict:
    """Upsert observed messages; absent files never delete previously imported rows."""
    rows, stats = read_history(root)
    with _conn() as connection:
        connection.executemany(
            """INSERT INTO claude_history_usage_messages
               (message_id, day, project, model, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(message_id) DO UPDATE SET
                 day=excluded.day, project=excluded.project, model=excluded.model,
                 input_tokens=excluded.input_tokens,
                 output_tokens=excluded.output_tokens,
                 cache_read_tokens=excluded.cache_read_tokens,
                 cache_write_tokens=excluded.cache_write_tokens""",
            [(message_id, *value) for message_id, value in rows.items()],
        )
    stats["stored_messages"] = len(rows)
    return stats


def history_totals(rows: dict[str, tuple]) -> list[dict]:
    totals = defaultdict(lambda: [0, 0, 0, 0, 0])
    for day, project, model, input_tokens, output_tokens, cache_read, cache_write in rows.values():
        values = totals[(day, project, model)]
        values[0] += 1
        values[1] += input_tokens
        values[2] += output_tokens
        values[3] += cache_read
        values[4] += cache_write
    return [
        {"day": day, "project": project, "model": model, "message_count": v[0],
         "input_tokens": v[1], "output_tokens": v[2], "cache_read_tokens": v[3],
         "cache_write_tokens": v[4]}
        for (day, project, model), v in sorted(totals.items())
    ]
