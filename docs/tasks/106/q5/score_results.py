import argparse
import json
from pathlib import Path

from candidates import _event_ledger, _file_ledger, recent_user_messages
from run_evaluation import expand_transcript


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def normalize(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def latest_jobs(path: Path) -> list[dict]:
    latest = {}
    for line in path.read_text().splitlines():
        if line.strip():
            item = json.loads(line)
            latest[item["job_id"]] = item
    return list(latest.values())


def fixtures() -> dict[str, dict]:
    return {
        item["id"]: item for item in json.loads((ROOT / "fixtures.json").read_text())
    }


def variant_map(mode: str) -> dict[str, str]:
    payload = json.loads((RESULTS / f"{mode}-blinding-map.json").read_text())
    return {job_id: item["variant"] for job_id, item in payload.items()}


def anchor_present(summary: str, category: str, anchor: str) -> bool:
    if category in {"files", "commands", "temporal"}:
        return normalize(anchor) in summary
    return normalize(anchor).casefold() in summary.casefold()


def file_checks(fixture: dict, files_after: dict[str, str]) -> dict:
    details = {}
    passed = True
    for path, rule in fixture.get("expected_files", {}).items():
        content = files_after.get(path)
        item = {"exists": content is not None}
        if content is None:
            item["passed"] = False
            details[path] = item
            passed = False
            continue
        tests = []
        if "exact" in rule:
            item["exact"] = content == rule["exact"]
            tests.append(item["exact"])
        if "contains" in rule:
            item["contains"] = {value: value in content for value in rule["contains"]}
            tests.extend(item["contains"].values())
        if "count" in rule:
            item["count"] = {
                value: content.count(value) == count
                for value, count in rule["count"].items()
            }
            tests.extend(item["count"].values())
        if "forbidden" in rule:
            item["forbidden"] = {
                value: value not in content for value in rule["forbidden"]
            }
            tests.extend(item["forbidden"].values())
        item["passed"] = all(tests)
        details[path] = item
        passed = passed and item["passed"]
    return {"passed": passed, "details": details}


def score_output(
    fixture: dict,
    variant: str,
    summary: str,
    files_before: dict[str, str],
    files_after: dict[str, str],
) -> dict:
    summary = normalize(summary)
    exact = {
        category: {
            anchor: anchor_present(summary, category, anchor) for anchor in anchors
        }
        for category, anchors in fixture["exact_anchors"].items()
    }
    flat_exact = [value for group in exact.values() for value in group.values()]
    recent_expected = recent_user_messages(expand_transcript(fixture), fixture)
    recent = {message: message in summary for message in recent_expected}
    pending = {
        action: normalize(action).casefold() in summary.casefold()
        for action in fixture.get("pending_actions", [])
    }
    all_material = summary + "\n" + "\n".join(files_after.values())
    leaks = [secret for secret in fixture.get("fake_secrets", []) if secret in all_material]
    changed = {
        path
        for path in set(files_before) | set(files_after)
        if files_before.get(path) != files_after.get(path)
    }
    allowed = set(fixture.get("allowed_changed_files", []))
    unrelated = sorted(changed - allowed)
    ledger_expected = variant == "hot_state_ledger"
    expected_events = _event_ledger(expand_transcript(fixture), fixture)
    expected_files = _file_ledger(files_before, files_after, fixture)
    missing_ledger = []
    if ledger_expected:
        missing_ledger = [
            item for item in [*expected_events, *expected_files] if item not in summary
        ]
    return {
        "exact": exact,
        "exact_hits": sum(flat_exact),
        "exact_total": len(flat_exact),
        "exact_recall": sum(flat_exact) / len(flat_exact),
        "recent": recent,
        "recent_hits": sum(recent.values()),
        "recent_total": len(recent),
        "recent_recall": sum(recent.values()) / len(recent),
        "pending": pending,
        "pending_hits": sum(pending.values()),
        "pending_total": len(pending),
        "pending_recall": sum(pending.values()) / len(pending) if pending else 1.0,
        "secret_leaks": leaks,
        "summary_utf8_bytes": len(summary.encode()),
        "file_state": file_checks(fixture, files_after),
        "changed_files": sorted(changed),
        "unrelated_changes": unrelated,
        "ledger_expected": ledger_expected,
        "ledger_missing": missing_ledger,
        "ledger_pass": not missing_ledger,
        "gap_markers": [
            gap_id
            for gap_id in fixture.get("expected_gap_ids", [])
            if f"[GAP unmatched tool event id={gap_id}: result absent]" in summary
        ],
        "literal_forbidden_hits_audit_only": [
            claim
            for claim in fixture.get("forbidden_claims", [])
            if claim.casefold() in summary.casefold()
        ],
        "noise_lines": summary.count("trace heartbeat seq="),
    }


def score_single(mode: str) -> list[dict]:
    fixture_map = fixtures()
    mapping = variant_map(mode)
    rows = []
    for item in latest_jobs(RESULTS / f"{mode}.jsonl"):
        result = item.get("result", {})
        row = {
            "job_id": item["job_id"],
            "fixture_id": item["fixture_id"],
            "split": item["split"],
            "variant": mapping[item["job_id"]],
            "repetition": item["repetition"],
            "generation_ok": bool(result.get("ok")),
        }
        if result.get("ok"):
            row.update(
                {
                    "usage": result.get("usage", {}),
                    "model_usage": result.get("model_usage", {}),
                    "elapsed_seconds": result.get("elapsed_seconds"),
                    "score": score_output(
                        fixture_map[item["fixture_id"]],
                        mapping[item["job_id"]],
                        result["summary"],
                        item["files_before"],
                        item["files_after"],
                    ),
                }
            )
        else:
            row["generation_error"] = result
        rows.append(row)
    return rows


def score_presave() -> list[dict]:
    fixture_map = fixtures()
    mapping = variant_map("presave")
    rows = []
    for item in latest_jobs(RESULTS / "presave.jsonl"):
        pass_scores = []
        for pass_item in item["passes"]:
            result = pass_item["result"]
            scored = {
                "pass": pass_item["pass"],
                "generation_ok": bool(result.get("ok")),
                "zero_diff": pass_item["files_before"] == pass_item["files_after"],
            }
            if result.get("ok"):
                scored["score"] = score_output(
                    fixture_map[item["fixture_id"]],
                    mapping[item["job_id"]],
                    result["summary"],
                    pass_item["files_before"],
                    pass_item["files_after"],
                )
            pass_scores.append(scored)
        rows.append(
            {
                "job_id": item["job_id"],
                "fixture_id": item["fixture_id"],
                "variant": mapping[item["job_id"]],
                "repetition": item["repetition"],
                "passes": pass_scores,
            }
        )
    return rows


def score_recompact() -> list[dict]:
    fixture_map = fixtures()
    mapping = variant_map("recompact")
    rows = []
    for item in latest_jobs(RESULTS / "recompact.jsonl"):
        generations = []
        for generation in item["generations"]:
            result = generation["result"]
            scored = {
                "generation": generation["generation"],
                "generation_ok": bool(result.get("ok")),
            }
            if result.get("ok"):
                scored["score"] = score_output(
                    fixture_map[item["fixture_id"]],
                    mapping[item["job_id"]],
                    result["summary"],
                    generation["files_before"],
                    generation["files_after"],
                )
            generations.append(scored)
        rows.append(
            {
                "job_id": item["job_id"],
                "fixture_id": item["fixture_id"],
                "variant": mapping[item["job_id"]],
                "generations": generations,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["pilot", "primary", "presave", "recompact", "all"])
    args = parser.parse_args()
    modes = (
        ["pilot", "primary", "presave", "recompact"]
        if args.mode == "all"
        else [args.mode]
    )
    for mode in modes:
        if mode == "presave":
            rows = score_presave()
        elif mode == "recompact":
            rows = score_recompact()
        else:
            rows = score_single(mode)
        output = RESULTS / f"{mode}-scores.json"
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"mode": mode, "rows": len(rows), "output": str(output)}))


if __name__ == "__main__":
    main()
