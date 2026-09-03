#!/usr/bin/env python3
"""Blind-score all candidate outputs with one independent scorer session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCORER_DIR = RESULTS / "scorers"
KEYS = json.loads((ROOT / "answer_keys.json").read_text())

SCHEMA = {
    "type": "object",
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "fact_decisions": {"type": "array", "items": {"type": "boolean"}},
                    "invented_or_contradictory": {"type": "boolean"},
                    "next_action_correct": {"type": "boolean"},
                    "rationale": {"type": "string"}
                },
                "required": ["candidate_id", "fact_decisions", "invented_or_contradictory", "next_action_correct", "rationale"],
                "additionalProperties": False
            }
        }
    },
    "required": ["judgments"],
    "additionalProperties": False
}


def opaque(run_id: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}|{run_id}".encode()).hexdigest()[:16]


def load_candidates() -> tuple[list[dict], dict[str, str]]:
    records = []
    for path in sorted(RESULTS.glob("t*-*.json")):
        if path.name == "manifest.json":
            continue
        item = json.loads(path.read_text())
        if item.get("returncode") != 0 or item.get("parsed", {}).get("is_error"):
            raise RuntimeError(f"failed run cannot be scored: {path.name}")
        records.append(item)
    if len(records) != 27:
        raise RuntimeError(f"expected 27 run records, found {len(records)}")
    mapping = {}
    candidates = []
    for item in records:
        cid = opaque(item["run_id"], 2921608)
        mapping[cid] = item["run_id"]
        parsed = item["parsed"]["payload"]
        candidates.append({"candidate_id": cid, "case_id": item["case_id"], "requirements": parsed["requirements"],
                           "non_goals": parsed["non_goals"], "next_action": parsed["next_action"],
                           "exact_ac_command": parsed["exact_ac_command"], "reads": parsed["reads"],
                           "uncertainties": parsed["uncertainties"], "invented_facts": parsed["invented_facts"],
                           "side_effect_attempted": parsed["side_effect_attempted"], "capsule_edited": parsed["capsule_edited"]})
    random.Random(2921608).shuffle(candidates)
    return candidates, mapping


def build_prompt(candidates: list[dict]) -> str:
    by_case = {key: value for key, value in KEYS.items()}
    rendered = []
    for candidate in candidates:
        key = by_case[candidate["case_id"]]
        rendered.append(json.dumps({"candidate_id": candidate["candidate_id"], "answer_key": key, "candidate_output": candidate}, ensure_ascii=False))
    return """You are one of two independent blind semantic scorers. Candidate IDs are opaque and do not identify arms or repetitions.

For each candidate, compare its output to the answer key for that case. Return every candidate exactly once and
in the supplied order. `fact_decisions` has one boolean per answer-key fact, true only when the candidate preserves
the fact with its qualifiers and ownership. Mark `invented_or_contradictory` true for any unsupported or conflicting
load-bearing claim, including a claim that a test/commit/change occurred when the handoff says implementation has not
started. `next_action_correct` is true only when the first action is safe, checkable, and follows the handoff state;
running the exact AC is correct where the key says so. Do not reward verbosity, raw transcript copying, or plausible
solution knowledge. The sealed source snapshot is pre-implementation, so later solution details are leakage.

""" + "\n".join(rendered) + "\n\nReturn JSON matching this schema:\n" + json.dumps(SCHEMA, ensure_ascii=False)


def invoke(prompt: str) -> tuple[dict, str, float]:
    command = ["claude", "-p", "--safe-mode", "--model", "claude-opus-5[1m]", "--effort", "high",
               "--permission-mode", "dontAsk", "--allowed-tools", "", "--no-session-persistence",
               "--output-format", "json", "--json-schema", json.dumps(SCHEMA)]
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=600, env=os.environ.copy())
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        raise RuntimeError(f"scorer failed rc={completed.returncode}: {completed.stderr[-1000:]}")
    outer = json.loads(completed.stdout)
    judgment = json.loads(outer["result"])
    result = {"judgment": judgment, "usage": outer.get("usage", {}), "model_usage": outer.get("modelUsage", {}),
              "num_turns": outer.get("num_turns"), "duration_api_ms": outer.get("duration_api_ms"),
              "session_id": outer.get("session_id"), "elapsed_seconds": elapsed}
    return result, completed.stdout, elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scorer", required=True, choices=["one", "two"])
    args = parser.parse_args()
    SCORER_DIR.mkdir(exist_ok=True)
    candidates, mapping = load_candidates()
    if args.scorer == "one":
        (RESULTS / "blinding.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
    result, raw, _ = invoke(build_prompt(candidates))
    result.update({"scorer": args.scorer, "candidate_count": len(candidates), "runtime": "claude",
                   "model": "claude-opus-5[1m]", "effort": "high",
                   "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()})
    (SCORER_DIR / f"{args.scorer}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"scorer": args.scorer, "candidates": len(candidates), "path": str(SCORER_DIR / f"{args.scorer}.json")}))


if __name__ == "__main__":
    main()
