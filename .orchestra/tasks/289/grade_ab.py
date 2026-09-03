#!/usr/bin/env python3
"""Mechanically verify the freeze/commitment and blind-grade the A/B outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


EXPECTED_CORPUS = "5ab469c76089dc124e849223b904eea449b36a8308e1e07621b4f863af43bf5d"
EXPECTED_PROMPT = "4cd1ea1d3485ee351a34559768ab94c944960ce180ce631ae374191e654d3222"
CASES = ("K2", "M7", "Q4", "T9")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(text: str, case_id: str) -> str:
    match = re.search(
        rf"^## Case {re.escape(case_id)}\s*$([\s\S]*?)(?=^## (?:Case|Verdict)|\Z)",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"missing section {case_id}")
    return match.group(1).strip()


def case_verdict(body: str) -> str:
    match = re.search(r"(?im)^.*verdict.*\b(PASS|BLOCK)\b", body)
    if match is None:
        raise ValueError("missing case verdict")
    return match.group(1).upper()


def grade_anonymous(text: str, truth: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"cases": {}}
    for case_id in CASES:
        body = section(text, case_id)
        lower = body.lower()
        verdict = case_verdict(body)
        if case_id == "K2":
            mechanism_hit = (
                verdict == "BLOCK"
                and all(token in lower for token in ("admission", "unknown", "session"))
                and any(token in lower for token in ("task", "delivery", "send"))
            )
        elif case_id == "Q4":
            mechanism_hit = (
                verdict == "BLOCK"
                and re.search(r"\block(?:ed|ing|s)?\b", lower) is not None
                and any(token in lower for token in ("sleep", "wait", "retry", "starv", "queue"))
            )
        else:
            mechanism_hit = None
        label = truth[case_id]["label"]
        blocking_false_positive = label == "clean" and verdict == "BLOCK"
        result["cases"][case_id] = {
            "truth_label": label,
            "verdict": verdict,
            "required_mechanism_hit": mechanism_hit,
            "blocking_false_positive": blocking_false_positive,
        }

    defect_cases = [case_id for case_id in CASES if truth[case_id]["label"] == "defect"]
    clean_cases = [case_id for case_id in CASES if truth[case_id]["label"] == "clean"]
    hits = sum(bool(result["cases"][case_id]["required_mechanism_hit"]) for case_id in defect_cases)
    false_positives = sum(bool(result["cases"][case_id]["blocking_false_positive"]) for case_id in clean_cases)
    result["required_blocker_hits"] = hits
    result["defect_cases"] = len(defect_cases)
    result["required_blocker_recall"] = hits / len(defect_cases)
    result["blocking_false_positives"] = false_positives
    result["clean_cases"] = len(clean_cases)
    result["blocking_false_positive_rate"] = false_positives / len(clean_cases)
    result["verdict_vector"] = [result["cases"][case_id]["verdict"] for case_id in CASES]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--luna-review", type=Path, required=True)
    parser.add_argument("--sol-review", type=Path, required=True)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-evidence", type=Path)
    parser.add_argument("--combined-evidence", type=Path)
    args = parser.parse_args()

    corpus_hash = sha256(args.corpus)
    prompt_hash = sha256(args.prompt)
    if corpus_hash != EXPECTED_CORPUS or prompt_hash != EXPECTED_PROMPT:
        raise ValueError("frozen corpus or prompt hash mismatch")

    reveal = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    truth = reveal["truth"]
    canonical = json.dumps(truth, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    commitment = hashlib.sha256((canonical + reveal["nonce"]).encode("utf-8")).hexdigest()
    if commitment != reveal["commitment"]:
        raise ValueError("ground-truth commitment mismatch")

    named_paths = {"luna": args.luna_review, "sol": args.sol_review}
    # Hash-sort first, grade as anonymous arms, and attach model labels only
    # after all case scores exist.
    anonymous = sorted(
        ((sha256(path), path.read_text(encoding="utf-8")) for path in named_paths.values()),
        key=lambda pair: pair[0],
    )
    blind_results: dict[str, Any] = {}
    hash_to_blind: dict[str, str] = {}
    for index, (output_hash, text) in enumerate(anonymous, start=1):
        blind_id = f"arm-{index}"
        blind_results[blind_id] = grade_anonymous(text, truth)
        blind_results[blind_id]["review_sha256"] = output_hash
        hash_to_blind[output_hash] = blind_id

    model_mapping = {model: hash_to_blind[sha256(path)] for model, path in named_paths.items()}
    luna = blind_results[model_mapping["luna"]]
    sol = blind_results[model_mapping["sol"]]
    if luna["required_blocker_hits"] < sol["required_blocker_hits"]:
        decision = "luna_clearly_worse"
    elif luna["blocking_false_positives"] > sol["blocking_false_positives"]:
        decision = "luna_clearly_worse"
    elif (
        luna["required_blocker_hits"] == sol["required_blocker_hits"]
        and luna["blocking_false_positives"] == sol["blocking_false_positives"]
    ):
        decision = "no_observed_difference_not_equivalence"
    else:
        decision = "luna_not_worse_in_this_pilot"
    common_misses = [
        case_id
        for case_id in CASES
        if truth[case_id]["label"] == "defect"
        and not luna["cases"][case_id]["required_mechanism_hit"]
        and not sol["cases"][case_id]["required_mechanism_hit"]
    ]

    metadata = json.loads(args.run_metadata.read_text(encoding="utf-8"))
    output = {
        "schema_version": 1,
        "freeze": {
            "corpus_sha256": corpus_hash,
            "prompt_sha256": prompt_hash,
            "ground_truth_commitment": commitment,
            "verified": True,
        },
        "blind_results": blind_results,
        "model_to_blind_arm": model_mapping,
        "decision": decision,
        "common_required_blocker_misses": common_misses,
        "run_metadata": metadata,
        "limits": [
            "N=4 is an operational falsifier, not a statistical equivalence study.",
            "A mechanism is a hit only if it matches the preregistered blocker; a different valid finding is secondary value, not primary recall.",
            "Both calls use the same model family, so common misses do not estimate cross-family performance.",
        ],
    }
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if bool(args.base_evidence) != bool(args.combined_evidence):
        raise ValueError("--base-evidence and --combined-evidence must be provided together")
    if args.base_evidence and args.combined_evidence:
        combined = json.loads(args.base_evidence.read_text(encoding="utf-8"))
        combined["luna_sol_preregistered_ab"] = output
        args.combined_evidence.write_text(
            json.dumps(combined, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "decision": decision,
        "common_misses": common_misses,
        "luna_hits": luna["required_blocker_hits"],
        "sol_hits": sol["required_blocker_hits"],
        "luna_false_positives": luna["blocking_false_positives"],
        "sol_false_positives": sol["blocking_false_positives"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
