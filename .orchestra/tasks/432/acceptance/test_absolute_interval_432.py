from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts/recon429"))

from analyze_432 import analyze


def test_price_and_quality_differences_have_paired_intervals() -> None:
    pairs = []
    for task in range(1, 13):
        for repetition in (1, 2):
            pairs.append(
                {
                    "task": task,
                    "repetition": repetition,
                    "order": "ABAB" if task <= 6 else "BABA",
                    "A": {
                        "classification": "success",
                        "total_cost_usd": 1.0,
                        "oracle_id": f"oracle-{task}",
                    },
                    "B": {
                        "classification": "success",
                        "total_cost_usd": 0.8,
                        "oracle_id": f"oracle-{task}",
                    },
                }
            )
    noise = [
        {
            "task": task,
            "cost_A01": 1.0,
            "cost_A02": 1.0,
            "main_cache_A01": 100,
            "main_cache_A02": 100,
        }
        for task in range(1, 7)
    ]

    result = analyze({"pairs": pairs, "noise": noise})

    assert result["arm_total_cost_usd"] == pytest.approx({"A": 24.0, "B": 19.2})
    assert result["arm_cost_difference_usd"]["B_minus_A"] == pytest.approx(-4.8)
    assert result["arm_cost_difference_usd"]["ci90"] == pytest.approx([-4.8, -4.8])
    assert result["quality_count_difference"]["B_minus_A"] == 0
    assert result["quality_count_difference"]["ci90"] == [0, 0]
