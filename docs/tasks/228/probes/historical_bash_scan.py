"""Replay task #228's Bash classifier over a read-only Orchestra log snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from app.backend_claude import _classify_bash_payload  # noqa: E402
from app.secret_mask import mask_secrets  # noqa: E402


_FAILURE_HINTS = {
    "recursive rm text": re.compile(
        r"(?i)(?:^|[;&|()\s])(?:/\S*/)?rm\s+(?:-[^\s]*[rR]|--recursive\b)"
    ),
    "chmod 777 text": re.compile(
        r"(?i)(?:^|[;&|()\s])(?:/\S*/)?chmod(?:\s+-\S+)*\s+0?777\b"
    ),
    "curl pipe shell text": re.compile(
        r"(?is)(?:^|[;&|()\s])(?:/\S*/)?curl\b[^\n]*\|\s*(?:/\S*/)?(?:ba)?sh\b"
    ),
}

# Manual adjudication at the immutable cutoff. Both rows write `rm -rf` into a
# heredoc-created script; the current Bash invocation does not execute that text.
_TEXT_DETECTOR_FALSE_POSITIVES = {
    "recursive rm text": {68878, 69082},
    "chmod 777 text": set(),
    "curl pipe shell text": set(),
}


def _payload(content: str) -> dict:
    _, separator, encoded = content.partition(": ")
    if not separator:
        raise ValueError("tool log has no payload separator")
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("tool payload is not an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/home/kesha/orchestra/data/orchestra.db")
    parser.add_argument("--cutoff", type=int)
    args = parser.parse_args()

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    db.execute("BEGIN")
    cutoff = args.cutoff or db.execute("SELECT MAX(id) FROM logs").fetchone()[0]
    rows = db.execute(
        """
        SELECT l.id, s.name, l.ts, l.content
        FROM logs AS l
        JOIN sessions AS s ON s.id = l.session_id
        WHERE l.id <= ?
          AND l.type = 'tool'
          AND l.tool_name = 'Bash'
          AND s.backend_type = 'claude'
        ORDER BY l.id
        """,
        (cutoff,),
    ).fetchall()

    parse_failures: list[tuple[int, str, str]] = []
    classifier_failures: list[tuple[int, str, str, str, str]] = []
    matches: list[tuple[int, str, str, str, str]] = []
    categories: dict[str, int] = {}
    reference_ids = {label: set() for label in _FAILURE_HINTS}
    predicted_ids: dict[str, set[int]] = {}
    multiline_commands = 0
    classifier_ms: list[float] = []

    for log_id, agent, timestamp, content in rows:
        try:
            payload = _payload(content)
        except (ValueError, json.JSONDecodeError) as exc:
            parse_failures.append((log_id, agent, type(exc).__name__))
            continue
        command = payload.get("command")
        if isinstance(command, str):
            multiline_commands += "\n" in command
            for label, pattern in _FAILURE_HINTS.items():
                if pattern.search(command):
                    reference_ids[label].add(log_id)
        try:
            started = time.perf_counter_ns()
            classification = _classify_bash_payload(payload)
        except Exception as exc:
            classifier_ms.append((time.perf_counter_ns() - started) / 1_000_000)
            classifier_failures.append(
                (log_id, agent, timestamp, type(exc).__name__, command or "")
            )
            continue
        classifier_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        if classification:
            categories[classification] = categories.get(classification, 0) + 1
            predicted_ids.setdefault(classification, set()).add(log_id)
            matches.append(
                (log_id, agent, timestamp, classification, mask_secrets(command or ""))
            )

    print("# Historical Claude Bash classifier replay")
    print()
    print(f"- Immutable cutoff: `logs.id <= {cutoff}`.")
    print(f"- Claude `Bash` tool rows: **{len(rows)}**.")
    print(f"- Parseable tool payloads: **{len(rows) - len(parse_failures)}**.")
    print(f"- Classifier matches: **{len(matches)}**; categories: `{categories}`.")
    print(f"- Classifier failures (fail-open): **{len(classifier_failures)}**.")
    print(f"- Tool-payload parse failures: **{len(parse_failures)}**.")
    print(
        f"- Multi-line commands: **{multiline_commands}/{len(rows)} "
        f"({multiline_commands / len(rows):.1%})**."
    )
    ordered_ms = sorted(classifier_ms)
    p50_ms = ordered_ms[len(ordered_ms) // 2]
    p99_ms = ordered_ms[max(0, int(len(ordered_ms) * 0.99) - 1)]
    print(
        f"- Single-pass classifier interval: p50 **{p50_ms:.3f} ms**, "
        f"p99 **{p99_ms:.3f} ms**, max **{max(ordered_ms):.3f} ms**."
    )
    print()
    print("## Precision and recall against the preregistered text detectors")
    print()
    reference_categories = {
        "recursive rm text": "recursive_rm",
        "chmod 777 text": "world_writable",
        "curl pipe shell text": "curl_pipe_shell",
    }
    total_predicted: set[int] = set()
    total_reference: set[int] = set()
    for label, classification in reference_categories.items():
        predicted = predicted_ids.get(classification, set())
        raw_reference = reference_ids[label]
        excluded_reference = raw_reference & _TEXT_DETECTOR_FALSE_POSITIVES[label]
        reference = raw_reference - excluded_reference
        true_positive = predicted & reference
        false_positive = predicted - reference
        missed = reference - predicted
        total_predicted.update(predicted)
        total_reference.update(reference)
        precision = len(true_positive) / len(predicted) if predicted else None
        recall = len(true_positive) / len(reference) if reference else None
        precision_text = f"{precision:.1%}" if precision is not None else "n/a"
        recall_text = f"{recall:.1%}" if recall is not None else "n/a"
        print(
            f"- `{classification}`: predicted **{len(predicted)}**, reference-positive "
            f"**{len(reference)}** after excluding detector-only ids "
            f"`{sorted(excluded_reference)}`, TP **{len(true_positive)}**, "
            f"FP **{len(false_positive)}**, "
            f"FN **{len(missed)}**, precision **{precision_text}**, recall **{recall_text}**; "
            f"FP ids `{sorted(false_positive)}`, FN ids `{sorted(missed)}`."
        )
    total_true_positive = total_predicted & total_reference
    total_false_positive = total_predicted - total_reference
    total_missed = total_reference - total_predicted
    total_precision = len(total_true_positive) / len(total_predicted)
    total_recall = len(total_true_positive) / len(total_reference)
    print(
        f"- **Overall:** TP **{len(total_true_positive)}**, FP **{len(total_false_positive)}**, "
        f"FN **{len(total_missed)}**, precision **{total_precision:.1%}**, "
        f"recall **{total_recall:.1%}**."
    )
    print()
    print("## Classifier failures")
    print()
    for label, pattern in _FAILURE_HINTS.items():
        ids = [row[0] for row in classifier_failures if pattern.search(row[4])]
        print(f"- `{label}` among failed commands: **{len(ids)}**, ids: `{ids}`.")
    if classifier_failures:
        print("- Failed rows (content omitted):")
        for log_id, agent, timestamp, error, command in classifier_failures:
            print(
                f"  - `{log_id}` · `{agent}` · `{timestamp}` · `{error}` · "
                f"command length `{len(command)}`"
            )
    print()
    print("## Exact masked matches")
    print()
    for log_id, agent, timestamp, classification, command in matches:
        encoded = json.dumps(command, ensure_ascii=False)
        print(
            f"1. `{log_id}` · `{agent}` · `{timestamp}` · `{classification}`: "
            f"`{encoded}`"
        )


if __name__ == "__main__":
    main()
