import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
VARIANTS = ("orchestra_current", "kesha_full", "concise")
BOOTSTRAP_SEED = 10620260731
BOOTSTRAP_N = 10_000


def load_json(path: Path):
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def latest(path: Path) -> dict[str, dict]:
    return {item["job_id"]: item for item in load_jsonl(path)}


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def cluster_bootstrap(
    rows: list[dict],
    numerator: str,
    denominator: str,
    rng: random.Random,
) -> tuple[float, list[float]]:
    by_fixture = defaultdict(lambda: [0, 0])
    for row in rows:
        score = row["score"]
        by_fixture[row["fixture_id"]][0] += score[numerator]
        by_fixture[row["fixture_id"]][1] += score[denominator]
    fixtures = sorted(by_fixture)
    point = sum(value[0] for value in by_fixture.values()) / sum(
        value[1] for value in by_fixture.values()
    )
    samples = []
    for _ in range(BOOTSTRAP_N):
        selected = [rng.choice(fixtures) for _ in fixtures]
        hits = sum(by_fixture[fixture][0] for fixture in selected)
        total = sum(by_fixture[fixture][1] for fixture in selected)
        samples.append(hits / total)
    return point, samples


def interval(samples: list[float]) -> list[float]:
    return [percentile(samples, 0.025), percentile(samples, 0.975)]


def paired_cluster_difference(
    left_rows: list[dict],
    right_rows: list[dict],
    numerator: str,
    denominator: str,
    rng: random.Random,
) -> list[float]:
    def aggregate(rows: list[dict]) -> dict[str, list[int]]:
        values = defaultdict(lambda: [0, 0])
        for row in rows:
            values[row["fixture_id"]][0] += row["score"][numerator]
            values[row["fixture_id"]][1] += row["score"][denominator]
        return values

    left = aggregate(left_rows)
    right = aggregate(right_rows)
    fixtures = sorted(left)
    assert fixtures == sorted(right)
    samples = []
    for _ in range(BOOTSTRAP_N):
        selected = [rng.choice(fixtures) for _ in fixtures]
        left_rate = sum(left[item][0] for item in selected) / sum(
            left[item][1] for item in selected
        )
        right_rate = sum(right[item][0] for item in selected) / sum(
            right[item][1] for item in selected
        )
        samples.append(left_rate - right_rate)
    return samples


def kappa(left: list[bool], right: list[bool]) -> dict:
    assert len(left) == len(right)
    n = len(left)
    agreement = sum(a == b for a, b in zip(left, right)) / n
    left_rate = sum(left) / n
    right_rate = sum(right) / n
    expected = left_rate * right_rate + (1 - left_rate) * (1 - right_rate)
    value = None if expected == 1 else (agreement - expected) / (1 - expected)
    return {
        "n": n,
        "agreement": agreement,
        "kappa": value,
        "left_positive_rate": left_rate,
        "right_positive_rate": right_rate,
    }


def zero_event_upper(n: int, alpha: float = 0.05) -> float:
    return 1 - (alpha / 2) ** (1 / n)


def judge_ratings(name: str) -> dict[str, dict]:
    candidate_map = load_json(RESULTS / f"judge-{name}-blinding-map.json")
    rows = latest(RESULTS / f"judge-{name}.jsonl")
    ratings = {}
    for row in rows.values():
        for candidate in row["result"]["judgment"]["candidates"]:
            primary_job = candidate_map[candidate["candidate_id"]]["primary_job_id"]
            ratings[primary_job] = candidate
    return ratings


def model_cost(result: dict) -> float:
    return sum(
        float(item.get("costUSD", 0))
        for item in result.get("model_usage", {}).values()
    )


def failed_primary_cost() -> float:
    total = 0.0
    for item in load_jsonl(RESULTS / "primary.jsonl"):
        result = item.get("result", {})
        if result.get("ok") or not result.get("stdout"):
            continue
        try:
            total += float(json.loads(result["stdout"]).get("total_cost_usd", 0))
        except json.JSONDecodeError:
            pass
    return total


def main() -> None:
    scores = load_json(RESULTS / "primary-scores.json")
    primary = latest(RESULTS / "primary.jsonl")
    mapping = load_json(RESULTS / "primary-blinding-map.json")
    score_by_job = {row["job_id"]: row for row in scores}
    assert len(score_by_job) == len(scores), "duplicate job_id in primary scores"
    assert set(score_by_job) == set(primary), "primary scores do not match latest jobs"
    claude = judge_ratings("claude")
    codex = judge_ratings("codex")
    rng = random.Random(BOOTSTRAP_SEED)

    analysis = {
        "method": {
            "primary_generations": len(scores),
            "holdout_generations": sum(row["split"] == "holdout" for row in scores),
            "dev_generations": sum(row["split"] == "dev" for row in scores),
            "bootstrap_clusters": 7,
            "bootstrap_resamples": BOOTSTRAP_N,
            "bootstrap_seed": BOOTSTRAP_SEED,
        },
        "holdout": {},
        "dev": {},
    }

    for split in ("holdout", "dev"):
        target = analysis[split]
        for variant in VARIANTS:
            rows = [
                row
                for row in scores
                if row["split"] == split and row["variant"] == variant
            ]
            split_rng = rng if split == "holdout" else random.Random(BOOTSTRAP_SEED + 10)
            exact, exact_samples = cluster_bootstrap(
                rows, "exact_hits", "exact_total", split_rng
            )
            recent, recent_samples = cluster_bootstrap(
                rows, "recent_hits", "recent_total", split_rng
            )
            pending, pending_samples = cluster_bootstrap(
                rows, "pending_hits", "pending_total", split_rng
            )
            bytes_values = [row["score"]["summary_utf8_bytes"] for row in rows]
            output_tokens = [
                row.get("usage", {}).get("output_tokens", 0) for row in rows
            ]
            clean_passes = sum(
                row["score"]["exact_hits"] == row["score"]["exact_total"]
                and row["score"]["recent_hits"] == row["score"]["recent_total"]
                and row["score"]["pending_hits"] == row["score"]["pending_total"]
                and not row["score"]["secret_leaks"]
                and row["score"]["redundant_noise_lines"] <= 2
                for row in rows
            )
            secret_exposed = [
                row
                for row in rows
                if load_json(ROOT / "fixtures.json")[
                    next(
                        index
                        for index, fixture in enumerate(load_json(ROOT / "fixtures.json"))
                        if fixture["id"] == row["fixture_id"]
                    )
                ]["fake_secrets"]
            ]
            target[variant] = {
                "n": len(rows),
                "exact_recall": exact,
                "exact_recall_cluster_bootstrap_95": interval(exact_samples),
                "recent_recall": recent,
                "recent_recall_cluster_bootstrap_95": interval(recent_samples),
                "pending_recall": pending,
                "pending_recall_cluster_bootstrap_95": interval(pending_samples),
                "median_summary_utf8_bytes": statistics.median(bytes_values),
                "median_whole_turn_output_tokens": statistics.median(output_tokens),
                "deterministic_clean_passes": clean_passes,
                "secret_exposed_runs": len(secret_exposed),
                "secret_leaks": sum(
                    len(row["score"]["secret_leaks"]) for row in secret_exposed
                ),
                "zero_leak_two_sided_cp95_upper": (
                    zero_event_upper(len(secret_exposed)) if secret_exposed else None
                ),
            }

    differences = {}
    for left, right in (
        ("kesha_full", "orchestra_current"),
        ("concise", "orchestra_current"),
        ("concise", "kesha_full"),
    ):
        item = {}
        for metric in ("exact", "recent", "pending"):
            left_rows = [
                row
                for row in scores
                if row["split"] == "holdout" and row["variant"] == left
            ]
            right_rows = [
                row
                for row in scores
                if row["split"] == "holdout" and row["variant"] == right
            ]
            samples = paired_cluster_difference(
                left_rows,
                right_rows,
                f"{metric}_hits",
                f"{metric}_total",
                random.Random(
                    BOOTSTRAP_SEED
                    + sum(ord(char) for char in f"{left}|{right}|{metric}")
                ),
            )
            point = (
                analysis["holdout"][left][f"{metric}_recall"]
                - analysis["holdout"][right][f"{metric}_recall"]
            )
            item[metric] = {"difference": point, "paired_cluster_bootstrap_95": interval(samples)}
        differences[f"{left}_minus_{right}"] = item
    analysis["holdout_differences"] = differences
    analysis["primary_file_writes"] = {}
    for variant in VARIANTS:
        rows = [row for row in scores if row["variant"] == variant]
        analysis["primary_file_writes"][variant] = {
            "n_outputs": len(rows),
            "outputs_with_changed_files": sum(
                bool(row["score"]["changed_files"]) for row in rows
            ),
            "total_changed_files": sum(
                len(row["score"]["changed_files"]) for row in rows
            ),
        }

    fixtures = {fixture["id"]: fixture for fixture in load_json(ROOT / "fixtures.json")}
    missing = defaultdict(lambda: defaultdict(Counter))
    for row in scores:
        for category, anchors in row["score"]["exact"].items():
            for anchor, present in anchors.items():
                if not present:
                    missing[row["split"]][row["variant"]][category] += 1
    analysis["missing_anchor_taxonomy"] = {
        split: {variant: dict(categories) for variant, categories in variants.items()}
        for split, variants in missing.items()
    }

    judge_summary = {"holdout": {}, "dev": {}}
    for split in ("holdout", "dev"):
        for variant in VARIANTS:
            jobs = [
                job_id
                for job_id, item in primary.items()
                if item["split"] == split and mapping[job_id]["variant"] == variant
            ]
            anchor_total = sum(len(fixtures[primary[job]["fixture_id"]]["semantic_anchors"]) for job in jobs)
            claude_hits = sum(
                sum(claude[job]["semantic_anchors"].values()) for job in jobs
            )
            codex_hits = sum(
                sum(codex[job]["semantic_anchors"].values()) for job in jobs
            )
            judge_summary[split][variant] = {
                "n_outputs": len(jobs),
                "semantic_anchor_total": anchor_total,
                "sonnet_semantic_recall": claude_hits / anchor_total,
                "sol_semantic_recall": codex_hits / anchor_total,
                "sonnet_outputs_with_unsupported_claim": sum(
                    bool(claude[job]["unsupported_claims"]) for job in jobs
                ),
                "sol_outputs_with_unsupported_claim": sum(
                    bool(codex[job]["unsupported_claims"]) for job in jobs
                ),
                "both_raters_flag_unsupported": sum(
                    bool(claude[job]["unsupported_claims"])
                    and bool(codex[job]["unsupported_claims"])
                    for job in jobs
                ),
                "sonnet_unsupported_claim_count": sum(
                    len(claude[job]["unsupported_claims"]) for job in jobs
                ),
                "sol_unsupported_claim_count": sum(
                    len(codex[job]["unsupported_claims"]) for job in jobs
                ),
                "sonnet_no_dump": sum(claude[job]["no_transcript_dump"] for job in jobs),
                "sol_no_dump": sum(codex[job]["no_transcript_dump"] for job in jobs),
            }
    analysis["semantic_judges"] = judge_summary

    for split in ("all", "holdout"):
        jobs = [
            job_id
            for job_id, item in primary.items()
            if split == "all" or item["split"] == split
        ]
        semantic_left = []
        semantic_right = []
        for job in jobs:
            for anchor in fixtures[primary[job]["fixture_id"]]["semantic_anchors"]:
                semantic_left.append(claude[job]["semantic_anchors"][anchor["id"]])
                semantic_right.append(codex[job]["semantic_anchors"][anchor["id"]])
        unsupported_left = [bool(claude[job]["unsupported_claims"]) for job in jobs]
        unsupported_right = [bool(codex[job]["unsupported_claims"]) for job in jobs]
        no_dump_left = [claude[job]["no_transcript_dump"] for job in jobs]
        no_dump_right = [codex[job]["no_transcript_dump"] for job in jobs]
        analysis.setdefault("inter_rater", {})[split] = {
            "semantic_anchor": kappa(semantic_left, semantic_right),
            "unsupported_any": kappa(unsupported_left, unsupported_right),
            "no_transcript_dump": kappa(no_dump_left, no_dump_right),
        }

    presave = load_json(RESULTS / "presave-scores.json")
    clear_fixture = [
        row for row in presave if row["fixture_id"] == "holdout-presave-idempotent"
    ]
    analysis["presave"] = {}
    for variant in ("kesha_full", "kesha_handoff_only"):
        rows = [row for row in clear_fixture if row["variant"] == variant]
        analysis["presave"][variant] = {
            "n": len(rows),
            "first_pass_expected_file_state": sum(
                row["passes"][0]["score"]["file_state"]["passed"] for row in rows
            ),
            "second_pass_expected_file_state": sum(
                row["passes"][1]["score"]["file_state"]["passed"] for row in rows
            ),
            "second_pass_zero_diff": sum(
                row["passes"][1]["files_stable_from_previous_pass"] for row in rows
            ),
            "secret_leaks": sum(
                len(item["score"]["secret_leaks"])
                for row in rows
                for item in row["passes"]
            ),
        }
    analysis["presave"]["excluded_ambiguous_fixture"] = {
        "fixture_id": "holdout-preference-secret",
        "reason": "The fixture expected CLAUDE.md to remain byte-identical while its transcript declared a durable operating preference; Kesha's prompt explicitly allows stable operating rules in CLAUDE.md.",
    }
    matched_first_pass = {}
    for variant in ("kesha_full", "kesha_handoff_only"):
        rows = [row for row in presave if row["variant"] == variant]
        scores = [row["passes"][0]["score"] for row in rows]
        matched_first_pass[variant] = {
            "n_outputs": len(scores),
            "n_fixture_clusters": len({row["fixture_id"] for row in rows}),
            "exact_hits": sum(score["exact_hits"] for score in scores),
            "exact_total": sum(score["exact_total"] for score in scores),
            "exact_recall": sum(score["exact_hits"] for score in scores)
            / sum(score["exact_total"] for score in scores),
            "recent_hits": sum(score["recent_hits"] for score in scores),
            "recent_total": sum(score["recent_total"] for score in scores),
            "pending_hits": sum(score["pending_hits"] for score in scores),
            "pending_total": sum(score["pending_total"] for score in scores),
            "median_summary_utf8_bytes": statistics.median(
                score["summary_utf8_bytes"] for score in scores
            ),
        }
    matched_first_pass["kesha_full_minus_handoff_only_exact"] = (
        matched_first_pass["kesha_full"]["exact_recall"]
        - matched_first_pass["kesha_handoff_only"]["exact_recall"]
    )
    analysis["presave"]["matched_first_pass_handoff"] = matched_first_pass

    recompact = load_json(RESULTS / "recompact-scores.json")
    analysis["recompaction"] = {}
    for variant in VARIANTS:
        rows = [row for row in recompact if row["variant"] == variant]
        generations = {}
        for generation in (1, 2, 3):
            items = [
                next(item for item in row["generations"] if item["generation"] == generation)
                for row in rows
            ]
            generations[str(generation)] = {
                "n_fixture_chains": len(items),
                "exact_hits": sum(item["score"]["exact_hits"] for item in items),
                "exact_total": sum(item["score"]["exact_total"] for item in items),
                "exact_recall": sum(item["score"]["exact_hits"] for item in items)
                / sum(item["score"]["exact_total"] for item in items),
                "recent_hits": sum(item["score"]["recent_hits"] for item in items),
                "recent_total": sum(item["score"]["recent_total"] for item in items),
                "secret_leaks": sum(len(item["score"]["secret_leaks"]) for item in items),
                "summary_utf8_bytes": [item["score"]["summary_utf8_bytes"] for item in items],
            }
        analysis["recompaction"][variant] = generations

    all_primary_records = load_jsonl(RESULTS / "primary.jsonl")
    primary_success_cost = sum(
        model_cost(item["result"])
        for item in all_primary_records
        if item.get("result", {}).get("ok")
    )
    presave_cost = sum(
        model_cost(item["result"])
        for row in load_jsonl(RESULTS / "presave.jsonl")
        for item in row["passes"]
        if item["result"].get("ok")
    )
    recompact_cost = sum(
        model_cost(item["result"])
        for row in load_jsonl(RESULTS / "recompact.jsonl")
        for item in row["generations"]
        if item["result"].get("ok")
    )
    sonnet_cost = sum(
        model_cost(row["result"])
        for row in load_jsonl(RESULTS / "judge-claude.jsonl")
        if row["result"].get("ok")
    )
    invalid_sonnet_cost = sum(
        model_cost(row["result"])
        for row in load_jsonl(
            RESULTS
            / "failed-attempts/judges-missing-file-evidence-20260801/judge-claude.jsonl"
        )
        if row["result"].get("ok")
    )
    corrected_pilot_cost = model_cost(
        load_json(RESULTS / "pilot-corrected-judge/result.json")
    )
    generator_pilot_cost = model_cost(load_json(RESULTS / "pilot.json")["result"])
    accepted_cost = (
        primary_success_cost
        + failed_primary_cost()
        + presave_cost
        + recompact_cost
        + sonnet_cost
    )
    analysis["cost_usd_api_equivalent"] = {
        "primary_successful_calls": primary_success_cost,
        "primary_failed_529_calls": failed_primary_cost(),
        "presave_calls": presave_cost,
        "recompact_calls": recompact_cost,
        "sonnet_judge_calls": sonnet_cost,
        "accepted_evidence_total": accepted_cost,
        "invalid_sonnet_judge_missing_ledger": invalid_sonnet_cost,
        "excluded_corrected_sonnet_pilot": corrected_pilot_cost,
        "excluded_generator_pilot": generator_pilot_cost,
        "all_claude_calls_including_invalid_and_pilots": (
            accepted_cost
            + invalid_sonnet_cost
            + corrected_pilot_cost
            + generator_pilot_cost
        ),
        "codex_judge": None,
        "note": "Subscription workload; USD fields are provider/API-equivalent accounting, not cash charged for this experiment.",
    }

    (RESULTS / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({"output": str(RESULTS / "analysis.json"), "holdout": analysis["holdout"], "inter_rater": analysis["inter_rater"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
