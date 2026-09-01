"""Compare #395 before/after rows only when they describe the same frozen corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _rows(path: Path) -> list[dict]:
    values = [json.loads(line) for line in path.read_text().splitlines()]
    rows = [value for value in values if "summary" not in value]
    if not rows:
        raise SystemExit(f"no measurement rows: {path}")
    return rows


def _identity(rows: list[dict]) -> dict:
    fields = (
        "client_deadline_seconds",
        "current_projection_rows",
        "task_state_rows",
    )
    identities = [{field: row.get(field) for field in fields} for row in rows]
    if any(identity != identities[0] for identity in identities[1:]):
        raise SystemExit("one artifact contains multiple corpus identities")
    return identities[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--expected-current-rows", type=int, required=True)
    parser.add_argument("--expected-task-rows", type=int, required=True)
    parser.add_argument("--max-startup-seconds", type=float)
    parser.add_argument("--max-create-seconds", type=float)
    parser.add_argument("--max-contended-list-seconds", type=float)
    args = parser.parse_args()

    before = _rows(args.before)
    after = _rows(args.after)
    if len(before) != len(after):
        raise SystemExit(
            f"measurement row count mismatch: before={len(before)} after={len(after)}"
        )
    before_identity = _identity(before)
    after_identity = _identity(after)
    expected = {
        "client_deadline_seconds": 30,
        "current_projection_rows": args.expected_current_rows,
        "task_state_rows": args.expected_task_rows,
    }
    if before_identity != expected or after_identity != expected:
        raise SystemExit(json.dumps({
            "error": "benchmark corpus mismatch",
            "expected": expected,
            "before": before_identity,
            "after": after_identity,
        }, sort_keys=True))
    for row in after:
        if row.get("startup_receipts") != "cleared":
            raise SystemExit("after arm did not clear startup receipts")
        if row.get("startup_page_cache") != "dropped":
            raise SystemExit("after arm did not request cloned-file page-cache eviction")

    metrics = {
        "startup_runtime_seconds": args.max_startup_seconds,
        "create_seconds": args.max_create_seconds,
        "contended_task_list_seconds": args.max_contended_list_seconds,
    }
    result = {
        "corpus": expected,
        "before": {},
        "after": {},
        "limits": {},
        "statistic": "maximum across every measurement row",
    }
    failed = []
    for metric, limit in metrics.items():
        if limit is None:
            continue
        if any(metric not in row for row in [*before, *after]):
            raise SystemExit(f"measurement row is missing required metric: {metric}")
        before_value = max(float(row[metric]) for row in before)
        after_value = max(float(row[metric]) for row in after)
        result["before"][metric] = before_value
        result["after"][metric] = after_value
        result["limits"][metric] = limit
        if after_value > limit:
            failed.append(f"{metric}={after_value:.6f} > {limit:.6f}")
    print(json.dumps(result, sort_keys=True))
    if failed:
        raise SystemExit("; ".join(failed))


if __name__ == "__main__":
    main()
