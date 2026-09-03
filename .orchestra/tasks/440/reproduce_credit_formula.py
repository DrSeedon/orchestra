#!/usr/bin/env python3
"""Reproduce #440 credit-formula checks from a read-only Orchestra database."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from fractions import Fraction
import json
import math
from pathlib import Path
import sqlite3


DEFAULT_START = "2026-07-26T04:48:33.960178+00:00"
DEFAULT_CUTOFF = "2026-09-02T03:49:33.877143+00:00"
FIVE_HOUR_CREDITS = 11_000_000
RATES = {
    "haiku": (Fraction(2, 15), Fraction(10, 15)),
    "sonnet": (Fraction(6, 15), Fraction(30, 15)),
    "opus": (Fraction(10, 15), Fraction(50, 15)),
}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _model_class(model: str) -> str | None:
    lowered = model.lower()
    return next((name for name in RATES if name in lowered), None)


def _simplest_fraction_in_interval(low: Fraction, high: Fraction) -> Fraction:
    """Return the lowest-complexity positive rational in a closed interval."""
    if not 0 <= low <= high:
        raise ValueError("expected 0 <= low <= high")
    low_floor = low.numerator // low.denominator
    high_floor = high.numerator // high.denominator
    if low_floor < high_floor:
        return Fraction(low_floor + 1, 1)
    if low == low_floor:
        return Fraction(low_floor, 1)
    return Fraction(low_floor, 1) + 1 / _simplest_fraction_in_interval(
        1 / (high - high_floor), 1 / (low - low_floor)
    )


def recover_fraction(value: float) -> Fraction:
    """Recover the simplest rational in the IEEE-754 rounding bucket of value."""
    exact = Fraction.from_float(value)
    previous = Fraction.from_float(math.nextafter(value, -math.inf))
    following = Fraction.from_float(math.nextafter(value, math.inf))
    return _simplest_fraction_in_interval((previous + exact) / 2, (exact + following) / 2)


def _credits(row: sqlite3.Row, include_write: bool, *, all_opus: bool = False) -> dict:
    model_class = _model_class(str(row["model"]))
    if model_class is None:
        raise ValueError(f"unknown Claude model: {row['model']}")
    rate_in, rate_out = RATES["opus" if all_opus else model_class]
    fresh = int(row["input_tokens"]) * rate_in
    write = int(row["cache_create_tokens"]) * rate_in if include_write else Fraction(0)
    output = int(row["output_tokens"]) * rate_out
    return {
        "rounded": math.ceil(fresh + write + output),
        "fresh": fresh,
        "write": write,
        "output": output,
        "model_class": model_class,
    }


def _summarize(pairs: list[dict]) -> dict:
    result = {
        "pairs": len(pairs),
        "turn_rows": sum(pair["turn_rows"] for pair in pairs),
        "observed_pp_sum": sum(pair["observed_pp"] for pair in pairs),
    }
    for arm in ("with_write", "without_write"):
        if not pairs:
            result[arm] = {"matches": 0, "share": None, "predicted_pp_sum": 0.0, "mae_pp": None}
            continue
        matches = sum(abs(pair[arm]["predicted_pp"] - pair["observed_pp"]) <= 1.0 for pair in pairs)
        result[arm] = {
            "matches": matches,
            "share": matches / len(pairs),
            "predicted_pp_sum": sum(pair[arm]["predicted_pp"] for pair in pairs),
            "mae_pp": sum(abs(pair[arm]["predicted_pp"] - pair["observed_pp"]) for pair in pairs) / len(pairs),
        }
    if pairs:
        paired = Counter()
        for pair in pairs:
            write_hit = abs(pair["with_write"]["predicted_pp"] - pair["observed_pp"]) <= 1.0
            no_write_hit = abs(pair["without_write"]["predicted_pp"] - pair["observed_pp"]) <= 1.0
            paired[
                "both" if write_hit and no_write_hit
                else "with_write_only" if write_hit
                else "without_write_only" if no_write_hit
                else "neither"
            ] += 1
        result["paired_match_outcomes"] = dict(paired)
    return result


def analyze(db_path: Path, start: str, cutoff: str) -> dict:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    sessions_before = connection.execute("SELECT count(*) FROM sessions").fetchone()[0]
    snapshots = connection.execute(
        """SELECT ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                  seven_day_resets_at, provider_usage
           FROM usage_snapshots
           WHERE ts >= ? AND ts <= ? ORDER BY ts""",
        (start, cutoff),
    ).fetchall()
    turns = connection.execute(
        """SELECT ts, model, input_tokens, output_tokens, cache_read_tokens,
                  cache_create_tokens
           FROM turn_usage
           WHERE runtime = 'claude' AND ts > ? AND ts <= ? ORDER BY ts""",
        (start, cutoff),
    ).fetchall()
    sessions_after = connection.execute("SELECT count(*) FROM sessions").fetchone()[0]
    connection.close()

    pairs: list[dict] = []
    rejected = Counter()
    turn_index = 0
    model_rows = Counter()
    model_tokens: dict[str, Counter] = defaultdict(Counter)
    unknown_models = Counter()

    for left, right in zip(snapshots, snapshots[1:]):
        left_time, right_time = _dt(left["ts"]), _dt(right["ts"])
        while turn_index < len(turns) and _dt(turns[turn_index]["ts"]) <= left_time:
            turn_index += 1
        end_index = turn_index
        while end_index < len(turns) and _dt(turns[end_index]["ts"]) <= right_time:
            end_index += 1
        interval_turns = turns[turn_index:end_index]
        turn_index = end_index

        if left["five_hour_pct"] is None or right["five_hour_pct"] is None:
            rejected["missing_counter"] += 1
            continue
        if (right_time - left_time).total_seconds() > 900:
            rejected["gap_over_900s"] += 1
            continue
        if not left["five_hour_resets_at"]:
            rejected["missing_reset"] += 1
            continue
        if right_time >= _dt(left["five_hour_resets_at"]):
            rejected["crosses_declared_reset"] += 1
            continue
        observed_pp = float(right["five_hour_pct"]) - float(left["five_hour_pct"])
        if observed_pp < 0:
            rejected["counter_decrease"] += 1
            continue

        arm_totals = {
            "with_write": {"credits": 0, "fresh": Fraction(0), "write": Fraction(0), "output": Fraction(0)},
            "without_write": {"credits": 0, "fresh": Fraction(0), "write": Fraction(0), "output": Fraction(0)},
        }
        all_opus_credits = 0
        pair_models = Counter()
        invalid = False
        for turn in interval_turns:
            model_class = _model_class(str(turn["model"]))
            if model_class is None:
                unknown_models[str(turn["model"])] += 1
                invalid = True
                continue
            pair_models[model_class] += 1
            model_rows[model_class] += 1
            for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_create_tokens"):
                model_tokens[model_class][key] += int(turn[key])
            for arm, include_write in (("with_write", True), ("without_write", False)):
                value = _credits(turn, include_write)
                arm_totals[arm]["credits"] += value["rounded"]
                for component in ("fresh", "write", "output"):
                    arm_totals[arm][component] += value[component]
            all_opus_credits += _credits(turn, True, all_opus=True)["rounded"]
        if invalid:
            rejected["unknown_model"] += 1
            continue

        pair = {
            "left_ts": left["ts"],
            "right_ts": right["ts"],
            "elapsed_seconds": (right_time - left_time).total_seconds(),
            "observed_pp": observed_pp,
            "right_pct": float(right["five_hour_pct"]),
            "turn_rows": len(interval_turns),
            "models": dict(pair_models),
            "all_opus_with_write_credits": all_opus_credits,
        }
        for arm, totals in arm_totals.items():
            pair[arm] = {
                "credits": totals["credits"],
                "predicted_pp": 100 * totals["credits"] / FIVE_HOUR_CREDITS,
                "raw_component_credits": {
                    key: float(totals[key]) for key in ("fresh", "write", "output")
                },
            }
        pairs.append(pair)

    groups = {
        "all_eligible": pairs,
        "active_primary": [pair for pair in pairs if pair["turn_rows"] > 0],
        "positive_observed": [pair for pair in pairs if pair["observed_pp"] > 0],
        "observed_at_least_2pp": [pair for pair in pairs if pair["observed_pp"] >= 2],
        "active_unsaturated_postfreeze": [
            pair for pair in pairs if pair["turn_rows"] > 0 and pair["right_pct"] < 100
        ],
        "observed_at_least_2pp_unsaturated_postfreeze": [
            pair for pair in pairs if pair["observed_pp"] >= 2 and pair["right_pct"] < 100
        ],
    }
    active = groups["active_primary"]
    proper = sum(pair["with_write"]["credits"] for pair in active)
    all_opus = sum(pair["all_opus_with_write_credits"] for pair in active)
    components = {
        component: sum(pair["with_write"]["raw_component_credits"][component] for pair in active)
        for component in ("fresh", "write", "output")
    }

    return {
        "contract": {
            "start": start,
            "cutoff": cutoff,
            "snapshot_order": "ts ASC",
            "pair_filter": "adjacent; both 5h values; gap<=900s; right<left reset; delta>=0",
            "turn_filter": "runtime='claude' and left.ts < ts <= right.ts",
            "rounding_match": "abs(predicted_pp-observed_pp)<=1.0",
            "five_hour_credit_limit": FIVE_HOUR_CREDITS,
        },
        "source": {
            "db": str(db_path),
            "sessions_before": sessions_before,
            "sessions_after": sessions_after,
            "snapshot_rows": len(snapshots),
            "turn_rows": len(turns),
            "snapshot_min_ts": snapshots[0]["ts"] if snapshots else None,
            "snapshot_max_ts": snapshots[-1]["ts"] if snapshots else None,
            "turn_min_ts": turns[0]["ts"] if turns else None,
            "turn_max_ts": turns[-1]["ts"] if turns else None,
        },
        "rejected_pairs": dict(rejected),
        "groups": {name: _summarize(group) for name, group in groups.items()},
        "active_model_rows": dict(model_rows),
        "active_model_tokens": {name: dict(values) for name, values in model_tokens.items()},
        "unknown_models": dict(unknown_models),
        "active_model_mix_counterfactual": {
            "proper_rate_credits": proper,
            "all_opus_rate_credits": all_opus,
            "all_opus_minus_proper": all_opus - proper,
            "relative_delta": (all_opus - proper) / proper if proper else None,
        },
        "active_raw_credit_components": components,
        "active_quiet_counter_movement": {
            "zero_turn_pairs_with_positive_delta": sum(
                pair["turn_rows"] == 0 and pair["observed_pp"] > 0 for pair in pairs
            ),
            "their_observed_pp_sum": sum(
                pair["observed_pp"] for pair in pairs
                if pair["turn_rows"] == 0 and pair["observed_pp"] > 0
            ),
        },
        "largest_active_misses": sorted(
            (
                {
                    "left_ts": pair["left_ts"],
                    "right_ts": pair["right_ts"],
                    "turn_rows": pair["turn_rows"],
                    "observed_pp": pair["observed_pp"],
                    "with_write_predicted_pp": pair["with_write"]["predicted_pp"],
                    "without_write_predicted_pp": pair["without_write"]["predicted_pp"],
                }
                for pair in active
            ),
            key=lambda item: abs(item["with_write_predicted_pp"] - item["observed_pp"]),
            reverse=True,
        )[:20],
    }


def _self_test() -> None:
    assert recover_fraction(0.16327272727272726) == Fraction(449, 2750)
    assert math.lcm(2750, 75000, 44000) == 3_300_000
    assert _model_class("claude-opus-5[1m]") == "opus"
    assert _model_class("claude-sonnet-5") == "sonnet"
    assert _model_class("claude-haiku-4-5") == "haiku"
    print("SELF_TEST_OK fraction=449/2750 lcm_control=3300000")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    if args.db is None or args.output is None:
        parser.error("--db and --output are required unless --self-test is used")
    result = analyze(args.db, args.start, args.cutoff)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    primary = result["groups"]["active_primary"]
    print(json.dumps({
        "output": str(args.output),
        "sessions_before": result["source"]["sessions_before"],
        "sessions_after": result["source"]["sessions_after"],
        "primary_pairs": primary["pairs"],
        "with_write_matches": primary["with_write"]["matches"],
        "without_write_matches": primary["without_write"]["matches"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
