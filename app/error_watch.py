"""Read-only recurring-error detector for journalctl and the session log."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import DB_PATH
from app.secret_mask import mask_secrets

DEFAULT_WINDOW_HOURS = 168
DEFAULT_THRESHOLD = 10
_NOISE = (
    ("quota/rate limit", re.compile(r"quota|rate[_ -]?limit|rate_limited|subscription limit", re.I)),
    ("hook policy block", re.compile(r"PreToolUse:|hook error:|recursive rm is blocked|bounded quantifier", re.I)),
    ("external timeout", re.compile(r"(?:TG |telegram|Anthropic usage fetch).*?(?:TimeoutError|timed? ?out|rate_limited)", re.I)),
    ("expected command termination", re.compile(r"command exited with code", re.I)),
    ("merge gate refusal", re.compile(r"DIFF TOO LARGE", re.I)),
    ("agent command exit code", re.compile(r"^Exit code (?:\d+|<N>)$", re.I)),
    ("external app tool argument", re.compile(r"This app tool requires", re.I)),
    ("external app unknown tool", re.compile(r"codex_apps/.*Unknown tool", re.I)),
    # Case-sensitive on purpose: a missing real `Bash` tool must still surface.
    ("agent misspelled tool name", re.compile(r"No such tool available: bash(?:_placeholder)?\b")),
    ("TG polling cut by shutdown", re.compile(r"Failed to fetch updates.*ServerDisconnectedError", re.I)),
    ("agent shell syntax", re.compile(r"-c: line (?:\d+|<N>): syntax error", re.I)),
    ("agent missing python package", re.compile(r"File \"<stdin>\".*ModuleNotFoundError", re.I)),
    ("Bash hook fail-open under load", re.compile(r"PreToolUse failed open \(TimeoutError\): classifier deadline", re.I)),
    # uvicorn cuts open SSE connections on every service restart; the chained-traceback
    # line carries no cause of its own — the real exception is logged as a separate line.
    ("restart graceful-shutdown timeout", re.compile(r"Cancel (?:\d+|<N>) running task\(s\), timeout graceful shutdown exceeded", re.I)),
    ("traceback chaining line", re.compile(r"^During handling of the above exception, another exception occurred:$", re.I)),
)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.I)
_LONG_HEX = re.compile(r"\b(?:0x)?[0-9a-f]{12,}\b", re.I)
_PATH = re.compile(r"(?<![\w])(?:/(?:[^\s:'\"<>]+/?)+)")
_SESSION = re.compile(r"\[(?!secret\b|PATH\]|PROJECT\]|ID\]|N\]|SESSION\])[A-Za-z0-9_.-]+\]", re.I)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_PREFIX = re.compile(r"^(?:WARNING|ERROR|CRITICAL|INFO|DEBUG):[\w.]+:\s*")
_SECRET_MARK = re.compile(r"\[secret[^\]]*\]", re.I)
_EXPECTED_LISTENER_END = re.compile(
    r"listen task exited without exception \(silent death\), status=AgentStatus\.(?:IDLE|WAITING)", re.I,
)
_UNEXPECTED_LISTENER_END = re.compile(
    r"listen task exited unexpectedly while RUNNING", re.I,
)
_SESSION_NAME = re.compile(r"\[([A-Za-z0-9_.-]+)\]")
_LISTENER_STATUS = re.compile(r"status=AgentStatus\.([A-Z]+)")
_URL = re.compile(r"(?:https?://|tg://)\S+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def normalize_signature(message: str) -> str:
    """Drop volatile logger prefixes, identifiers and values while retaining cause."""
    value = mask_secrets(message or "")
    value = _SECRET_MARK.sub("<SECRET>", value)
    value = _URL.sub("<URL>", value)
    value = _EMAIL.sub("<EMAIL>", value)
    value = _PREFIX.sub("", value.strip())
    value = _UUID.sub("<ID>", value)
    value = _LONG_HEX.sub("<ID>", value)
    value = _PATH.sub("<PATH>", value)
    value = _SESSION.sub("[SESSION]", value)
    value = re.sub(r"\bproject=[A-Za-z0-9_.-]+", "project=<PROJECT>", value, flags=re.I)
    value = _NUMBER.sub("<N>", value)
    return " ".join(value.split())[:1000]


def classify_noise(signature: str) -> str | None:
    if _EXPECTED_LISTENER_END.search(signature):
        return "normal per-turn listener completion"
    for label, pattern in _NOISE:
        if pattern.search(signature):
            return label
    return None


def safe_example(message: str) -> str:
    value = normalize_signature(message)
    value = re.sub(r"https?://\S+|\b\S+@\S+", "<URL>", value, flags=re.I)
    return value[:240]


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def collect_db_events(db_path: Path, since: datetime) -> list[dict]:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        rows = connection.execute(
            "SELECT ts, type, content FROM logs "
            "WHERE (tool_is_error=1 OR type='error') AND ts >= ? ORDER BY ts",
            (since.isoformat(),),
        ).fetchall()
    return [
        {"source": "logs", "ts": ts, "message": content}
        for ts, _kind, content in rows
        if _parse_ts(ts) and _parse_ts(ts) >= since
    ]


def collect_journal_events(since: datetime, *, runner=subprocess.run) -> list[dict]:
    result = runner(
        ["journalctl", "-u", "orchestra", "--since", since.isoformat(), "-o", "json",
         "--output-fields=MESSAGE,__REALTIME_TIMESTAMP", "--no-pager"],
        check=True, capture_output=True, text=True, timeout=45,
    )
    events = []
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
            message = row.get("MESSAGE", "")
            if isinstance(message, list):
                message = bytes(message).decode("utf-8", errors="replace")
            stamp = datetime.fromtimestamp(int(row["__REALTIME_TIMESTAMP"]) / 1_000_000, timezone.utc)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        if re.search(r"\b(?:ERROR|CRITICAL|exception|traceback|failed|error:|silent death)\b", message, re.I):
            events.append({"source": "journalctl", "ts": stamp.isoformat(), "message": message})
    return events


def deduplicate_events(events: list[dict]) -> list[dict]:
    unique = []
    seen_journal_records: set[tuple[str, ...]] = set()
    for event in events:
        signature = normalize_signature(event["message"])
        if signature:
            if event["source"] == "journalctl":
                session = _SESSION_NAME.search(event["message"])
                status = _LISTENER_STATUS.search(event["message"])
                if "silent death" in event["message"].lower():
                    duplicate_key = (
                        event["ts"],
                        session.group(1) if session else "",
                        status.group(1) if status else "",
                    )
                else:
                    duplicate_key = (
                        event["ts"], session.group(1) if session else "", signature,
                    )
                if duplicate_key in seen_journal_records:
                    continue
                seen_journal_records.add(duplicate_key)
            unique.append(event)
    return unique


def aggregate(events: list[dict], now: datetime, *, threshold=DEFAULT_THRESHOLD) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in deduplicate_events(events):
        grouped[normalize_signature(event["message"])].append(event)
    candidates, noise = [], []
    for signature, rows in grouped.items():
        timestamps = [parsed for row in rows if (parsed := _parse_ts(row["ts"]))]
        required = 1 if _UNEXPECTED_LISTENER_END.search(signature) else threshold
        if len(timestamps) < required or not timestamps:
            continue
        item = {
            "signature": signature,
            "count": len(rows),
            "first": min(timestamps).isoformat(),
            "last": max(timestamps).isoformat(),
            "examples": list(dict.fromkeys(safe_example(row["message"]) for row in rows))[:2],
            "noise": classify_noise(signature),
        }
        (noise if item["noise"] else candidates).append(item)
    sort_key = lambda item: (-item["count"], item["signature"])
    return sorted(candidates, key=sort_key), sorted(noise, key=sort_key)


def post_fix_verdict(events: list[dict], signature: str, started_at: datetime, window_hours: int) -> dict:
    matches = [
        event for event in events
        if normalize_signature(event["message"]) == signature
        and (parsed := _parse_ts(event["ts"])) and parsed >= started_at
    ]
    now = datetime.now(timezone.utc)
    elapsed = max(0.0, (now - started_at).total_seconds() / 3600)
    complete = elapsed >= window_hours
    return {
        "count": len(matches),
        "complete": complete,
        "verdict": f"повторилась {len(matches)} раз" if matches else (
            f"не повторилась за окно {window_hours} ч" if complete else "не повторилась пока; окно наблюдения не завершено"
        ),
    }


def _state_path(db_path: Path) -> Path:
    return db_path.resolve().parent / "error_watch.json"


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"alerts": {}, "fixes": {}}


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="error-watch-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _existing_refs(signature: str) -> dict:
    if "_fire_sync" in signature:
        return {"tasks": ["V-636"], "commit": "9035836a"}
    root = Path(__file__).resolve().parent.parent / ".orchestra" / "tasks"
    if not signature:
        return {"tasks": []}
    refs = []
    for report in root.glob("*/report.md"):
        if report.parent.name == "V-647":
            continue
        try:
            content = report.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        normalized_report = " ".join(normalize_signature(line) for line in content.splitlines())
        position = normalized_report.lower().find(signature.lower())
        if position < 0:
            continue
        context = normalized_report[max(0, position - 600):position + len(signature) + 600]
        refs.extend(re.findall(r"\bV-\d+\b", context))
        refs.append(report.parent.name)
    return {"tasks": list(dict.fromkeys(refs))[:6]}


def _brief_output(signals: list[dict], verdicts: list[dict]) -> str:
    lines = ["ERROR-WATCH: new findings"]
    for item in signals[:3]:
        known = item.get("known", {})
        if "task" in known:
            refs = f"{known['task']} {known['commit']}"
        else:
            found = known.get("known", {})
            refs = ", ".join(found.get("tasks", []))
            if found.get("commit"):
                refs = f"{refs} {found['commit']}".strip()
            refs = refs or "нет найденной задачи/фикса"
        examples = " | ".join(item.get("examples", [])[:2])
        line = (
            f"{item['count']} раз; {item['first']} — {item['last']}; "
            f"сигнатура: {item['signature']}; примеры: {examples}; известно: {refs}"
        )
        lines.append(line[:550])
    for item in verdicts[:2]:
        lines.append(
            f"post-fix {item['task']} {item['commit']}: {item['verdict']}; "
            f"сигнатура: {item['signature'][:160]}"
        )
    return "\n".join(lines)[:2800]


def scan(args) -> int:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.window_hours)
    events = collect_db_events(Path(args.db), since) + collect_journal_events(since)
    deduped_events = deduplicate_events(events)
    candidates, noise = aggregate(deduped_events, now, threshold=args.threshold)
    state_path = _state_path(Path(args.db))
    state = _load_state(state_path) if not args.dry_run else {"alerts": {}, "fixes": {}}
    active = {item["signature"] for item in candidates + noise}
    state["alerts"] = {key: value for key, value in state.get("alerts", {}).items() if key in active}
    signals = []
    for item in candidates:
        key = item["signature"]
        if key in state["alerts"]:
            continue
        refs = _existing_refs(key)
        fix = state.get("fixes", {}).get(key)
        reference = fix if fix else ({"known": refs} if refs else {"known": {"tasks": []}})
        item["known"] = reference
        signals.append(item)
        state["alerts"][key] = {"first_alerted": now.isoformat(), "count": item["count"]}
    verdicts = []
    all_events = deduped_events
    for signature, fix in state.get("fixes", {}).items():
        started = _parse_ts(fix.get("started_at"))
        if started:
            verdict = post_fix_verdict(all_events, signature, started, int(fix.get("window_hours", args.window_hours)))
            recurring = verdict["count"] > 0 and not fix.get("recurrence_reported")
            complete = verdict["complete"] and not fix.get("completion_reported")
            if recurring or complete:
                verdicts.append({"signature": signature, **fix, **verdict})
                if recurring:
                    fix["recurrence_reported"] = True
                if complete:
                    fix["completion_reported"] = True
    output = {
        "signals": signals,
        "post_fix": verdicts,
        "noise_count": len(noise),
        "noise_events": sum(item["count"] for item in noise),
        "noise_by_class": {
            label: sum(item["count"] for item in noise if item["noise"] == label)
            for label in sorted({item["noise"] for item in noise})
        },
        "events": len(events),
        "events_by_source": {
            source: sum(event["source"] == source for event in events)
            for source in ("journalctl", "logs")
        },
    }
    if args.dry_run:
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    elif signals or verdicts:
        visible = signals[:3]
        state["alerts"] = {
            key: value for key, value in state["alerts"].items()
            if key not in {item["signature"] for item in signals[3:]}
        }
        print(_brief_output(visible, verdicts))
    else:
        print("No new error-watch findings")
    if not args.dry_run:
        _write_state(state_path, state)
    return 0


def record_fix(args) -> int:
    signature = normalize_signature(args.signature)
    state_path = _state_path(Path(args.db))
    state = _load_state(state_path)
    state.setdefault("fixes", {})[signature] = {
        "task": args.task,
        "commit": args.commit,
        "started_at": args.started_at,
        "window_hours": args.window_hours,
    }
    _write_state(state_path, state)
    print(f"Зарегистрирован фикс {args.task} {args.commit}: {signature}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("scan")
    check.add_argument("--db", default=str(DB_PATH))
    check.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    check.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    check.add_argument("--dry-run", action="store_true")
    check.set_defaults(func=scan)
    fix = sub.add_parser("record-fix")
    fix.add_argument("--db", default=str(DB_PATH))
    fix.add_argument("--signature", required=True)
    fix.add_argument("--task", required=True)
    fix.add_argument("--commit", required=True)
    fix.add_argument("--started-at", required=True)
    fix.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    fix.set_defaults(func=record_fix)
    args = parser.parse_args(argv)
    if args.window_hours <= 0 or getattr(args, "threshold", DEFAULT_THRESHOLD) <= 0:
        parser.error("window-hours and threshold must be positive")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
