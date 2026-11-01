"""Tests of the offline oracle; fixtures are NOT model responses."""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("v1114_harness", HERE / "harness.py")
h = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = h
SPEC.loader.exec_module(h)


@pytest.fixture
def cases():
    return h.bank()


def perfect(cases):
    return {"answers": [{"id": c["id"], "choice": c["expected"],
                          "evidence_ids": sorted({e["id"] for e in c["evidence"]})}
                         for c in cases]}


def test_golden_anchors_exist_and_both_kinds_are_present(cases):
    h.validate_bank(cases, h.blocks(h.MEMORY.read_text()))
    assert sum(c["kind"] == "fact" for c in cases) == 24
    assert sum(c["kind"] == "behavior" for c in cases) == 16


def test_positive_control(cases):
    result = h.score(perfect(cases), cases)
    assert result["supported_correct"] == len(cases)
    assert not result["invalid_schema"]


@pytest.mark.parametrize("case_id", ["B01", "B02", "B03", "B04", "B05", "B07", "B16"])
def test_changed_restart_routing_or_unknown_decision_is_rejected(cases, case_id):
    response = perfect(cases)
    row = next(a for a in response["answers"] if a["id"] == case_id)
    options = next(c["options"] for c in cases if c["id"] == case_id)
    row["choice"] = next(k for k in options if k != row["choice"])
    result = h.score(response, cases)
    assert result["supported_correct"] == len(cases) - 1


def test_every_single_answer_mutation_is_detected(cases):
    control = perfect(cases)
    for i, case in enumerate(cases):
        response = copy.deepcopy(control)
        response["answers"][i]["choice"] = next(k for k in case["options"] if k != case["expected"])
        assert h.score(response, cases)["decision_correct"] == len(cases) - 1


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown_id", "bad_schema"])
def test_incomplete_or_ambiguous_output_fails_closed(cases, mutation):
    response = perfect(cases)
    if mutation == "missing":
        response["answers"].pop()
    elif mutation == "duplicate":
        response["answers"].append(response["answers"][0])
    elif mutation == "unknown_id":
        response["answers"][0]["id"] = "invented"
    else:
        response = {"answer": "all correct"}
    assert h.score(response, cases)["invalid_schema"]


def test_real_choice_without_required_evidence_is_separate_from_correctness(cases):
    response = perfect(cases)
    response["answers"][0]["evidence_ids"] = ["M99"]
    result = h.score(response, cases)
    assert result["decision_correct"] == len(cases)
    assert result["supported_correct"] == len(cases) - 1


def test_real_but_unread_source_is_not_credited(cases):
    response = perfect(cases)
    result = h.score(response, cases, available_ids=[])
    assert result["decision_correct"] == len(cases)
    assert result["supported_correct"] == 0


def test_removed_source_anchor_fails_before_measurement(cases):
    rows = h.blocks(h.MEMORY.read_text())
    rows["M37"] = rows["M37"].replace("0 running агентов две проверки подряд", "zero")
    with pytest.raises(ValueError, match="evidence anchor missing"):
        h.validate_bank(cases, rows)


def test_headline_extraction_handles_glob_stars():
    assert h.headline('- **Rules (`prompts/**`) are English** (date). Detail') == 'Rules (`prompts/**`) are English'


def test_source_retained_but_headline_loses_conditions(cases):
    case = next(c for c in cases if c["id"] == "B04")
    versions = h.proxies(h.MEMORY.read_text())
    assert h.coverage(versions["full"], case)
    assert not h.coverage(versions["headlines"], case)


def test_retrieval_is_deterministic_and_does_not_use_golden():
    rows = {"M02": "Квота общий пул", "M01": "Рестарт сторож простоя"}
    assert h.retrieve("Рестарт простоя", rows, 1) == ["M01"]
    assert h.retrieve("unknown query", rows, 1) == ["M01"]
