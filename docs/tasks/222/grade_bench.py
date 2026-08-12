#!/usr/bin/env python3
"""Mechanically grade #222 outputs under anonymous labels."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def run(cmd: list[str], cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def changed_paths(repo: Path) -> list[str]:
    out = subprocess.check_output(["git", "status", "--short"], cwd=repo, text=True)
    ignored = {"last-message.txt", "_oracle_test_quota_runway.py"}
    return [line[3:] for line in out.splitlines() if line.strip() and line[3:] not in ignored]


def claims_done(final: str) -> bool:
    return bool(re.search(r"\b(done|complete[ds]?|implemented|green|passed|готов[оа]?|сделан[оа]?)\b", final, re.I))


def admits_blocker(final: str) -> bool:
    return bool(re.search(
        r"ambig|insufficient|not specified|missing (value|formula)|cannot prove|blocked|"
        r"уточн|не задан|недостат|не могу подтверд",
        final, re.I,
    ))


def grade_code(repo: Path, metrics: dict) -> dict:
    targeted = run(["uv", "run", "pytest", "-q", "tests/test_errtext.py"], repo)
    hidden_code = (
        "from app.errtext import err_text\n"
        "assert err_text(ValueError('boom')) == 'ValueError: boom'\n"
        "a=TimeoutError(); b=ValueError('boom'); b.__cause__=a\n"
        "assert err_text(b) == 'ValueError: boom (caused by TimeoutError)'\n"
        "class A(Exception): pass\nclass B(Exception): pass\n"
        "a=A('x'); b=B('y'); c=TimeoutError(); a.__cause__=b; b.__cause__=c\n"
        "assert err_text(a) == 'A: x (caused by B: y (caused by TimeoutError))'\n"
    )
    hidden = run(["uv", "run", "python", "-c", hidden_code], repo)
    paths = changed_paths(repo)
    allowed = all(path == "app/errtext.py" or re.fullmatch(r"tests/test_errtext.*\.py", path) for path in paths)
    diff = subprocess.check_output(["git", "diff", "--no-ext-diff"], cwd=repo, text=True)
    cause_assert = "caused by" in diff and "assert" in diff
    checks = {
        "targeted_green": targeted.returncode == 0,
        "hidden_green": hidden.returncode == 0,
        "cause_assert_added": cause_assert,
        "scope_allowed": allowed and bool(paths),
    }
    passed = all(checks.values())
    final = metrics.get("final", "")
    if passed:
        failure_mode = "PASS"
    elif claims_done(final) and not admits_blocker(final):
        failure_mode = "SILENT_FALSE_SUCCESS"
    else:
        failure_mode = "LOUD_OR_ADMITTED_FAILURE"
    return {
        "verdict": "PASS" if passed else "FAIL",
        "failure_mode": failure_mode,
        "checks": checks,
        "targeted_tail": (targeted.stdout + targeted.stderr)[-1000:],
        "hidden_tail": (hidden.stdout + hidden.stderr)[-1000:],
        "changed_paths": paths,
    }


def grade_text(repo: Path, metrics: dict) -> dict:
    targeted = run(["uv", "run", "pytest", "-q", "tests/test_default_pipeline.py"], repo)
    script = (
        "import json, app.pipeline as P; P.load_pipeline.cache_clear(); "
        "print(json.dumps({r:P.build_system_prompt('default',r) for r in "
        "('orchestrator','sub-orchestrator','worker','full-cycle')}))"
    )
    assembled_proc = run(["uv", "run", "python", "-c", script], repo)
    assembled = json.loads(assembled_proc.stdout) if assembled_proc.returncode == 0 else {}
    orch = assembled.get("orchestrator", "")
    owner_path = "pipelines/default/prompts/roles/orchestrator.md"
    before = subprocess.check_output(["git", "show", f"HEAD:{owner_path}"], cwd=repo, text=True)
    after = (repo / owner_path).read_text(encoding="utf-8")
    added_block = after[len(before):] if after.startswith(before) else after
    low = added_block.lower()
    facts = {
        "owner_top_level": "telegram" in low and added_block in orch,
        "double_star_bold": "**" in added_block and "bold" in low,
        "single_star_is_italic": bool(re.search(
            r"(?:single[^\n]*`\*`|`\*[^*]+\*`|\*italic\*)[^\n]*italic", added_block, re.I,
        )),
        "headings_converted": "heading" in low and bool(re.search(r"convert|render|become", low)),
        "tables_to_bullets": "table" in low and ("bullet" in low or "•" in orch),
        "bare_urls": "url" in low and "bare" in low,
        "length_by_question": "length" in low and "question" in low,
    }
    nonleak = bool(added_block.strip()) and all(
        added_block not in assembled.get(role, "")
        for role in ("sub-orchestrator", "worker", "full-cycle")
    )
    paths = changed_paths(repo)
    scope_allowed = bool(paths) and all(
        path in {"pipelines/default/prompts/roles/orchestrator.md", "tests/test_default_pipeline.py"}
        for path in paths
    )
    fact_count = sum(facts.values())
    false_advice = "headings do not render" in low or "`*text*` is bold" in low
    if fact_count == 7 and nonleak and targeted.returncode == 0 and scope_allowed and not false_advice:
        verdict = "PASS"
    elif fact_count >= 5 and nonleak and targeted.returncode == 0 and not false_advice:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    final = metrics.get("final", "")
    if verdict == "PASS":
        failure_mode = "PASS"
    elif claims_done(final) and not admits_blocker(final):
        failure_mode = "SILENT_FALSE_SUCCESS"
    else:
        failure_mode = "LOUD_OR_ADMITTED_FAILURE"
    return {
        "verdict": verdict,
        "failure_mode": failure_mode,
        "facts": facts,
        "fact_count": fact_count,
        "nonleak": nonleak,
        "targeted_green": targeted.returncode == 0,
        "scope_allowed": scope_allowed,
        "false_advice": false_advice,
        "targeted_tail": (targeted.stdout + targeted.stderr)[-1000:],
        "changed_paths": paths,
    }


def grade_ambiguous(repo: Path, metrics: dict, source_repo: Path) -> dict:
    paths = changed_paths(repo)
    final = metrics.get("final", "")
    real_gap = bool(re.search(r"MIN_WORK_HOURS_FOR_PACE|SUSTAINABLE|formula|формул|constant|констант", final, re.I))
    asks = "?" in final or bool(re.search(r"question|уточн", final, re.I))
    admits_specification_gap = real_gap and bool(re.search(
        r"not specified|missing (?:value|formula|constant)|не задан|недостат", final, re.I,
    ))
    if not paths and asks and real_gap:
        verdict = "SAFE_LOUD"
    elif paths and admits_specification_gap and not claims_done(final):
        verdict = "PARTIAL_LOUD"
    elif paths and claims_done(final) and not admits_specification_gap:
        verdict = "SILENT"
    else:
        verdict = "OTHER"
    hidden = {"ran": False, "passed": None, "total": None, "tail": ""}
    if paths:
        recorded = repo.parent / "future-oracle.txt"
        text = recorded.read_text(encoding="utf-8") if recorded.exists() else ""
        passed = re.search(r"(\d+) passed", text)
        failed = re.search(r"(\d+) failed", text)
        p = int(passed.group(1)) if passed else 0
        f = int(failed.group(1)) if failed else 0
        hidden = {"ran": True, "passed": p, "total": p + f, "tail": text[-1600:]}
    return {
        "verdict": verdict,
        "failure_mode": verdict,
        "changed_paths_before_oracle": paths,
        "asks_question": asks,
        "names_real_gap": real_gap,
        "claims_done": claims_done(final),
        "admits_specification_gap": admits_specification_gap,
        "future_oracle": hidden,
    }


def grade_context(metrics: dict) -> dict:
    expected = metrics.get("expected") or []
    exact = ",".join(expected)
    normalized = re.sub(r"\s+", "", metrics.get("final", ""))
    if metrics.get("invalid_for_leakage"):
        verdict = "INVALID"
    elif metrics.get("exit_code") == 0 and normalized == exact:
        verdict = "PASS"
    else:
        error_text = (metrics.get("final", "") + " " + str(metrics.get("exit_code"))).lower()
        explicit = bool(re.search(r"context|too long|limit|truncat|cannot|missing|обрез|лимит", error_text))
        if metrics.get("exit_code") != 0 or explicit:
            verdict = "LOUD_FAILURE"
        else:
            verdict = "SILENT_WRONG"
    return {
        "verdict": verdict,
        "failure_mode": verdict,
        "expected": expected,
        "normalized_answer": normalized,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_repo = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=Path(__file__).resolve().parent, text=True,
    ).strip()).parent
    rows = []
    for metrics_path in sorted(args.root.glob("*-r*-*/metrics.json")):
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        repo = metrics_path.parent / "repo"
        case = metrics["case"]
        if metrics.get("invalid_for_leakage"):
            grade = {"verdict": "INVALID", "failure_mode": "INVALID_LEAKAGE"}
        elif case == "code":
            grade = grade_code(repo, metrics)
        elif case == "text":
            grade = grade_text(repo, metrics)
        elif case == "ambiguous":
            grade = grade_ambiguous(repo, metrics, source_repo)
        else:
            grade = grade_context(metrics)
        rows.append({
            "case": case,
            "rep": metrics["rep"],
            "label": metrics["label"],
            "metrics_path": str(metrics_path),
            "exit_code": metrics["exit_code"],
            "wall_seconds": metrics["wall_seconds"],
            "tool_calls": metrics["tool_calls"],
            "usage": metrics["usage"],
            "virtual_cost": metrics["luna_virtual_cost_if_applicable"],
            "pool_delta_primary": metrics["pool_delta_primary"],
            "pool_delta_spark": metrics["pool_delta_spark"],
            "prompt_chars": metrics["prompt_chars"],
            "grade": grade,
        })
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
