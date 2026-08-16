#!/usr/bin/env python3
"""Deterministic, time-causal replay and evidence evaluation for quota telemetry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


OUTPUT_SCHEMA_VERSION = 2
_MIN_STABLE_WINDOWS = 3
_MIN_COVERAGE_PCT = 90.0
_MIN_BLOCKS = 20
_MIN_ESS = 20.0
_MIN_SETTLED_OUTCOMES = 20
_MIN_Q95_COVERAGE = 0.95
_MIN_Q95_LOWER_BOUND = 0.80
_GAP_SECONDS = 900.0
_MISSING = object()

_SERIES_BUCKETS = {
    "claude.five_hour": "anthropic:five_hour",
    "claude.seven_day": "anthropic:seven_day",
    "codex.primary": "codex:primary",
    "codex.spark": "codex_spark:primary",
    "grok.weekly": "grok:primary",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _deduplicate(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        copied = dict(item)
        marker = _canonical_json(copied)
        if marker not in seen:
            seen.add(marker)
            result.append(copied)
    return result


def _nearest_rank_q95(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _failure_reason(field: str, scope: str = "") -> str:
    return f"missing_field:{field}{':' + scope if scope else ''}"


def _required(container: Mapping[str, Any], field: str, scope: str, reasons: list[str]) -> Any:
    value = container.get(field, _MISSING)
    if value is _MISSING:
        reasons.append(_failure_reason(field, scope))
    return value


def _at_least(value: Any, minimum: float) -> bool:
    number = _number(value)
    return number is not None and number >= minimum


def _is_zero(value: Any) -> bool:
    return _number(value) == 0


def _constraint_failures(bucket: str, raw: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []

    stable = _required(raw, "stable_same_regime_windows", bucket, reasons)
    if stable is not _MISSING and not _at_least(stable, _MIN_STABLE_WINDOWS):
        reasons.append(f"insufficient_stable_same_regime_windows:{bucket}")

    coverage = _required(raw, "telemetry_coverage_pct_by_window", bucket, reasons)
    if coverage is not _MISSING:
        stable_count = _number(stable)
        valid_coverage = (
            isinstance(coverage, list)
            and bool(coverage)
            and stable_count is not None
            and len(coverage) >= stable_count
            and all(_at_least(item, _MIN_COVERAGE_PCT) for item in coverage)
        )
        if not valid_coverage:
            reasons.append(f"insufficient_telemetry_coverage:{bucket}")

    threshold_fields = (
        ("non_overlapping_blocks", _MIN_BLOCKS, "insufficient_non_overlapping_blocks"),
        ("effective_sample_size", _MIN_ESS, "insufficient_effective_sample_size"),
    )
    for field, threshold, reason in threshold_fields:
        value = _required(raw, field, bucket, reasons)
        if value is not _MISSING and not _at_least(value, threshold):
            reasons.append(f"{reason}:{bucket}")

    zero_fields = (
        ("unsafe_allow_count", "unsafe_allow_observed"),
        ("qualified_window_drift_count", "qualified_window_has_drift"),
    )
    for field, reason in zero_fields:
        value = _required(raw, field, bucket, reasons)
        if value is not _MISSING and not _is_zero(value):
            reasons.append(f"{reason}:{bucket}")

    comparisons = (
        (
            "adaptive_early_exhaustion_hours",
            "static_early_exhaustion_hours",
            "worse_than_static_early_exhaustion",
        ),
        (
            "adaptive_median_unused_headroom",
            "static_median_unused_headroom",
            "worse_than_static_unused_headroom",
        ),
        ("adaptive_false_holds", "static_false_holds", "worse_than_static_false_holds"),
    )
    for adaptive_field, static_field, reason in comparisons:
        adaptive = _required(raw, adaptive_field, bucket, reasons)
        static = _required(raw, static_field, bucket, reasons)
        if adaptive is _MISSING or static is _MISSING:
            continue
        adaptive_number = _number(adaptive)
        static_number = _number(static)
        if (
            adaptive_number is None
            or static_number is None
            or adaptive_number > static_number
        ):
            reasons.append(f"{reason}:{bucket}")
    return list(dict.fromkeys(reasons))


def _stratum_failures(name: str, raw: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    checks = (
        ("settled_usable_outcomes", _MIN_SETTLED_OUTCOMES, "insufficient_settled_outcomes"),
        ("q95_empirical_coverage", _MIN_Q95_COVERAGE, "q95_undercoverage"),
        ("q95_binomial_lower_95", _MIN_Q95_LOWER_BOUND, "q95_lower_bound"),
    )
    for field, threshold, reason in checks:
        value = _required(raw, field, name, reasons)
        number = _number(value)
        if (
            value is not _MISSING
            and (
                number is None
                or number < threshold
                or (field.startswith("q95_") and number > 1)
            )
        ):
            reasons.append(f"{reason}:{name}")
    return list(dict.fromkeys(reasons))


def evaluate_evidence_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed against all seven evidence criteria, scoped by named stratum."""
    if not isinstance(metrics, Mapping):
        return {"eligible": False, "eligible_strata": [], "reasons": ["invalid_metrics"]}

    reasons: list[str] = []
    global_ok = True
    prospective = _required(metrics, "prospective", "", reasons)
    if prospective is not True:
        if prospective is not _MISSING:
            reasons.append("not_prospective")
        global_ok = False

    corrupt = _required(metrics, "corrupt_authoritative_decision_count", "", reasons)
    if corrupt is not _MISSING and not _is_zero(corrupt):
        reasons.append("corrupt_authoritative_decision")
        global_ok = False
    elif corrupt is _MISSING:
        global_ok = False

    live_regime = _required(metrics, "live_regime_matches", "", reasons)
    if live_regime is not True:
        if live_regime is not _MISSING:
            reasons.append("live_regime_mismatch")
        global_ok = False

    enabled = _required(metrics, "enabled_strata", "", reasons)
    constraints = _required(metrics, "constraints", "", reasons)
    strata = _required(metrics, "strata", "", reasons)
    if (
        not isinstance(enabled, list)
        or not enabled
        or not all(isinstance(value, str) and value for value in enabled)
    ):
        if enabled is not _MISSING:
            reasons.append("no_enabled_strata")
        enabled = []
        global_ok = False
    if not isinstance(constraints, Mapping):
        constraints = {}
        global_ok = False
    if not isinstance(strata, Mapping):
        strata = {}
        global_ok = False

    constraint_results: dict[str, list[str]] = {}
    eligible_strata: list[str] = []
    for name in enabled:
        local: list[str] = []
        stratum = strata.get(name)
        if not isinstance(stratum, Mapping):
            local.append(f"missing_stratum:{name}")
        else:
            referenced = _required(stratum, "constraints", name, local)
            primary_bucket = name.split("/", 1)[0]
            if (
                not isinstance(referenced, list)
                or not referenced
                or not all(isinstance(bucket, str) and bucket for bucket in referenced)
            ):
                if referenced is not _MISSING:
                    local.append(f"invalid_constraints:{name}")
                referenced = []
            elif set(referenced) != {primary_bucket}:
                local.append(f"cross_bucket_evidence:{name}")

            for bucket in referenced:
                constraint = constraints.get(bucket)
                if not isinstance(constraint, Mapping):
                    local.append(f"missing_constraint:{bucket}")
                    continue
                if bucket not in constraint_results:
                    constraint_results[bucket] = _constraint_failures(bucket, constraint)
                local.extend(constraint_results[bucket])
            local.extend(_stratum_failures(name, stratum))

        local = list(dict.fromkeys(local))
        reasons.extend(local)
        if global_ok and not local:
            eligible_strata.append(name)

    reasons = list(dict.fromkeys(reasons))
    return {
        "eligible": global_ok and len(eligible_strata) == len(enabled),
        "eligible_strata": eligible_strata,
        "reasons": reasons,
    }


def _row_exclusion(row: Mapping[str, Any], previous: Mapping[str, Any] | None) -> str | None:
    utilization = _number(row.get("utilization"))
    quality = str(row.get("quality") or "").lower()
    if row.get("available") is False or "unavailable" in quality or utilization is None:
        return "provider_unavailable"
    if quality == "legacy_columns" and utilization == 0 and not row.get("resets_at"):
        return "ambiguous_legacy_double_zero"
    if (
        row.get("bucket") == "codex_spark:primary"
        and utilization == 0
        and previous is not None
        and _number(previous.get("utilization")) == 0
        and row.get("resets_at")
        and previous.get("resets_at")
        and row.get("resets_at") != previous.get("resets_at")
    ):
        return "sliding_zero_anchor"
    return None


def replay_observation_series(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Replay decisions in timestamp order using outcomes strictly earlier than each row."""
    indexed: list[tuple[datetime, int, dict[str, Any]]] = []
    exclusions: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            exclusions.append({"reason": "invalid_row", "input_index": index})
            continue
        row = dict(raw)
        observed_at = row.get("observed_at") or row.get("ts")
        parsed = _parse_time(observed_at)
        if parsed is None:
            exclusions.append({"reason": "invalid_timestamp", "input_index": index})
            continue
        row["observed_at"] = observed_at
        indexed.append((parsed, index, row))
    indexed.sort(key=lambda item: (item[0], item[1]))

    decisions: list[dict[str, Any]] = []
    splits: list[dict[str, Any]] = []
    history: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    previous_by_bucket: dict[str, tuple[datetime, dict[str, Any]]] = {}
    segment_by_bucket: dict[str, int] = defaultdict(int)
    pending_outcomes: list[
        tuple[datetime, tuple[str, str, int], float]
    ] = []

    for observed_time, input_index, row in indexed:
        ready = [item for item in pending_outcomes if item[0] < observed_time]
        pending_outcomes = [item for item in pending_outcomes if item[0] >= observed_time]
        for _available_at, history_key, actual_turn in ready:
            history[history_key].append(actual_turn)

        bucket = row.get("bucket") if isinstance(row.get("bucket"), str) else "unknown"
        row["bucket"] = bucket
        previous_entry = previous_by_bucket.get(bucket)
        previous = previous_entry[1] if previous_entry else None
        exclusion = _row_exclusion(row, previous)
        if exclusion:
            exclusions.append({
                "reason": exclusion,
                "input_index": input_index,
                "bucket": bucket,
                "observed_at": row["observed_at"],
            })
            previous_by_bucket[bucket] = (observed_time, row)
            continue

        split_reason: str | None = None
        if previous_entry:
            previous_time, previous = previous_entry
            gap_seconds = (observed_time - previous_time).total_seconds()
            if row.get("break_before") is True or gap_seconds > _GAP_SECONDS:
                split_reason = "gap_gt_900s"
            elif row.get("plan") != previous.get("plan"):
                split_reason = "plan_transition"
            elif row.get("regime_key") != previous.get("regime_key"):
                split_reason = "regime_change"
        if split_reason:
            segment_by_bucket[bucket] += 1
            splits.append({
                "reason": split_reason,
                "bucket": bucket,
                "at": row["observed_at"],
                "from_regime": previous.get("regime_key") if previous else None,
                "to_regime": row.get("regime_key"),
            })

        regime_key = str(row.get("regime_key") or row.get("plan") or "unknown")
        history_key = (bucket, regime_key, segment_by_bucket[bucket])
        prior_outcomes = history[history_key]
        q95 = _nearest_rank_q95(prior_outcomes)
        utilization = _number(row.get("utilization"))
        static_allow = utilization is not None and utilization < 95.0
        adaptive_allow = None if utilization is None or q95 is None else utilization + q95 <= 99.0
        decisions.append({
            "evaluated_at": row["observed_at"],
            "bucket": bucket,
            "regime_key": regime_key,
            "history_outcomes": len(prior_outcomes),
            "q95_next_turn_pp": q95,
            "observed_utilization": utilization,
            "static_would_allow": static_allow,
            "adaptive_would_allow": adaptive_allow,
            "reason": None if q95 is not None else "insufficient_prior_outcomes",
        })

        actual_turn = _number(row.get("actual_turn_pp"))
        if actual_turn is not None and actual_turn >= 0:
            outcome_observed_at = row.get("outcome_observed_at")
            available_at = (
                _parse_time(outcome_observed_at)
                if outcome_observed_at is not None
                else observed_time
            )
            if available_at is not None:
                pending_outcomes.append((available_at, history_key, actual_turn))
        previous_by_bucket[bucket] = (observed_time, row)

    return {
        "decisions": decisions,
        "regime_splits": _deduplicate(splits),
        "exclusions": _deduplicate(exclusions),
    }


def _timeline_rows(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    timeline = data.get("timeline_series")
    if not isinstance(timeline, Mapping):
        return []
    contour = "unknown"
    scope = data.get("scope")
    if isinstance(scope, Mapping) and isinstance(scope.get("contours"), list):
        canonical = next(
            (
                item
                for item in scope["contours"]
                if isinstance(item, Mapping)
                and "canonical" in str(item.get("status", ""))
            ),
            None,
        )
        if isinstance(canonical, Mapping):
            contour = str(canonical.get("id") or contour)

    rows: list[dict[str, Any]] = []
    for series_name, series in timeline.items():
        if not isinstance(series, list):
            continue
        bucket = _SERIES_BUCKETS.get(str(series_name), str(series_name).replace(".", ":"))
        for raw in series:
            if not isinstance(raw, Mapping):
                continue
            plan = raw.get("plan")
            rows.append({
                "observed_at": raw.get("ts"),
                "bucket": bucket,
                "utilization": raw.get("utilization"),
                "resets_at": raw.get("resets_at"),
                "plan": plan,
                "quality": raw.get("quality"),
                "break_before": raw.get("break_before", False),
                "regime_key": f"{contour}|{bucket}|{plan or 'unknown'}",
                "contour": contour,
            })
    return rows


def _real_metrics(data: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    minimum_time = datetime.min.replace(tzinfo=timezone.utc)
    for row in sorted(
        rows,
        key=lambda item: _parse_time(item.get("observed_at")) or minimum_time,
    ):
        by_bucket[row["bucket"]].append(row)
    constraints: dict[str, dict[str, Any]] = {}
    for bucket in sorted(by_bucket):
        constraints[bucket] = {
            "stable_same_regime_windows": 0,
            "telemetry_coverage_pct_by_window": [],
            "non_overlapping_blocks": 0,
            "effective_sample_size": 0,
            "unsafe_allow_count": 0,
            "qualified_window_drift_count": 0,
            "adaptive_early_exhaustion_hours": None,
            "static_early_exhaustion_hours": None,
            "adaptive_median_unused_headroom": None,
            "static_median_unused_headroom": None,
            "adaptive_false_holds": None,
            "static_false_holds": None,
        }
    return {
        "prospective": data.get("prospective") is True,
        "corrupt_authoritative_decision_count": 0,
        "live_regime_matches": data.get("live_regime_matches") is True,
        "enabled_strata": data.get("enabled_strata", []),
        "constraints": constraints,
        "strata": data.get("strata", {}),
    }


def _artifact_exclusions(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    exclusions: list[dict[str, Any]] = []
    sampling = data.get("sampling")
    quality = sampling.get("quality") if isinstance(sampling, Mapping) else None
    if isinstance(quality, Mapping):
        ambiguous = quality.get("ambiguous_legacy_double_zero_rows_excluded")
        if _number(ambiguous) and _number(ambiguous) > 0:
            exclusions.append({"reason": "ambiguous_legacy_double_zero", "rows": int(ambiguous)})
        unavailable = quality.get("normalized_unavailable_rows")
        if isinstance(unavailable, Mapping):
            for provider, count in sorted(unavailable.items()):
                if _number(count) and _number(count) > 0:
                    exclusions.append({
                        "reason": "provider_unavailable",
                        "provider": provider,
                        "rows": int(count),
                    })

    scope = data.get("scope")
    contours = scope.get("contours") if isinstance(scope, Mapping) else None
    if isinstance(contours, list) and len(contours) > 1:
        exclusions.append({
            "reason": "contour_boundary",
            "contours": sorted(
                str(item.get("id"))
                for item in contours
                if isinstance(item, Mapping) and item.get("id")
            ),
            "action": "kept_separate",
        })
    return exclusions


def replay_limits_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Replay a frozen schema-2 limits artifact into deterministic machine evidence."""
    if not isinstance(data, Mapping):
        raise ValueError("input must be a JSON object")
    schema_version = data.get("schema_version")
    if schema_version != 2:
        raise ValueError(f"unsupported input schema_version: {schema_version!r}")

    observation_series = data.get("observation_series")
    rows = (
        [dict(row) for row in observation_series if isinstance(row, Mapping)]
        if isinstance(observation_series, list)
        else _timeline_rows(data)
    )
    replay = replay_observation_series(rows)
    splits = list(replay["regime_splits"])
    for transition in data.get("plan_transitions", []):
        if isinstance(transition, Mapping):
            splits.append({
                "reason": "plan_transition",
                "bucket": "codex:primary",
                "at": transition.get("interval_at_or_before"),
                "from_plan": transition.get("from_plan"),
                "to_plan": transition.get("to_plan"),
            })

    metrics = _real_metrics(data, rows)
    verdict = evaluate_evidence_metrics(metrics)
    reasons = list(verdict["reasons"])
    if "not_prospective" not in reasons and metrics["prospective"] is not True:
        reasons.append("not_prospective")
    if any(
        item["stable_same_regime_windows"] < _MIN_STABLE_WINDOWS
        for item in metrics["constraints"].values()
    ):
        reasons.append("insufficient_stable_same_regime_windows")

    current_by_bucket: dict[str, tuple[datetime, str]] = {}
    for row in rows:
        observed_at = _parse_time(row.get("observed_at"))
        bucket = row.get("bucket")
        regime = row.get("regime_key")
        if observed_at is None or not isinstance(bucket, str) or not isinstance(regime, str):
            continue
        previous = current_by_bucket.get(bucket)
        if previous is None or observed_at >= previous[0]:
            current_by_bucket[bucket] = (observed_at, regime)
    current_regimes = [
        f"{bucket}={observed[1]}"
        for bucket, observed in sorted(current_by_bucket.items())
    ]
    source_digest = data.get("_source_digest")
    if not isinstance(source_digest, str):
        source_digest = hashlib.sha256(_canonical_json(data).encode()).hexdigest()
    timestamps = [
        parsed
        for row in rows
        if (parsed := _parse_time(row.get("observed_at"))) is not None
    ]
    result: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "input_schema_version": schema_version,
        "source_kind": data.get("_source_kind", "frozen_json"),
        "source_digest": source_digest,
        "dataset_start": min(timestamps).isoformat() if timestamps else None,
        "dataset_end": max(timestamps).isoformat() if timestamps else None,
        "prospective": metrics["prospective"],
        "eligible": verdict["eligible"],
        "eligible_strata": verdict["eligible_strata"],
        "reasons": list(dict.fromkeys(reasons)),
        "regime_set_hash": hashlib.sha256("\n".join(current_regimes).encode()).hexdigest(),
        "contours_merged": False,
        "regime_splits": _deduplicate(splits),
        "exclusions": _deduplicate([*replay["exclusions"], *_artifact_exclusions(data)]),
        "metrics": metrics,
        "decisions": replay["decisions"],
    }
    result["evidence_id"] = hashlib.sha256(_canonical_json(result).encode()).hexdigest()
    return result


def _assert_frozen_db(path: Path) -> None:
    repo_live = Path(__file__).resolve().parents[1] / "data" / "orchestra.db"
    configured = {
        Path(value).expanduser().resolve()
        for name in ("ORCHESTRA_DB", "ORCHESTRA_DB_PATH")
        if (value := os.environ.get(name))
    }
    if path.resolve() == repo_live.resolve() or path.resolve() in configured:
        raise ValueError("live Orchestra DB is not an accepted replay input")
    if Path(f"{path}-wal").exists() or Path(f"{path}-shm").exists():
        raise ValueError("SQLite input has live WAL sidecars; use sqlite3.Connection.backup")


def _load_db_copy(path: Path) -> dict[str, Any]:
    _assert_frozen_db(path)
    uri = f"file:{path.resolve()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required = {"quota_controller_decisions", "quota_controller_outcomes"}
        if not required <= tables:
            missing = ", ".join(sorted(required - tables))
            raise ValueError(f"SQLite copy lacks quota replay tables: {missing}")
        query = """
            SELECT d.created_at, d.task_class, d.model, d.fast_mode,
                   d.regime_set_hash, d.observation_json, o.status, o.actual_json,
                   o.ended_at, o.settled_at
              FROM quota_controller_decisions AS d
              LEFT JOIN quota_controller_outcomes AS o USING (decision_id)
             ORDER BY d.created_at, d.decision_id
        """
        rows: list[dict[str, Any]] = []
        for record in connection.execute(query):
            observations = json.loads(record["observation_json"])
            actual = json.loads(record["actual_json"]) if record["actual_json"] else {}
            terminal = actual.get("terminal_quota") if isinstance(actual, Mapping) else None
            for observation in observations if isinstance(observations, list) else []:
                if not isinstance(observation, Mapping):
                    continue
                bucket = observation.get("bucket")
                terminal_key = {
                    "anthropic:five_hour": "quota_five_hour_pct",
                    "anthropic:seven_day": "quota_seven_day_pct",
                    "codex:primary": "quota_primary_pct",
                    "codex_spark:primary": "quota_primary_pct",
                    "grok:primary": "quota_primary_pct",
                }.get(bucket)
                start = _number(observation.get("utilization"))
                end = (
                    _number(terminal.get(terminal_key))
                    if isinstance(terminal, Mapping) and terminal_key
                    else None
                )
                delta = (
                    end - start
                    if start is not None and end is not None and end >= start
                    else None
                )
                rows.append({
                    "observed_at": observation.get("observed_at") or record["created_at"],
                    "bucket": bucket,
                    "utilization": start,
                    "actual_turn_pp": delta,
                    "outcome_observed_at": record["settled_at"],
                    "resets_at": observation.get("reset_at"),
                    "regime_key": observation.get("regime_key") or record["regime_set_hash"],
                    "plan": observation.get("plan"),
                    "task_class": record["task_class"],
                    "model": record["model"],
                    "fast_mode": bool(record["fast_mode"]),
                })
        return {
            "schema_version": 2,
            "_source_kind": "frozen_sqlite",
            "_source_digest": _file_digest(path),
            "prospective": False,
            "live_regime_matches": False,
            "enabled_strata": [],
            "strata": {},
            "timeline_series": {},
            "observation_series": rows,
        }
    finally:
        connection.close()


def _load_input(path: Path) -> Mapping[str, Any]:
    if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        return _load_db_copy(path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("input JSON must contain an object")
    return {
        **loaded,
        "_source_kind": "frozen_json",
        "_source_digest": _file_digest(path),
    }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    if not path.parent.is_dir():
        raise ValueError(f"output directory does not exist: {path.parent}")
    content = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Frozen schema-2 JSON or WAL-safe DB copy",
    )
    parser.add_argument("--output", required=True, type=Path, help="Evidence JSON path")
    args = parser.parse_args(argv)

    data = _load_input(args.input)
    result = replay_limits_data(data)
    _write_json_atomic(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
