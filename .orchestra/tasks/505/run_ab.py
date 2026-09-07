#!/usr/bin/env python3
"""Frozen A/B/A/B harness for #505. Paid work needs an explicit execution flag."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import statistics
import subprocess
import tarfile
import time
from collections import Counter
from pathlib import Path
from typing import Any


TASK_DIR = Path(__file__).resolve().parent
ROOT = TASK_DIR.parents[2]
COMMON_REPO = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT,
        text=True,
    ).strip()
).parent
BASE_COMMIT = "bf59a7d38739af3c7652b9466b2590490d83b0b7"
FIX_COMMIT = "cb052ede731d0a0846a340b02b1992da549cf095"
ORACLE_DIR = TASK_DIR / "oracle_tests"
ORACLE_MANIFEST = TASK_DIR / "oracle_manifest.json"
CANDIDATE_TASK = TASK_DIR / "candidate_task.md"
SCRATCH_ROOT = Path("/tmp/astra505")
RAW_DIR = TASK_DIR / "raw"
BATCH_IDENTITY = RAW_DIR / "batch_identity.json"
PREFLIGHT_RESULT = RAW_DIR / "preflight.json"
PARTIAL_RESULT = RAW_DIR / "benchmark.partial.json"
FINAL_RESULT = RAW_DIR / "benchmark.json"
MODELS = ("gpt-6-astra", "gpt-5.6-sol")
RUNS = 3
RUN_SEQUENCE = tuple((run, model) for run in range(RUNS) for model in MODELS)
TIMEOUT_SECONDS = 3600
ORACLE_FILES = (
    "tests/test_review_coverage_target_drift_474.py",
    "tests/test_merge_test_gate.py",
    "tests/test_acceptance.py",
    "tests/test_review_receipt_migration_436.py",
)
ALLOWED_PRODUCTION = {
    "app/db.py",
    "app/merge_operations.py",
    "app/merge_test_gate.py",
    "app/review_coverage.py",
    "scripts/migrate_review_receipts.py",
}
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
PRICES = {
    "gpt-6-astra": {"input": 10.0, "cached": 1.0, "write": 12.5, "output": 50.0},
    "gpt-5.6-sol": {"input": 4.0, "cached": 0.4, "write": 5.0, "output": 20.0},
}
REASONING_CONTROL_PROMPT = (
    "Without using any tools, prove rigorously whether every positive integer can be "
    "written as the sum of at most four squares, then compute the number of "
    "representations of 2026 as an ordered sum of four squares. Show the reasoning."
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def source_archive() -> bytes:
    return subprocess.check_output(
        ["git", "archive", "--format=tar", BASE_COMMIT], cwd=ROOT
    )


def source_fixture_hash() -> str:
    return sha256_bytes(source_archive())


def file_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if path.is_dir() or any(part in IGNORED_PARTS for part in relative.parts):
            continue
        name = relative.as_posix()
        if path.is_symlink():
            manifest[name] = "link:" + os.readlink(path)
        else:
            manifest[name] = sha256(path)
    return manifest


def oracle_bundle_hash() -> str:
    digest = hashlib.sha256()
    for relative in ORACLE_FILES:
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update((ORACLE_DIR / relative).read_bytes())
        digest.update(b"\0")
    digest.update(ORACLE_MANIFEST.read_bytes())
    return digest.hexdigest()


def export_source(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(source_archive()), mode="r:") as bundle:
        bundle.extractall(destination, filter="data")
    shutil.copy2(destination / "CLAUDE.md", destination / "AGENTS.md")
    for relative in ORACLE_FILES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ORACLE_DIR / relative, target)
    shutil.copy2(CANDIDATE_TASK, destination / "TASK.md")


def load_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def usage_from_events(events: list[dict[str, Any]]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for event in events:
        if event.get("type") == "turn.completed":
            raw = event.get("usage") or {}
            usage = {
                "input_tokens": int(raw.get("input_tokens") or 0),
                "cache_read_tokens": int(raw.get("cached_input_tokens") or 0),
                "cache_create_tokens": int(raw.get("cache_write_input_tokens") or 0),
                "output_tokens": int(raw.get("output_tokens") or 0),
                "reasoning_tokens": int(raw.get("reasoning_output_tokens") or 0),
            }
    return usage


def computed_cost_usd(model: str, usage: dict[str, int]) -> dict[str, float | int | str]:
    prices = PRICES[model]
    total_input = max(0, usage["input_tokens"])
    cache_read = min(max(0, usage["cache_read_tokens"]), total_input)
    cache_create = min(
        max(0, usage["cache_create_tokens"]), max(0, total_input - cache_read)
    )
    fresh = max(0, total_input - cache_read - cache_create)
    fresh_cost = fresh * prices["input"] / 1_000_000
    read_cost = cache_read * prices["cached"] / 1_000_000
    create_cost = cache_create * prices["write"] / 1_000_000
    output_cost = max(0, usage["output_tokens"]) * prices["output"] / 1_000_000
    total = fresh_cost + read_cost + create_cost + output_cost
    return {
        "cost_source": "computed_vendor_card",
        "fresh_input_tokens": fresh,
        "fresh_input_usd": fresh_cost,
        "cache_read_usd": read_cost,
        "cache_create_usd": create_cost,
        "output_usd": output_cost,
        "cost_usd": total,
        "arithmetic": (
            f"({fresh}*{prices['input']} + {cache_read}*{prices['cached']} + "
            f"{cache_create}*{prices['write']} + {usage['output_tokens']}*"
            f"{prices['output']}) / 1000000 = {total:.9f}"
        ),
    }


def verify_price_registration() -> None:
    probe = (
        "import json; from app.backend_codex import CODEX_TOKEN_PRICES as p; "
        "print(json.dumps(p.get('gpt-6-astra'), sort_keys=True))"
    )
    result = subprocess.run(
        [str(COMMON_REPO / ".venv/bin/python"), "-c", probe],
        cwd=COMMON_REPO,
        capture_output=True,
        text=True,
    )
    expected = PRICES["gpt-6-astra"]
    try:
        observed = json.loads(result.stdout.strip())
    except Exception:
        observed = None
    if result.returncode != 0 or observed != expected:
        raise SystemExit(
            "REFUSE_PAID_RUN: #503 Astra price row is not registered exactly; "
            f"observed={observed!r}, stderr={result.stderr[-300:]!r}"
        )


def binary_identity() -> dict[str, str]:
    path = shutil.which("codex")
    if not path:
        raise SystemExit("CODEX_BINARY_MISSING: codex is not on PATH")
    resolved = str(Path(path).resolve())
    version = subprocess.check_output([path, "--version"], text=True).strip()
    return {
        "path": path,
        "resolved_path": resolved,
        "version": version,
        "sha256": sha256(Path(resolved)),
    }


def assert_binary_identity(expected: dict[str, str]) -> None:
    observed = binary_identity()
    if observed != expected:
        raise SystemExit(
            "CODEX_BINARY_CHANGED: stop before mixed-binary run; "
            f"expected={expected!r}, observed={observed!r}"
        )


def bwrap_prefix(work: Path) -> list[str]:
    configured_home = os.environ.get("CODEX_HOME")
    codex_home = (
        Path(configured_home).resolve()
        if configured_home
        else (Path.home() / ".codex").resolve()
    )
    venv = COMMON_REPO / ".venv"
    if not codex_home.is_dir() or not venv.is_dir():
        raise SystemExit(f"runtime missing: CODEX_HOME={codex_home}, venv={venv}")
    temp_dir = work.parent / f"{work.name}-tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    runtime_home = work.parent / f"{work.name}-codex-home"
    if runtime_home.exists():
        shutil.rmtree(runtime_home)
    runtime_home.mkdir(parents=True)
    auth_source = codex_home / "auth.json"
    if not auth_source.exists():
        raise SystemExit(f"Codex auth is unavailable: {auth_source}")
    shutil.copy2(auth_source.resolve(), runtime_home / "auth.json")
    (runtime_home / "auth.json").chmod(0o600)
    venv_mountpoint = SCRATCH_ROOT / "venv"
    venv_mountpoint.mkdir(parents=True, exist_ok=True)
    return [
        "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
        "--bind", str(work), str(work),
        "--bind", str(temp_dir), str(temp_dir),
        "--bind", str(runtime_home), str(runtime_home),
        "--ro-bind", str(venv), str(venv_mountpoint),
        "--tmpfs", "/mnt/data/Projects/Python/orchestra",
        "--setenv", "TMPDIR", str(temp_dir),
        "--setenv", "CODEX_HOME", str(runtime_home),
        "--chdir", str(work),
    ]


def codex_command(work: Path, model: str, prompt: str, effort: str) -> list[str]:
    return bwrap_prefix(work) + [
        "codex", "exec", "--skip-git-repo-check", "--ignore-user-config", "--ephemeral",
        # The process is already inside the outer bwrap above. A second Codex bwrap cannot
        # create a nested user namespace; this flag is explicitly for externally sandboxed runs.
        "--dangerously-bypass-approvals-and-sandbox",
        "-C", str(work), "--json",
        "-c", f"model_reasoning_effort={effort}",
        "-c", "project_doc_max_bytes=262144",
        "-m", model, prompt,
    ]


def isolation_preflight(
    frozen_source_hash: str,
    frozen_oracle_hash: str,
    frozen_binary: dict[str, str],
) -> dict[str, Any]:
    assert_binary_identity(frozen_binary)
    work = SCRATCH_ROOT / "preflight"
    export_source(work)
    oracle_hashes = {relative: sha256(work / relative) for relative in ORACLE_FILES}
    shell = subprocess.run(
        bwrap_prefix(work) + [
            "sh", "-c",
            """set -u
echo SHELL_OK
test ! -e /mnt/data/Projects/Python/orchestra/CLAUDE.md
test ! -e /mnt/data/Projects/Python/orchestra/.orchestra/tasks/474
test ! -e .orchestra/tasks/474
test ! -e .git
test ! -e "$CODEX_HOME/sessions"
test ! -e "$CODEX_HOME/logs_2.sqlite"
test ! -e "$CODEX_HOME/history.jsonl"
test -f "$CODEX_HOME/auth.json"
cmp -s CLAUDE.md AGENTS.md
for f in app/db.py app/merge_operations.py app/merge_test_gate.py app/review_coverage.py scripts/migrate_review_receipts.py; do
  test -r "$f" && test -w "$f"
  cp "$f" "$TMPDIR/write-probe"
  cat "$TMPDIR/write-probe" > "$f"
  cmp -s "$f" "$TMPDIR/write-probe"
done
echo PRODUCTION_WRITABLE=5/5
set +e
/tmp/astra505/venv/bin/python -m pytest -q tests/test_review_coverage_target_drift_474.py tests/test_merge_test_gate.py tests/test_acceptance.py tests/test_review_receipt_migration_436.py > "$TMPDIR/preflight-pytest.txt" 2>&1
pytest_rc=$?
set -e
cat "$TMPDIR/preflight-pytest.txt"
test "$pytest_rc" -eq 1
grep -F "10 failed, 49 passed, 6 errors" "$TMPDIR/preflight-pytest.txt"
echo BLINDNESS_OK
codex login status
codex --version
/tmp/astra505/venv/bin/python -c 'import pytest; print(pytest.__version__)'
""",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    prompt = subprocess.run(
        bwrap_prefix(work) + [
            "codex", "debug", "prompt-input",
            "-c", "project_doc_max_bytes=262144", "probe",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        prompt_items = json.loads(prompt.stdout)
    except Exception as error:
        raise SystemExit(
            f"ISOLATION_PREFLIGHT_FAILED: prompt-input parse: {error}; "
            f"stderr={prompt.stderr[-500:]!r}"
        ) from error
    delivered = "\n".join(
        str(content.get("text") or "")
        for item in prompt_items
        for content in (item.get("content") or [])
        if isinstance(content, dict)
    )
    agents = (work / "AGENTS.md").read_text(encoding="utf-8")
    facts = {
        "checked_at": time.time(),
        "loadavg": list(os.getloadavg()),
        "binary": frozen_binary,
        "shell_rc": shell.returncode,
        "shell_stdout": shell.stdout.strip(),
        "shell_stderr": shell.stderr.strip(),
        "prompt_rc": prompt.returncode,
        "prompt_items": len(prompt_items),
        "prompt_chars": len(delivered),
        "agents_bytes": (work / "AGENTS.md").stat().st_size,
        "agents_full_substring": agents in delivered,
        "agents_tail_1000_present": agents[-1000:] in delivered,
        "base_contains_474": "#474" in agents,
        "source_fixture_hash_expected": frozen_source_hash,
        "source_fixture_hash_observed": source_fixture_hash(),
        "oracle_bundle_hash_expected": frozen_oracle_hash,
        "oracle_bundle_hash_observed": oracle_bundle_hash(),
        "scratch_oracle_hashes": oracle_hashes,
    }
    ok = bool(
        shell.returncode == 0
        and "SHELL_OK" in shell.stdout
        and "PRODUCTION_WRITABLE=5/5" in shell.stdout
        and "10 failed, 49 passed, 6 errors" in shell.stdout
        and "BLINDNESS_OK" in shell.stdout
        and prompt.returncode == 0
        and facts["agents_full_substring"]
        and facts["agents_tail_1000_present"]
        and not facts["base_contains_474"]
        and facts["source_fixture_hash_expected"] == facts["source_fixture_hash_observed"]
        and facts["oracle_bundle_hash_expected"] == facts["oracle_bundle_hash_observed"]
    )
    facts["ok"] = ok
    assert_binary_identity(frozen_binary)
    if not ok:
        raise SystemExit(f"ISOLATION_PREFLIGHT_FAILED: {facts!r}")
    return facts


def oracle_command() -> list[str]:
    return [str(COMMON_REPO / ".venv/bin/python"), "-m", "pytest", "-q", *ORACLE_FILES]


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )


def run_candidate(
    model: str,
    run_index: int,
    frozen_source_hash: str,
    frozen_oracle_hash: str,
    frozen_binary: dict[str, str],
    artifact_label: str | None = None,
) -> dict[str, Any]:
    assert_binary_identity(frozen_binary)
    short = "astra" if model == "gpt-6-astra" else "sol"
    work = SCRATCH_ROOT / f"run-{run_index}-{short}"
    export_source(work)
    before = file_manifest(work)
    oracle_before = {relative: sha256(work / relative) for relative in ORACLE_FILES}
    load_before = os.getloadavg()
    print(
        f"START model={model} run={run_index} "
        f"loadavg={load_before[0]:.2f},{load_before[1]:.2f},{load_before[2]:.2f}",
        flush=True,
    )
    started = time.time()
    timed_out = False
    try:
        completed = subprocess.run(
            codex_command(work, model, (work / "TASK.md").read_text(), "medium"),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
        rc, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        rc = 124
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    wall = time.time() - started
    load_after = os.getloadavg()
    print(
        f"END model={model} run={run_index} wall={wall:.1f}s "
        f"loadavg={load_after[0]:.2f},{load_after[1]:.2f},{load_after[2]:.2f}",
        flush=True,
    )

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"events-{artifact_label or f'{run_index}-{short}'}.jsonl"
    raw_path.write_text(stdout, encoding="utf-8")
    events = load_events(stdout)
    usage = usage_from_events(events)
    cost = computed_cost_usd(model, usage) if usage else {
        "cost_source": "missing_usage_void", "cost_usd": 0.0,
    }
    check = subprocess.run(
        oracle_command(), cwd=work, capture_output=True, text=True, timeout=180
    )
    after = file_manifest(work)
    changed = changed_paths(before, after)
    oracle_after = {relative: sha256(work / relative) for relative in ORACLE_FILES}
    source_hash_after = source_fixture_hash()
    oracle_hash_after = oracle_bundle_hash()
    binary_after = binary_identity()
    item_types = Counter(
        (event.get("item") or {}).get("type")
        for event in events if event.get("type") == "item.completed"
    )
    scope_ok = set(changed).issubset(ALLOWED_PRODUCTION)
    accepted = bool(
        rc == 0 and check.returncode == 0 and oracle_before == oracle_after
        and frozen_source_hash == source_hash_after and frozen_oracle_hash == oracle_hash_after
        and frozen_binary == binary_after and scope_ok and float(cost["cost_usd"]) > 0
    )
    return {
        "model": model, "run": run_index, "rc": rc, "timed_out": timed_out,
        "wall_s": round(wall, 3), "loadavg_before": list(load_before),
        "loadavg_after": list(load_after), "usage": usage, **cost,
        "item_types": dict(item_types),
        "tool_items": sum(
            count for kind, count in item_types.items()
            if kind not in {"agent_message", "reasoning"}
        ),
        "oracle_rc": check.returncode,
        "oracle_output": (check.stdout + check.stderr)[-8000:],
        "changed_paths": changed, "scope_ok": scope_ok,
        "scratch_oracle_hashes_before": oracle_before,
        "scratch_oracle_hashes_after": oracle_after,
        "scratch_oracle_untouched": oracle_before == oracle_after,
        "source_fixture_hash_before": frozen_source_hash,
        "source_fixture_hash_after": source_hash_after,
        "source_fixture_untouched": frozen_source_hash == source_hash_after,
        "oracle_bundle_hash_before": frozen_oracle_hash,
        "oracle_bundle_hash_after": oracle_hash_after,
        "oracle_bundle_untouched": frozen_oracle_hash == oracle_hash_after,
        "binary_identity_before_batch": frozen_binary,
        "binary_identity_after_run": binary_after,
        "binary_unchanged": frozen_binary == binary_after,
        "accepted": accepted, "stderr_tail": stderr[-1000:],
        "events_path": str(raw_path.relative_to(TASK_DIR)),
    }


def run_reasoning_control(
    frozen_source_hash: str,
    frozen_oracle_hash: str,
    frozen_binary: dict[str, str],
) -> dict[str, Any]:
    assert_binary_identity(frozen_binary)
    work = SCRATCH_ROOT / "reasoning-control-astra"
    export_source(work)
    completed = subprocess.run(
        codex_command(work, "gpt-6-astra", REASONING_CONTROL_PROMPT, "high"),
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600,
    )
    usage = usage_from_events(load_events(completed.stdout))
    binary_after = binary_identity()
    return {
        "model": "gpt-6-astra",
        "purpose": "reasoning-token-channel control; excluded from A/B economics",
        "rc": completed.returncode, "loadavg": list(os.getloadavg()), "usage": usage,
        **(computed_cost_usd("gpt-6-astra", usage) if usage else {}),
        "source_fixture_untouched": frozen_source_hash == source_fixture_hash(),
        "oracle_bundle_untouched": frozen_oracle_hash == oracle_bundle_hash(),
        "binary_identity_after_run": binary_after,
        "binary_unchanged": frozen_binary == binary_after,
        "stderr_tail": completed.stderr[-1000:],
    }


def summarize(
    results: list[dict[str, Any]],
    setup_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    setup_attempts = setup_attempts or []
    by_model = {model: [r for r in results if r["model"] == model] for model in MODELS}
    setup_by_model = {
        model: [r for r in setup_attempts if r["model"] == model] for model in MODELS
    }
    models: dict[str, Any] = {}
    qualified = True
    all_accepted = True
    for model, rows in by_model.items():
        accepted_count = sum(bool(row["accepted"]) for row in rows)
        accepted_costs = [float(row["cost_usd"]) for row in rows]
        setup_costs = [float(row["cost_usd"]) for row in setup_by_model[model]]
        all_costs = setup_costs + accepted_costs
        output_shares = [
            float(row.get("output_usd", 0)) / float(row["cost_usd"])
            if float(row["cost_usd"]) > 0 else 0.0 for row in rows
        ]
        long_checks = {
            "median_wall_at_least_180s": statistics.median(r["wall_s"] for r in rows) >= 180,
            "median_tool_items_at_least_8": statistics.median(r["tool_items"] for r in rows) >= 8,
            "median_output_tokens_at_least_5000": statistics.median(
                r["usage"].get("output_tokens", 0) for r in rows
            ) >= 5000,
        }
        qualified = qualified and all(long_checks.values())
        all_accepted = all_accepted and accepted_count == RUNS
        models[model] = {
            "attempts": len(rows) + len(setup_by_model[model]),
            "task_attempts": len(rows),
            "setup_failures": len(setup_by_model[model]),
            "accepted": accepted_count,
            "setup_failure_cost_usd": sum(setup_costs),
            "total_cost_usd_all_attempts": sum(all_costs),
            "dollars_per_accepted_result": (
                sum(all_costs) / accepted_count if accepted_count else None
            ),
            "accepted_run_cost_range_usd": (
                [min(accepted_costs), max(accepted_costs)]
                if accepted_count == RUNS else None
            ),
            "median_output_cost_share": statistics.median(output_shares),
            "long_qualification": long_checks,
        }

    verdict = "question_open"
    reason = "long-work qualification or 3/3 acceptance failed"
    if qualified and all_accepted:
        astra = [float(row["cost_usd"]) for row in by_model["gpt-6-astra"]]
        sol = [float(row["cost_usd"]) for row in by_model["gpt-5.6-sol"]]
        if max(astra) < min(sol):
            verdict = "astra_better"
            reason = "Astra dollar range is strictly below Sol and both are 3/3 accepted"
        elif max(sol) < min(astra):
            verdict = "sol_better"
            reason = "Sol dollar range is strictly below Astra and both are 3/3 accepted"
        else:
            verdict = "depends_overlapping_ranges"
            reason = "both are 3/3 accepted, but per-run dollar ranges overlap"
    return {
        "metric": "sum(cost_usd for all attempts) / accepted results",
        "cost_source": "computed_vendor_card; standalone codex exec bypasses turn_usage",
        "models": models, "long_work_qualified": qualified,
        "all_runs_accepted": all_accepted, "verdict": verdict, "reason": reason,
    }


def design_record(
    source_hash: str,
    oracle_hash: str,
    binary: dict[str, str],
) -> dict[str, Any]:
    return {
        "base_commit": BASE_COMMIT,
        "fixed_reference_commit": FIX_COMMIT,
        "models": list(MODELS),
        "runs_per_model": RUNS,
        "order": "A/B/A/B/A/B",
        "effort": "medium",
        "project_doc_max_bytes": 262144,
        "source_fixture_sha256": source_hash,
        "oracle_bundle_sha256": oracle_hash,
        "assignment_sha256": sha256(CANDIDATE_TASK),
        "codex_binary": binary,
        "prices_usd_per_million": PRICES,
        "fast_mode_disabled": True,
        "pool_percentage_measured": False,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def first_run_checks(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted": bool(row["accepted"]),
        "wall_at_least_180s": float(row["wall_s"]) >= 180,
        "tool_items_at_least_8": int(row["tool_items"]) >= 8,
        "output_tokens_at_least_5000": int(
            row.get("usage", {}).get("output_tokens", 0)
        ) >= 5000,
        "nonzero_computed_cost": bool(
            row.get("cost_source") == "computed_vendor_card"
            and float(row.get("cost_usd") or 0) > 0
        ),
        "binary_unchanged": bool(row.get("binary_unchanged")),
    }


def execute_first_run() -> None:
    verify_price_registration()
    if PARTIAL_RESULT.exists() or FINAL_RESULT.exists():
        raise SystemExit(
            "FIRST_RUN_ALREADY_RECORDED: preserve paid evidence; do not overwrite or rerun"
        )
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    source_hash = source_fixture_hash()
    oracle_hash = oracle_bundle_hash()
    binary = binary_identity()
    write_json(BATCH_IDENTITY, binary)
    preflight = isolation_preflight(source_hash, oracle_hash, binary)
    write_json(PREFLIGHT_RESULT, preflight)
    row = run_candidate(
        "gpt-6-astra", 0, source_hash, oracle_hash, binary,
    )
    row["attempt_kind"] = "task_attempt"
    checks = first_run_checks(row)
    checkpoint = {
        "design": design_record(source_hash, oracle_hash, binary),
        "preflight": preflight,
        "results": [row],
        "first_run_checks": checks,
        "continue_recommended": all(checks.values()),
    }
    write_json(PARTIAL_RESULT, checkpoint)
    print("PREFLIGHT " + json.dumps(preflight, ensure_ascii=False), flush=True)
    print("RUN1 " + json.dumps({
        "accepted": row["accepted"],
        "wall_s": row["wall_s"],
        "tool_items": row["tool_items"],
        "output_tokens": row.get("usage", {}).get("output_tokens", 0),
        "cost_usd": row["cost_usd"],
        "checks": checks,
        "continue_recommended": checkpoint["continue_recommended"],
    }, ensure_ascii=False), flush=True)


def retry_first_after_harness_fix() -> None:
    verify_price_registration()
    if FINAL_RESULT.exists() or not PARTIAL_RESULT.exists() or not BATCH_IDENTITY.exists():
        raise SystemExit("HARNESS_RETRY_STATE_INVALID: stopped run-1 evidence is required")
    old = json.loads(PARTIAL_RESULT.read_text())
    binary = json.loads(BATCH_IDENTITY.read_text())
    assert_binary_identity(binary)
    old_results = old.get("results") or []
    if not (
        len(old_results) == 1
        and old_results[0].get("model") == "gpt-6-astra"
        and old_results[0].get("run") == 0
        and not old_results[0].get("accepted")
        and not old.get("continue_recommended")
    ):
        raise SystemExit("HARNESS_RETRY_STATE_INVALID: expected one stopped Astra run 0")
    old_attempt = old_results[0]
    old_attempt["attempt_kind"] = "harness_failure"
    old_attempt["failure_classification"] = (
        "nested Codex bwrap could not create a namespace inside the outer bwrap"
    )
    setup_attempts = list(old.get("setup_attempts") or []) + [old_attempt]
    design = old["design"]
    source_hash = str(design["source_fixture_sha256"])
    oracle_hash = str(design["oracle_bundle_sha256"])
    if source_hash != source_fixture_hash() or oracle_hash != oracle_bundle_hash():
        raise SystemExit("FROZEN_FIXTURE_CHANGED: stop before retrying the paid run")
    preflight = isolation_preflight(source_hash, oracle_hash, binary)
    write_json(PREFLIGHT_RESULT, preflight)
    row = run_candidate(
        "gpt-6-astra", 0, source_hash, oracle_hash, binary,
        artifact_label="0-astra-retry1",
    )
    row["attempt_kind"] = "task_attempt"
    checks = first_run_checks(row)
    checkpoint = {
        "design": design,
        "preflight": preflight,
        "setup_attempts": setup_attempts,
        "results": [row],
        "first_run_checks": checks,
        "continue_recommended": all(checks.values()),
        "cost_including_setup_failure_usd": (
            sum(float(item["cost_usd"]) for item in setup_attempts)
            + float(row["cost_usd"])
        ),
    }
    write_json(PARTIAL_RESULT, checkpoint)
    print("PREFLIGHT " + json.dumps(preflight, ensure_ascii=False), flush=True)
    print("RUN1_RETRY " + json.dumps({
        "accepted": row["accepted"],
        "wall_s": row["wall_s"],
        "tool_items": row["tool_items"],
        "output_tokens": row.get("usage", {}).get("output_tokens", 0),
        "cost_usd": row["cost_usd"],
        "setup_failure_cost_usd": sum(
            float(item["cost_usd"]) for item in setup_attempts
        ),
        "cost_including_setup_failure_usd": checkpoint[
            "cost_including_setup_failure_usd"
        ],
        "checks": checks,
        "continue_recommended": checkpoint["continue_recommended"],
    }, ensure_ascii=False), flush=True)


def execute_open_first_run() -> None:
    verify_price_registration()
    if FINAL_RESULT.exists() or not PARTIAL_RESULT.exists() or not BATCH_IDENTITY.exists():
        raise SystemExit("OPEN_REREGISTRATION_STATE_INVALID: prior variants are required")
    old = json.loads(PARTIAL_RESULT.read_text())
    binary = json.loads(BATCH_IDENTITY.read_text())
    assert_binary_identity(binary)
    closed_results = old.get("results") or []
    if not (
        len(closed_results) == 1
        and closed_results[0].get("model") == "gpt-6-astra"
        and closed_results[0].get("run") == 0
        and closed_results[0].get("accepted") is True
        and old.get("continue_recommended") is False
    ):
        raise SystemExit(
            "OPEN_REREGISTRATION_STATE_INVALID: expected one accepted-but-short closed run"
        )
    overhead = list(old.get("setup_attempts") or [])
    for item in overhead:
        item["included_in_open_ab"] = False
        item["exclusion_reason"] = "harness_defect"
    closed = closed_results[0]
    closed["included_in_open_ab"] = False
    closed["exclusion_reason"] = "closed_assignment_variant"
    overhead.append(closed)
    overhead_cost = sum(float(item["cost_usd"]) for item in overhead)
    if abs(overhead_cost - 2.376104) > 1e-9:
        raise SystemExit(
            f"OVERHEAD_LEDGER_MISMATCH: expected 2.376104, got {overhead_cost:.9f}"
        )

    source_hash = source_fixture_hash()
    oracle_hash = oracle_bundle_hash()
    design = design_record(source_hash, oracle_hash, binary)
    design["assignment_variant"] = "open_red_oracle_only"
    preflight = isolation_preflight(source_hash, oracle_hash, binary)
    write_json(PREFLIGHT_RESULT, preflight)
    row = run_candidate(
        "gpt-6-astra", 0, source_hash, oracle_hash, binary,
        artifact_label="open-0-astra",
    )
    row["attempt_kind"] = "open_task_attempt"
    checks = first_run_checks(row)
    checkpoint = {
        "design": design,
        "preflight": preflight,
        "experiment_overhead_attempts": overhead,
        "experiment_overhead_cost_usd": overhead_cost,
        "results": [row],
        "first_run_checks": checks,
        "continue_recommended": all(checks.values()),
    }
    write_json(PARTIAL_RESULT, checkpoint)
    print("PREFLIGHT " + json.dumps(preflight, ensure_ascii=False), flush=True)
    print("OPEN_RUN1 " + json.dumps({
        "accepted": row["accepted"],
        "wall_s": row["wall_s"],
        "tool_items": row["tool_items"],
        "output_tokens": row.get("usage", {}).get("output_tokens", 0),
        "cost_usd": row["cost_usd"],
        "experiment_overhead_cost_usd": overhead_cost,
        "checks": checks,
        "continue_recommended": checkpoint["continue_recommended"],
    }, ensure_ascii=False), flush=True)


def execute_remaining_runs() -> None:
    verify_price_registration()
    if FINAL_RESULT.exists():
        raise SystemExit("FINAL_RESULT_EXISTS: preserve paid evidence; do not rerun")
    if not PARTIAL_RESULT.exists() or not BATCH_IDENTITY.exists():
        raise SystemExit("FIRST_RUN_MISSING: run the checkpoint stage first")
    checkpoint = json.loads(PARTIAL_RESULT.read_text())
    binary = json.loads(BATCH_IDENTITY.read_text())
    assert_binary_identity(binary)
    results = checkpoint.get("results") or []
    if not (
        len(results) == 1
        and results[0].get("model") == "gpt-6-astra"
        and results[0].get("run") == 0
    ):
        raise SystemExit("FIRST_RUN_INVALID: partial evidence does not contain only Astra run 0")
    if not checkpoint.get("continue_recommended"):
        raise SystemExit("FIRST_RUN_STOP_RULE: checkpoint failed; five more runs are forbidden")
    design = checkpoint["design"]
    source_hash = str(design["source_fixture_sha256"])
    oracle_hash = str(design["oracle_bundle_sha256"])
    if (
        source_hash != source_fixture_hash()
        or oracle_hash != oracle_bundle_hash()
        or design.get("assignment_sha256") != sha256(CANDIDATE_TASK)
    ):
        raise SystemExit("FROZEN_FIXTURE_CHANGED: stop before continuing the paid batch")

    for run_index, model in RUN_SEQUENCE[1:]:
        assert_binary_identity(binary)
        row = run_candidate(model, run_index, source_hash, oracle_hash, binary)
        row["attempt_kind"] = "task_attempt"
        results.append(row)
        checkpoint["results"] = results
        write_json(PARTIAL_RESULT, checkpoint)
        if not row.get("binary_unchanged"):
            raise SystemExit("CODEX_BINARY_CHANGED: result preserved; stop mixed-binary batch")
        if row.get("cost_source") != "computed_vendor_card" or row["cost_usd"] <= 0:
            raise SystemExit("VOID_RUN: result preserved; missing or zero cost is invalid")

    controls: list[dict[str, Any]] = []
    astra_with_usage = [
        row for row in results
        if row["model"] == "gpt-6-astra" and row.get("usage")
    ]
    if astra_with_usage and all(
        int(row["usage"].get("reasoning_tokens", 0)) == 0
        for row in astra_with_usage
    ):
        controls.append(run_reasoning_control(source_hash, oracle_hash, binary))
    payload = {
        "design": design,
        "preflight": checkpoint["preflight"],
        "experiment_overhead_attempts": checkpoint.get("experiment_overhead_attempts") or [],
        "experiment_overhead_cost_usd": checkpoint.get("experiment_overhead_cost_usd", 0),
        "results": results,
        "reasoning_controls": controls,
        "summary": summarize(results),
    }
    write_json(FINAL_RESULT, payload)
    PARTIAL_RESULT.unlink()
    BATCH_IDENTITY.unlink()
    PREFLIGHT_RESULT.unlink()
    print(json.dumps(payload["summary"], indent=2), flush=True)


def dry_run() -> None:
    manifest = json.loads(ORACLE_MANIFEST.read_text())
    print(json.dumps({
        "paid_calls": 0, "base_commit": BASE_COMMIT,
        "fixed_reference_commit": FIX_COMMIT, "models": list(MODELS),
        "order": [model for _ in range(RUNS) for model in MODELS], "effort": "medium",
        "project_doc_max_bytes": 262144,
        "oracle_bundle_sha256": oracle_bundle_hash(), "oracle_files": manifest["files"],
        "source_fixture_sha256": source_fixture_hash(), "scratch_root": str(SCRATCH_ROOT),
        "source_repository_masked_in_bwrap": "/mnt/data/Projects/Python/orchestra",
        "cost_source": "computed_vendor_card",
        "turn_usage_reason": (
            "standalone codex exec is outside Orchestra SessionManager/session_turns and "
            "therefore creates no attributable turn_usage row"
        ),
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    paid = parser.add_mutually_exclusive_group()
    paid.add_argument(
        "--execute-first-paid-run", action="store_true",
        help="Run the fresh preflight and Astra run 0, then stop for the required report.",
    )
    paid.add_argument(
        "--continue-paid-runs", action="store_true",
        help="Continue the unchanged batch after a qualifying recorded Astra run 0.",
    )
    paid.add_argument(
        "--retry-first-after-harness-fix", action="store_true",
        help="Preserve the nested-sandbox failure cost, rerun preflight, and retry Astra run 0.",
    )
    paid.add_argument(
        "--execute-open-first-run", action="store_true",
        help="Ledger both prior variants as overhead, then execute open-assignment Astra run 0.",
    )
    args = parser.parse_args()
    if args.execute_first_paid_run:
        execute_first_run()
        return
    if args.continue_paid_runs:
        execute_remaining_runs()
        return
    if args.retry_first_after_harness_fix:
        retry_first_after_harness_fix()
        return
    if args.execute_open_first_run:
        execute_open_first_run()
        return
    if not (
        args.execute_first_paid_run
        or args.continue_paid_runs
        or args.retry_first_after_harness_fix
        or args.execute_open_first_run
    ):
        dry_run()


if __name__ == "__main__":
    main()
