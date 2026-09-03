"""Atomic persistence and validation for codex_review output artifacts."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


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


def _last_agent_message(jsonl_path: Path) -> str:
    message = ""
    try:
        with jsonl_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                item = row.get("item") if isinstance(row, dict) else None
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        message = text.strip()
    except OSError:
        return ""
    return message


def _record_terminal_receipt(
    *, receipt_id: str, output: Path, jsonl_file: Path, status: str,
    return_code: int | None, failure_code: str = "",
    recovery_source: str = "", receipt_round: int | None = None,
) -> None:
    if not receipt_id:
        return
    include_artifact = status == "completed" or failure_code == "execution_guard"
    artifact_exists = include_artifact and output.is_file()
    artifact_bytes = output.stat().st_size if artifact_exists else None
    artifact_sha256 = ""
    verdict_present = False
    verdict_value = ""
    if artifact_exists:
        content = output.read_bytes()
        artifact_sha256 = hashlib.sha256(content).hexdigest()
        decoded = content.decode("utf-8", errors="replace")
        if receipt_round and receipt_round > 1:
            rounds = re.split(r"(?im)^##\s+Round\b", decoded)
            decoded = rounds[-1]
        match = re.search(r"(?ims)^##\s+Verdict\s*\n+(.+?)(?:\n##\s|\Z)", decoded)
        if match:
            verdict_present = True
            verdict_value = " ".join(match.group(1).split())
    jsonl_response_present = bool(_last_agent_message(jsonl_file))
    if recovery_source == "":
        recovery_source = ""
    try:
        if __package__ in (None, ""):
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from app.db import review_receipt_finish, review_receipt_get

        receipt = review_receipt_get(receipt_id) or {}
        coverage_outcome = (
            "reviewed"
            if (
                receipt.get("subject_kind") == "implementation"
                and status == "completed"
                and return_code == 0
                and artifact_exists
                and jsonl_response_present
            )
            else "unknown"
        )

        review_receipt_finish(
            receipt_id,
            {
                "status": status,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "return_code": return_code,
                "failure_code": failure_code,
                "artifact_exists": int(artifact_exists),
                "artifact_bytes": artifact_bytes,
                "artifact_sha256": artifact_sha256,
                "verdict_present": int(verdict_present),
                "verdict_value": verdict_value,
                "jsonl_response_present": int(jsonl_response_present),
                "recovery_source": recovery_source,
                "coverage_outcome": coverage_outcome,
            },
        )
    except Exception as error:
        print(f"Codex review receipt unaccounted: {type(error).__name__}: {error}", file=sys.stderr)


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
                             usage_task_id: str = "", usage_model: str = "",
                             receipt_id: str = "", receipt_status: str = "completed",
                             receipt_return_code: int = 0,
                             receipt_round: int | None = None) -> None:
    """Validate the final agent message, persist it atomically, and store its thread UUID."""
    recovery_source = ""
    try:
        review = round_file.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise ValueError(f"review output is missing: {round_file}: {e}") from e
    if not review:
        review = _last_agent_message(jsonl_file)
        if review:
            recovery_source = "jsonl_agent_message"
        else:
            raise ValueError(f"review output is empty: {round_file}")
    if require_verdict and re.search(r"(?im)^##\s+Verdict\b", review) is None:
        raise ValueError("review output has no '## Verdict' section")

    thread_id = _last_thread_id(jsonl_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    sessions_file.parent.mkdir(parents=True, exist_ok=True)
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", receipt_id or uuid4().hex)
    lock_name = hashlib.sha256(str(output.resolve()).encode()).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"codex-review-publish-{lock_name}.lock"
    output_tmp = output.with_name(f"{output.name}.{token}.tmp")
    sessions_tmp = sessions_file.with_name(f"{sessions_file.name}.{token}.tmp")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            sessions = {"sessions": {}}
            try:
                loaded = json.loads(sessions_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("sessions"), dict):
                    sessions = loaded
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            previous = sessions["sessions"].get(slug) or {}
            thread_id = thread_id or previous.get("uuid", "")
            if not thread_id and not recovery_source:
                raise ValueError(f"Codex thread UUID is missing from {jsonl_file}")
            expected_output = _file_sha256(output)
            expected_sessions = _file_sha256(sessions_file)
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
            output_tmp.write_text(content, encoding="utf-8")
            sessions_tmp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
            if _file_sha256(output) != expected_output or _file_sha256(sessions_file) != expected_sessions:
                raise ValueError("review artifact changed during finalization")
            os.replace(output_tmp, output)
            os.replace(sessions_tmp, sessions_file)
        finally:
            output_tmp.unlink(missing_ok=True)
            sessions_tmp.unlink(missing_ok=True)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
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
        if not recovery_source and not receipt_id:
            with output.open("a", encoding="utf-8") as fh:
                fh.write(f"\n> ⚠ {warning}\n")
        print(warning, file=sys.stderr)
    _record_terminal_receipt(
        receipt_id=receipt_id or (
            usage_event_id.replace("codex-review:", "review-receipt:", 1)
            if usage_event_id.startswith("codex-review:") else ""
        ),
        output=output,
        jsonl_file=jsonl_file,
        status=receipt_status,
        return_code=receipt_return_code,
        recovery_source=recovery_source,
        receipt_round=receipt_round,
    )


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
    parser.add_argument("--receipt-id", default="")
    parser.add_argument("--record-terminal", action="store_true")
    parser.add_argument("--receipt-status", default="completed")
    parser.add_argument("--receipt-return-code", type=int, default=0)
    parser.add_argument("--receipt-failure-code", default="")
    parser.add_argument("--receipt-round", type=int, default=0)
    args = parser.parse_args()
    if args.record_terminal:
        _record_terminal_receipt(
            receipt_id=args.receipt_id,
            output=args.output,
            jsonl_file=args.jsonl_file,
            status=args.receipt_status,
            return_code=args.receipt_return_code,
            failure_code=args.receipt_failure_code,
            receipt_round=args.receipt_round or None,
        )
        return 0
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
            receipt_id=args.receipt_id,
            receipt_status=args.receipt_status,
            receipt_return_code=args.receipt_return_code,
            receipt_round=args.receipt_round or None,
        )
    except ValueError as e:
        print(f"codex_review artifact validation failed: {e}")
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
