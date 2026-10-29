"""Progress samples for long background `run` jobs (V-1135).

Pure logic, no I/O: a sampler (the job's own output or a bounded read-only command)
produces one JSON object; `ingest` validates it and folds it into the durable record kept
at `bg_jobs.config._progress`. Nothing here ever invents a number: a missing total gives
no percent, too few observations give no ETA, and a rewind resets the history.

Sample protocol (one JSON object, or a line `ORCHESTRA_PROGRESS {json}`):
    status      running | paused | waiting | done | error      (default running)
    label       short human text, <= 120 chars
    completed   finite number >= 0
    total       finite number > 0
    unit        short text, e.g. "MB", "files", "%"
    percent     0..100, used only when completed/total are absent
    rate        finite number >= 0, units per second
    eta_seconds finite number >= 0 (approximate; reported by the source)
"""

import json
import math
import time
from datetime import datetime, timezone

MIN_INTERVAL = 5
DEFAULT_INTERVAL = 5
MAX_INTERVAL = 3600
SAMPLER_TIMEOUT = 10
SAMPLER_READ_LIMIT = 65536
MAX_COMMAND_CHARS = 2000
MAX_LABEL = 120
MAX_UNIT = 16
MAX_RAW = 500
MAX_ERROR = 120
HISTORY_POINTS = 12
MIN_ETA_POINTS = 3
MAX_ETA_SECONDS = 10 * 365 * 86400
LINE_PREFIX = "ORCHESTRA_PROGRESS"
STATUSES = ("running", "paused", "waiting", "done", "error")
MODES = ("output", "command")


def validate_config(progress) -> str | None:
    """Return an error for a bad `progress` option of a run job, else None."""
    if not isinstance(progress, dict):
        return "progress must be an object"
    mode = progress.get("mode")
    if mode not in MODES:
        return "progress.mode must be 'output' or 'command'"
    if mode == "command":
        command = progress.get("command")
        if not isinstance(command, str) or not command.strip():
            return "progress.command is required for mode 'command'"
        if len(command) > MAX_COMMAND_CHARS:
            return f"progress.command is longer than {MAX_COMMAND_CHARS} characters"
    interval = progress.get("interval_seconds", DEFAULT_INTERVAL)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) \
            or not math.isfinite(interval) or not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        return f"progress.interval_seconds must be between {MIN_INTERVAL} and {MAX_INTERVAL}"
    return None


def interval_of(progress: dict) -> float:
    value = progress.get("interval_seconds", DEFAULT_INTERVAL)
    try:
        return max(MIN_INTERVAL, min(float(value), MAX_INTERVAL))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def _number(value, *, positive: bool = False) -> float | None:
    """A finite non-negative real, else None (bools, strings, NaN, inf, negatives refused)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        return None
    return number


def _text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def parse_text(text: str) -> tuple[dict, str] | None:
    """Last progress object in the text: a JSON object line or an `ORCHESTRA_PROGRESS` line.

    Returns (object, raw line) or None. Only the last 200 lines are considered, so a huge
    log costs nothing, and a line that is not a progress object is never guessed at.
    """
    lines = text.splitlines()[-200:]
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith(LINE_PREFIX):
            stripped = stripped[len(LINE_PREFIX):].strip()
        if not stripped.startswith("{"):
            continue
        try:
            data = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data, line.strip()[:MAX_RAW]
    return None


def normalize(raw: dict) -> dict:
    """Validated sample fields; raises ValueError when nothing usable remains."""
    if not isinstance(raw, dict):
        raise ValueError("sample is not an object")
    status = raw.get("status", "running")
    if status not in STATUSES:
        status = "unknown"
    completed = _number(raw.get("completed"))
    total = _number(raw.get("total"), positive=True)
    unit = _text(raw.get("unit"), MAX_UNIT)
    percent = _number(raw.get("percent"))
    if completed is None and total is None and percent is not None:
        completed, total, unit = min(percent, 100.0), 100.0, "%"
    if completed is not None and total is not None and completed > total:
        completed = total
    sample = {
        "status": status,
        "label": _text(raw.get("label"), MAX_LABEL),
        "completed": completed,
        "total": total,
        "unit": unit,
        "percent": None,
        "rate": _number(raw.get("rate")),
        "eta_seconds": _number(raw.get("eta_seconds")),
    }
    if sample["eta_seconds"] is not None and sample["eta_seconds"] > MAX_ETA_SECONDS:
        sample["eta_seconds"] = None
    if completed is not None and total is not None:
        sample["percent"] = round(min(100.0, completed / total * 100.0), 1)
    if completed is None and not sample["label"] and "status" not in raw:
        raise ValueError("sample has no usable fields")
    return sample


def _blank() -> dict:
    return {"v": 1, "history": [], "resets": 0, "errors": 0}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def ingest(previous: dict | None, raw: dict, raw_line: str, mode: str,
           interval: float, now: float | None = None) -> dict:
    """Fold one sample into the durable record. Raises ValueError for an unusable sample."""
    now = time.time() if now is None else now
    sample = normalize(raw)
    record = _blank()
    if isinstance(previous, dict):
        record["history"] = [
            point for point in previous.get("history") or []
            if isinstance(point, list) and len(point) == 2
        ][-HISTORY_POINTS:]
        record["resets"] = int(previous.get("resets") or 0)
        record["moved_at"] = previous.get("moved_at")
    history = record["history"]
    completed = sample["completed"]
    sample["reset"] = False
    if completed is not None:
        if history and completed < history[-1][1]:
            # The counter went backwards (restart, new file, re-check): earlier points
            # would give a negative or inflated rate, so the estimate starts over.
            history.clear()
            record["resets"] += 1
            sample["reset"] = True
            record["moved_at"] = _iso(now)
        last = history[-1][1] if history else None
        if last is None or completed > last:
            record["moved_at"] = _iso(now)
        if not history or now > history[-1][0]:
            history.append([now, completed])
        del history[:-HISTORY_POINTS]
    rate_observed = None
    if len(history) >= 2:
        span = history[-1][0] - history[0][0]
        gained = history[-1][1] - history[0][1]
        if span >= MIN_INTERVAL and gained > 0:
            rate_observed = gained / span
    sample["rate_source"] = "reported" if sample["rate"] is not None else (
        "estimated" if rate_observed is not None else "")
    if sample["rate"] is None:
        sample["rate"] = rate_observed
    sample["eta_source"] = ""
    running = sample["status"] == "running"
    if sample["eta_seconds"] is not None and running:
        sample["eta_source"] = "reported"
    elif sample["eta_seconds"] is not None:
        sample["eta_seconds"] = None
    if sample["eta_seconds"] is None and running and completed is not None \
            and sample["total"] is not None and sample["rate"] and sample["rate"] > 0 \
            and len(history) >= MIN_ETA_POINTS:
        left = max(sample["total"] - completed, 0.0)
        eta = left / sample["rate"]
        if math.isfinite(eta) and eta <= MAX_ETA_SECONDS:
            sample["eta_seconds"] = round(eta)
            sample["eta_source"] = "estimated"
    sample["observed_at"] = _iso(now)
    record.update(
        mode=mode, interval=interval, sample=sample, raw=raw_line[:MAX_RAW],
        updated_at=_iso(now), last_ok_at=_iso(now), error="", error_at="", errors=0,
    )
    return record


def mark_error(previous: dict | None, reason: str, mode: str, interval: float,
               now: float | None = None) -> dict:
    """Keep the last good sample but say honestly that reading it failed."""
    now = time.time() if now is None else now
    record = dict(previous) if isinstance(previous, dict) else _blank()
    record.update(
        v=1, mode=mode, interval=interval, updated_at=_iso(now),
        error=_text(reason, MAX_ERROR) or "error", error_at=_iso(now),
        errors=int(record.get("errors") or 0) + 1,
    )
    record.setdefault("history", [])
    record.setdefault("resets", 0)
    return record


def summary(config: dict, now: float | None = None) -> str:
    """One-line text for `bg_list`; empty when the job has no progress record."""
    record = (config or {}).get("_progress")
    if not isinstance(record, dict) or not isinstance(record.get("sample"), dict):
        return ""
    sample = record["sample"]
    parts = []
    if sample.get("percent") is not None:
        parts.append(f"{sample['percent']:g}%")
    if sample.get("completed") is not None and sample.get("total") is not None:
        unit = f" {sample['unit']}" if sample.get("unit") and sample["unit"] != "%" else ""
        if sample.get("unit") != "%":
            parts.append(f"{sample['completed']:g}/{sample['total']:g}{unit}")
    if sample.get("status") and sample["status"] != "running":
        parts.append(sample["status"])
    if sample.get("eta_seconds") is not None:
        parts.append(f"ETA ~{int(sample['eta_seconds'])}s")
    if record.get("error"):
        parts.append(f"sampler error: {record['error']}")
    return " · ".join(parts)
