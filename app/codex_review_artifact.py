"""Atomic persistence and validation for codex_review output artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
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


def finalize_review_artifact(*, output: Path, round_file: Path, sessions_file: Path,
                             slug: str, jsonl_file: Path, resume: bool,
                             require_verdict: bool) -> None:
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
    if resume and output.exists():
        prior = output.read_text(encoding="utf-8").rstrip()
        content = f"{prior}\n\n## Round ({now})\n\n{review}\n"
    else:
        content = review + "\n"
    output_tmp = output.with_name(output.name + ".tmp")
    output_tmp.write_text(content, encoding="utf-8")
    os.replace(output_tmp, output)

    sessions["sessions"][slug] = {
        "uuid": thread_id,
        "started": previous.get("started") or now,
        "last_used": now,
        "turns": int(previous.get("turns") or 0) + 1,
    }
    sessions_file.parent.mkdir(parents=True, exist_ok=True)
    sessions_tmp = sessions_file.with_name(sessions_file.name + ".tmp")
    sessions_tmp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    os.replace(sessions_tmp, sessions_file)
    try:
        round_file.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--round-file", type=Path, required=True)
    parser.add_argument("--sessions-file", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--jsonl-file", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--require-verdict", action="store_true")
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
        )
    except ValueError as e:
        print(f"codex_review artifact validation failed: {e}")
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
