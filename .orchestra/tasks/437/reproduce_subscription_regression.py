#!/usr/bin/env python3
"""Reproduce the frozen #437 five-hour subscription regression."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import numpy as np


START = "2026-07-29T05:17:21.890375+00:00"
CUTOFF = "2026-09-01T18:45:10.186332+00:00"
TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_create_tokens",
)


def _ols(y: np.ndarray, predictors: np.ndarray, names: list[str]) -> dict:
    design = np.column_stack([np.ones(len(y)), predictors])
    beta, _, rank, singular = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ beta
    residual = y - fitted
    sse = float(residual @ residual)
    centered = y - y.mean()
    sst = float(centered @ centered)
    r2 = 1.0 - sse / sst if sst else 0.0
    dof = len(y) - design.shape[1]
    covariance = np.linalg.pinv(design.T @ design) * (sse / dof)
    se = np.sqrt(np.maximum(0.0, np.diag(covariance)))
    labels = ["intercept", *names]
    coefficients = {}
    for label, value, error in zip(labels, beta, se, strict=True):
        coefficients[label] = {
            "value": float(value),
            "std_error": float(error),
            "ci95_normal": [float(value - 1.96 * error), float(value + 1.96 * error)],
        }
    return {
        "n": len(y),
        "rank": int(rank),
        "singular_values": [float(value) for value in singular],
        "r2": r2,
        "sse": sse,
        "dof": dof,
        "coefficients": coefficients,
    }


def _r2_for_target(target: np.ndarray, others: np.ndarray) -> float:
    design = np.column_stack([np.ones(len(target)), others])
    beta = np.linalg.lstsq(design, target, rcond=None)[0]
    residual = target - design @ beta
    sse = float(residual @ residual)
    centered = target - target.mean()
    sst = float(centered @ centered)
    return 1.0 - sse / sst if sst else 0.0


def _diagnostics(predictors: np.ndarray, names: list[str]) -> dict:
    correlations = np.corrcoef(predictors, rowvar=False)
    vifs = {}
    for index, name in enumerate(names):
        other_indices = [i for i in range(len(names)) if i != index]
        r2 = _r2_for_target(predictors[:, index], predictors[:, other_indices])
        vifs[name] = float("inf") if r2 >= 1.0 else float(1.0 / (1.0 - r2))
    std = predictors.std(axis=0, ddof=0)
    if np.any(std == 0):
        condition_number = float("inf")
    else:
        standardized = (predictors - predictors.mean(axis=0)) / std
        condition_number = float(
            np.linalg.cond(np.column_stack([np.ones(len(predictors)), standardized]))
        )
    return {
        "correlations": {
            row_name: {
                col_name: float(correlations[row, col])
                for col, col_name in enumerate(names)
            }
            for row, row_name in enumerate(names)
        },
        "vif": vifs,
        "standardized_condition_number": condition_number,
    }


def _window_payload(segment: list[sqlite3.Row], token_rows: list[sqlite3.Row]) -> dict:
    first = segment[0]
    last = segment[-1]
    first_ts = datetime.fromisoformat(first["ts"])
    last_ts = datetime.fromisoformat(last["ts"])
    payload = {
        "start": first["ts"],
        "end": last["ts"],
        "duration_hours": (last_ts - first_ts).total_seconds() / 3600.0,
        "quota_rows": len(segment),
        "token_rows": len(token_rows),
        "first_pct": float(first["quota_five_hour_pct"]),
        "last_pct": float(last["quota_five_hour_pct"]),
        "min_pct": min(float(row["quota_five_hour_pct"]) for row in segment),
        "max_pct": max(float(row["quota_five_hour_pct"]) for row in segment),
        "tokens_all": {},
        "tokens_quota_observed": {},
    }
    for key in TOKEN_KEYS:
        payload["tokens_all"][key] = sum(int(row[key]) for row in token_rows)
        payload["tokens_quota_observed"][key] = sum(
            int(row[key]) for row in token_rows if row["quota_five_hour_pct"] is not None
        )
    payload["models"] = dict(Counter(str(row["model"]) for row in token_rows))
    return payload


def _make_windows(rows: list[sqlite3.Row]) -> list[dict]:
    quota_rows = [row for row in rows if row["quota_five_hour_pct"] is not None]
    segments: list[list[sqlite3.Row]] = []
    current: list[sqlite3.Row] = []
    previous = None
    for row in quota_rows:
        quota = float(row["quota_five_hour_pct"])
        if previous is not None and quota < previous:
            segments.append(current)
            current = []
        current.append(row)
        previous = quota
    if current:
        segments.append(current)

    windows = []
    for segment in segments:
        start = segment[0]["ts"]
        end = segment[-1]["ts"]
        token_rows = [row for row in rows if start <= row["ts"] <= end]
        windows.append(_window_payload(segment, token_rows))
    return windows


def _arm(windows: list[dict], name: str) -> dict:
    if name == "A":
        selected = windows
        token_field = "tokens_all"
    elif name == "B":
        selected = windows
        token_field = "tokens_quota_observed"
    elif name == "C":
        selected = [
            window for window in windows
            if window["duration_hours"] >= 1.0 and window["quota_rows"] >= 5
        ]
        token_field = "tokens_all"
    elif name == "D":
        selected = [window for window in windows if window["last_pct"] < 100.0]
        token_field = "tokens_all"
    else:
        raise ValueError(name)

    y = np.array([window["last_pct"] - window["first_pct"] for window in selected])
    names = ["cache_read_MTok", "cache_create_MTok", "output_MTok"]
    predictors = np.array([
        [
            window[token_field]["cache_read_tokens"] / 1_000_000,
            window[token_field]["cache_create_tokens"] / 1_000_000,
            window[token_field]["output_tokens"] / 1_000_000,
        ]
        for window in selected
    ])
    control_indices = [0, 2]
    control = _ols(y, predictors[:, control_indices], [names[i] for i in control_indices])
    extended = _ols(y, predictors, names)
    diagnostics = _diagnostics(predictors, names)
    ratios = np.array([
        row[1] / row[0] for row in predictors if row[0] > 0
    ])
    ratio_summary = {
        "n": len(ratios),
        "min": float(ratios.min()),
        "p10": float(np.quantile(ratios, 0.10)),
        "median": float(np.quantile(ratios, 0.50)),
        "p90": float(np.quantile(ratios, 0.90)),
        "max": float(ratios.max()),
    }
    read = control["coefficients"]["cache_read_MTok"]["value"]
    output = control["coefficients"]["output_MTok"]["value"]
    return {
        "windows": len(selected),
        "token_source": token_field,
        "control": control,
        "extended": extended,
        "delta_r2": extended["r2"] - control["r2"],
        "diagnostics": diagnostics,
        "cache_create_read_ratio": ratio_summary,
        "control_gate": {
            "read_output_abs_ratio": abs(read / output),
            "read_near_zero": abs(read / output) < 0.01,
            "output_positive": output > 0,
            "output_gt_10x_read": output > 10 * abs(read),
        },
        "window_ids": [window["start"] for window in selected],
    }


def _self_test() -> None:
    x = np.array([
        [1.0, 5.0, 1.0],
        [2.0, 1.0, 3.0],
        [3.0, 4.0, 2.0],
        [4.0, 2.0, 6.0],
        [5.0, 6.0, 4.0],
        [6.0, 3.0, 8.0],
    ])
    y = 7.0 + 2.0 * x[:, 0] - 3.0 * x[:, 1] + 5.0 * x[:, 2]
    result = _ols(y, x, ["a", "b", "c"])
    values = result["coefficients"]
    assert abs(values["intercept"]["value"] - 7.0) < 1e-9
    assert abs(values["a"]["value"] - 2.0) < 1e-9
    assert abs(values["b"]["value"] + 3.0) < 1e-9
    assert abs(values["c"]["value"] - 5.0) < 1e-9
    assert abs(result["r2"] - 1.0) < 1e-12
    diagnostics = _diagnostics(x, ["a", "b", "c"])
    assert diagnostics["standardized_condition_number"] > 1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("SELF_TEST_OK")
        return
    if args.db is None or args.output is None:
        parser.error("--db and --output are required unless --self-test is used")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")

    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT ts, model, input_tokens, output_tokens,
               cache_read_tokens, cache_create_tokens, quota_five_hour_pct
        FROM turn_usage
        WHERE runtime = 'claude' AND ts >= ? AND ts <= ?
        ORDER BY ts ASC
        """,
        (START, CUTOFF),
    ).fetchall()
    connection.close()
    windows = _make_windows(rows)
    arms = {name: _arm(windows, name) for name in ("A", "B", "C", "D")}
    result = {
        "contract": {
            "start": START,
            "cutoff": CUTOFF,
            "boundary": "new window on strict quota_five_hour_pct decrease, ordered by ts",
            "outcome": "last-first",
            "units": "percentage points per million tokens",
        },
        "source": {
            "db": str(args.db),
            "rows": len(rows),
            "quota_rows": sum(row["quota_five_hour_pct"] is not None for row in rows),
            "models": dict(Counter(str(row["model"]) for row in rows)),
        },
        "all_windows": windows,
        "arms": arms,
        "stable_control_gate": all(
            all(arm["control_gate"].values()) for arm in arms.values()
        ),
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "rows": len(rows),
        "windows": {name: arm["windows"] for name, arm in arms.items()},
        "stable_control_gate": result["stable_control_gate"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
