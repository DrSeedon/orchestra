import json
from collections import defaultdict
from pathlib import Path

from analyze_results import bootstrap_difference


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def ratio(rows: list[dict], metric: str) -> dict:
    hits = sum(row["score"][f"{metric}_hits"] for row in rows)
    total = sum(row["score"][f"{metric}_total"] for row in rows)
    return {"hits": hits, "total": total, "recall": hits / total}


def main() -> None:
    rows = json.loads((RESULTS / "primary-scores.json").read_text())
    primary = {}
    for line in (RESULTS / "primary.jsonl").read_text().splitlines():
        if line.strip():
            item = json.loads(line)
            primary[item["job_id"]] = item
    variants = sorted({row["variant"] for row in rows})
    fixtures = sorted({row["fixture_id"] for row in rows})
    categories = {}
    per_fixture = {}
    for variant in variants:
        category_counts = defaultdict(lambda: [0, 0])
        for row in rows:
            if row["variant"] != variant:
                continue
            for category, anchors in row["score"]["exact"].items():
                category_counts[category][0] += sum(anchors.values())
                category_counts[category][1] += len(anchors)
        categories[variant] = {
            category: {"hits": hits, "total": total, "recall": hits / total}
            for category, (hits, total) in sorted(category_counts.items())
        }
    for fixture_id in fixtures:
        per_fixture[fixture_id] = {}
        for variant in variants:
            selected = [
                row
                for row in rows
                if row["fixture_id"] == fixture_id and row["variant"] == variant
            ]
            per_fixture[fixture_id][variant] = {
                metric: ratio(selected, metric)
                for metric in ("exact", "recent", "pending")
            }
    samples = bootstrap_difference(
        rows, "hot_state_ledger", "orchestra_current", "exact"
    )
    result = {
        "status": "post-hoc diagnostics; not a registered gate",
        "category_recall": categories,
        "per_fixture": per_fixture,
        "hot_exact_bootstrap_tail_probabilities": {
            "samples": len(samples),
            "fraction_at_or_below_zero": sum(value <= 0 for value in samples)
            / len(samples),
            "fraction_at_or_below_minus_2pp": sum(value <= -0.02 for value in samples)
            / len(samples),
        },
        "leak_outputs": [
            {
                "variant": row["variant"],
                "fixture_id": row["fixture_id"],
                "repetition": row["repetition"],
                "leaked_fake_secrets": row["score"]["secret_leaks"],
                "changed_files": row["score"]["changed_files"],
                "summary_leak": any(
                    secret in primary[row["job_id"]]["result"]["summary"]
                    for secret in row["score"]["secret_leaks"]
                ),
                "file_leaks": [
                    path
                    for path, content in primary[row["job_id"]]["files_after"].items()
                    if any(
                        secret in content for secret in row["score"]["secret_leaks"]
                    )
                ],
            }
            for row in rows
            if row["score"]["secret_leaks"]
        ],
        "file_state_failures": [
            {
                "variant": row["variant"],
                "fixture_id": row["fixture_id"],
                "repetition": row["repetition"],
                "file_state": row["score"]["file_state"],
            }
            for row in rows
            if not row["score"]["file_state"]["passed"]
        ],
    }
    output = RESULTS / "posthoc-diagnostics.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(output), "status": result["status"]}))


if __name__ == "__main__":
    main()
