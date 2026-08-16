"""Atomic persistence and validation for codex_review output artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _last_thread_id(jsonl_path: Path) -> str:
    thread_id = ""
    try:
        with jsonl_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if row.get("type") == "thread.started" and row.get("thread_id"):
                    thread_id = str(row["thread_id"])
    except OSError:
        return ""
    return thread_id


def _record_usage(*, jsonl_file: Path, event_id: str, session_id: str,
                  scope: str, task_id: str, model: str) -> None:
    if not event_id or not session_id or not model:
        raise ValueError("Codex usage attribution is incomplete")
    thread_id = ""
    completed = []
    with jsonl_file.open(encoding="utf-8", errors="replace") as fh:
        for line_number, line in enumerate(fh, 1):
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if row.get("type") == "thread.started":
                thread_id = str(row.get("thread_id") or "")
            elif row.get("type") == "turn.completed":
                completed.append((line_number, thread_id, row.get("usage") or {}))
    if len(completed) != 1:
        raise ValueError(f"Codex review reported {len(completed)} completed usage events")
    line_number, thread_id, usage = completed[0]
    if not thread_id:
        raise ValueError("Codex usage appeared before thread.started")
    values = {}
    for key in (
        "input_tokens", "output_tokens", "cached_input_tokens",
        "cache_write_input_tokens",
    ):
        value = usage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"invalid Codex {key}: {value!r}")
        values[key] = value
    if values["input_tokens"] + values["output_tokens"] == 0:
        raise ValueError("Codex completed turn reported zero tokens")

    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.backend_codex import _codex_cost
    from app.db import turn_usage_add

    turn_usage_add(
        event_id=f"{event_id}:{thread_id}:{line_number}",
        session_id=session_id,
        scope=scope,
        task_id=task_id,
        runtime="codex",
        model=model,
        ok=True,
        stop_reason="end_turn",
        cost_usd=_codex_cost(
            model,
            values["input_tokens"],
            values["cached_input_tokens"],
            values["cache_write_input_tokens"],
            values["output_tokens"],
        ),
        input_tokens=values["input_tokens"],
        output_tokens=values["output_tokens"],
        cache_read_tokens=values["cached_input_tokens"],
        cache_create_tokens=values["cache_write_input_tokens"],
    )


def finalize_review_artifact(*, output: Path, round_file: Path, sessions_file: Path,
                             slug: str, jsonl_file: Path, resume: bool,
                             require_verdict: bool, usage_event_id: str = "",
                             usage_session_id: str = "", usage_scope: str = "",
                             usage_task_id: str = "", usage_model: str = "") -> None:
    """Validate the final agent message, persist it atomically, and store its thread UUID."""
    try:
        review = round_file.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise ValueError(f"review output is missing: {round_file}: {e}") from e
    if not review:
        raise ValueError(f"review output is empty: {round_file}")
    if require_verdict and re.search(r"(?im)^##\s+Verdict\b", review) is None:
        raise ValueError("review output has no '## Verdict' section")

    sessions = {"sessions": {}}
    try:
        loaded = json.loads(sessions_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("sessions"), dict):
            sessions = loaded
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    previous = sessions["sessions"].get(slug) or {}
    thread_id = _last_thread_id(jsonl_file) or previous.get("uuid", "")
    if not thread_id:
        raise ValueError(f"Codex thread UUID is missing from {jsonl_file}")
    output.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    model_metadata = (
        f"<!-- codex-review-metadata: "
        f"{json.dumps({'reviewer_model': usage_model}, sort_keys=True)} -->"
        if usage_model else ""
    )
    if resume and output.exists():
        prior = output.read_text(encoding="utf-8").rstrip()
        round_parts = [f"## Round ({now})", model_metadata, review]
        content = f"{prior}\n\n" + "\n\n".join(part for part in round_parts if part) + "\n"
    else:
        content = "\n\n".join(part for part in (model_metadata, review) if part) + "\n"
    output_tmp = output.with_name(output.name + ".tmp")
    output_tmp.write_text(content, encoding="utf-8")
    os.replace(output_tmp, output)

    session_metadata = {
        "uuid": thread_id,
        "started": previous.get("started") or now,
        "last_used": now,
        "turns": int(previous.get("turns") or 0) + 1,
    }
    reviewer_model = usage_model or previous.get("reviewer_model", "")
    if reviewer_model:
        session_metadata["reviewer_model"] = reviewer_model
    sessions["sessions"][slug] = session_metadata
    sessions_file.parent.mkdir(parents=True, exist_ok=True)
    sessions_tmp = sessions_file.with_name(sessions_file.name + ".tmp")
    sessions_tmp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    os.replace(sessions_tmp, sessions_file)
    try:
        round_file.unlink()
    except FileNotFoundError:
        pass

    usage_error = ""
    if not usage_event_id:
        usage_error = "caller did not provide usage attribution"
    else:
        try:
            _record_usage(
                jsonl_file=jsonl_file,
                event_id=usage_event_id,
                session_id=usage_session_id,
                scope=usage_scope,
                task_id=usage_task_id,
                model=usage_model,
            )
        except Exception as error:
            usage_error = f"{type(error).__name__}: {error}"
    if usage_error:
        warning = f"Codex usage unaccounted: {usage_error}"
        with output.open("a", encoding="utf-8") as fh:
            fh.write(f"\n> ⚠ {warning}\n")
        print(warning, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--round-file", type=Path, required=True)
    parser.add_argument("--sessions-file", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--jsonl-file", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--require-verdict", action="store_true")
    parser.add_argument("--usage-event-id", default="")
    parser.add_argument("--usage-session-id", default="")
    parser.add_argument("--usage-scope", default="")
    parser.add_argument("--usage-task-id", default="")
    parser.add_argument("--usage-model", default="")
    args = parser.parse_args()
    try:
        finalize_review_artifact(
            output=args.output,
            round_file=args.round_file,
            sessions_file=args.sessions_file,
            slug=args.slug,
            jsonl_file=args.jsonl_file,
            resume=args.resume,
            require_verdict=args.require_verdict,
            usage_event_id=args.usage_event_id,
            usage_session_id=args.usage_session_id,
            usage_scope=args.usage_scope,
            usage_task_id=args.usage_task_id,
            usage_model=args.usage_model,
        )
    except ValueError as e:
        print(f"codex_review artifact validation failed: {e}")
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
