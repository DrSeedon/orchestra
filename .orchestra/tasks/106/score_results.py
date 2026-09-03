import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def normalize(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def latest_jobs(path: Path) -> list[dict]:
    rows = {}
    for item in load_jsonl(path):
        rows[item["job_id"]] = item
    return list(rows.values())


def load_fixture_map() -> dict[str, dict]:
    fixtures = json.loads((ROOT / "fixtures.json").read_text())
    return {fixture["id"]: fixture for fixture in fixtures}


def flatten_anchors(fixture: dict) -> list[tuple[str, str]]:
    return [
        (category, anchor)
        for category, anchors in fixture["exact_anchors"].items()
        for anchor in anchors
    ]


def expected_recent(fixture: dict) -> list[str]:
    values = []
    for message in fixture["recent_messages"]:
        for secret, replacement in fixture.get("redactions", {}).items():
            message = message.replace(secret, replacement)
        values.append(message)
    return values


def anchor_present(summary: str, category: str, anchor: str) -> bool:
    normalized = normalize(anchor)
    if category in {"files", "commands", "temporal"}:
        return normalized in summary
    return normalized.casefold() in summary.casefold()


def file_checks(fixture: dict, files_after: dict[str, str]) -> dict:
    expected = fixture.get("expected_files", {})
    details = {}
    ok = True
    for path, rule in expected.items():
        content = files_after.get(path)
        item = {"exists": content is not None}
        if content is None:
            item["passed"] = False
            details[path] = item
            ok = False
            continue
        if "exact" in rule:
            item["exact"] = content == rule["exact"]
        if "contains" in rule:
            item["contains"] = {
                value: value in content for value in rule["contains"]
            }
        if "count" in rule:
            item["count"] = {
                value: content.count(value) == count
                for value, count in rule["count"].items()
            }
        if "forbidden" in rule:
            item["forbidden"] = {
                value: value not in content for value in rule["forbidden"]
            }
        item["passed"] = all(
            value
            for key, group in item.items()
            if key not in {"exists", "passed"}
            for value in (group.values() if isinstance(group, dict) else [group])
        )
        details[path] = item
        ok = ok and item["passed"]
    return {"passed": ok, "details": details}


def score_output(
    fixture: dict,
    summary: str,
    files_before: dict[str, str],
    files_after: dict[str, str],
) -> dict:
    summary = normalize(summary)
    exact = {}
    for category, anchors in fixture["exact_anchors"].items():
        exact[category] = {
            anchor: anchor_present(summary, category, anchor) for anchor in anchors
        }
    flat = [value for group in exact.values() for value in group.values()]
    recent = {
        message: normalize(message) in summary for message in expected_recent(fixture)
    }
    pending = {
        action: normalize(action).casefold() in summary.casefold()
        for action in fixture.get("pending_actions", [])
    }
    all_material = summary + "\n" + "\n".join(files_after.values())
    leaks = [secret for secret in fixture.get("fake_secrets", []) if secret in all_material]
    forbidden = [
        claim
        for claim in fixture.get("forbidden_claims", [])
        if normalize(claim).casefold() in summary.casefold()
    ]
    file_state = file_checks(fixture, files_after)
    changed = {
        path
        for path in set(files_before) | set(files_after)
        if files_before.get(path) != files_after.get(path)
    }
    expected_changed = {
        path
        for path, rule in fixture.get("expected_files", {}).items()
        if "exact" not in rule or files_before.get(path) != rule["exact"]
    }
    unrelated_changes = sorted(changed - expected_changed)
    repeated_noise = summary.count("heartbeat seq=")
    return {
        "exact": exact,
        "exact_hits": sum(flat),
        "exact_total": len(flat),
        "exact_recall": sum(flat) / len(flat) if flat else 1.0,
        "recent": recent,
        "recent_hits": sum(recent.values()),
        "recent_total": len(recent),
        "pending": pending,
        "pending_hits": sum(pending.values()),
        "pending_total": len(pending),
        "secret_leaks": leaks,
        "forbidden_claims": forbidden,
        "file_state": file_state,
        "changed_files": sorted(changed),
        "unrelated_changes": unrelated_changes,
        "redundant_noise_lines": repeated_noise,
        "summary_chars": len(summary),
        "summary_utf8_bytes": len(summary.encode()),
        "hard_pass": (
            all(flat)
            and all(recent.values())
            and all(pending.values())
            and not leaks
            and not forbidden
            and repeated_noise <= 2
        ),
    }


def variant_map(mode: str) -> dict[str, str]:
    payload = json.loads((ROOT / "results" / f"{mode}-blinding-map.json").read_text())
    return {job_id: item["variant"] for job_id, item in payload.items()}


def score_primary() -> list[dict]:
    fixtures = load_fixture_map()
    mapping = variant_map("primary")
    rows = []
    for item in latest_jobs(ROOT / "results" / "primary.jsonl"):
        result = item.get("result", {})
        if not result.get("ok"):
            rows.append(
                {
                    "job_id": item["job_id"],
                    "fixture_id": item["fixture_id"],
                    "split": item["split"],
                    "variant": mapping[item["job_id"]],
                    "repetition": item["repetition"],
                    "generation_ok": False,
                    "generation_error": result,
                }
            )
            continue
        score = score_output(
            fixtures[item["fixture_id"]],
            result["summary"],
            item["files_before"],
            item["files_after"],
        )
        rows.append(
            {
                "job_id": item["job_id"],
                "fixture_id": item["fixture_id"],
                "split": item["split"],
                "variant": mapping[item["job_id"]],
                "repetition": item["repetition"],
                "generation_ok": True,
                "usage": result.get("usage", {}),
                "elapsed_seconds": result.get("elapsed_seconds"),
                "num_turns": result.get("num_turns"),
                "score": score,
            }
        )
    return rows


def score_presave() -> list[dict]:
    fixtures = load_fixture_map()
    mapping = variant_map("presave")
    rows = []
    for item in latest_jobs(ROOT / "results" / "presave.jsonl"):
        previous_files = item["initial_files"]
        pass_scores = []
        for pass_item in item["passes"]:
            result = pass_item["result"]
            if not result.get("ok"):
                pass_scores.append({"generation_ok": False, "generation_error": result})
                continue
            score = score_output(
                fixtures[item["fixture_id"]],
                result["summary"],
                pass_item["files_before"],
                pass_item["files_after"],
            )
            pass_scores.append(
                {
                    "generation_ok": True,
                    "score": score,
                    "files_stable_from_previous_pass": (
                        pass_item["files_after"] == previous_files
                        if pass_item["pass"] == 2
                        else None
                    ),
                }
            )
            previous_files = pass_item["files_after"]
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
    fixtures = load_fixture_map()
    mapping = variant_map("recompact")
    rows = []
    for item in latest_jobs(ROOT / "results" / "recompact.jsonl"):
        generation_scores = []
        before = fixtures[item["fixture_id"]].get("seeded_files", {})
        for generation in item["generations"]:
            result = generation["result"]
            if not result.get("ok"):
                generation_scores.append(
                    {
                        "generation": generation["generation"],
                        "generation_ok": False,
                        "generation_error": result,
                    }
                )
                continue
            score = score_output(
                fixtures[item["fixture_id"]],
                result["summary"],
                before,
                generation["files_after"],
            )
            generation_scores.append(
                {
                    "generation": generation["generation"],
                    "generation_ok": True,
                    "usage": result.get("usage", {}),
                    "score": score,
                }
            )
            before = generation["files_after"]
        rows.append(
            {
                "job_id": item["job_id"],
                "fixture_id": item["fixture_id"],
                "variant": mapping[item["job_id"]],
                "generations": generation_scores,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["primary", "presave", "recompact"])
    args = parser.parse_args()
    scorers = {
        "primary": score_primary,
        "presave": score_presave,
        "recompact": score_recompact,
    }
    rows = scorers[args.mode]()
    output = ROOT / "results" / f"{args.mode}-scores.json"
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"mode": args.mode, "rows": len(rows), "output": str(output)}))


if __name__ == "__main__":
    main()
