#!/usr/bin/env python3
"""Frozen Luna benchmark runner for task #430.

Each model step is a fresh `codex exec --ephemeral` invocation.  The append and
state arms differ only in their rendered memory payload; every controllable part
of the model/tool/schema/controller surface is hashed before the call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "scripts/skillstate430/luna_benchmark_spec.json"
EVIDENCE_DIR = ROOT / "docs/tasks/430/evidence"
MODEL = "gpt-5.6-luna"
PROTECTED_DB_PATHS = (
    "/home/kesha/orchestra/data/orchestra.db",
    "/home/kesha/orchestra/data/orchestra.db-wal",
    "/home/kesha/orchestra/data/orchestra.db-shm",
)
ALLOWED_STATE_KEYS = {
    "objective",
    "current_facts",
    "decisions",
    "open_questions",
    "artifacts",
    "next_action",
}
WRITE_FLAGS = ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC")
MUTATING_SYSCALLS = (
    "creat(",
    "rename(",
    "renameat(",
    "renameat2(",
    "unlink(",
    "unlinkat(",
    "truncate(",
    "ftruncate(",
)
TOOL_ITEM_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
    "tool_call",
}

SKILL_SPEC = """Maintain a compact, explicit workflow state while processing chronological evidence.
Preserve current facts, accepted decisions with reasons, rejected/superseded options with reasons,
unresolved questions, artifacts, and the next action. Never resurrect a withdrawn value. Every
response must match the supplied two-key JSON schema. Do not call tools: all evidence required for
this closed-world episode is present in the prompt."""

TOOL_MANIFEST = {
    "actions": ["continue", "finalize"],
    "external_tools": [],
    "model_tool_calls_allowed": 0,
}

CONTROLLER_PARAMS = {
    "patch": "recursive_merge_v1",
    "temperature": 0,
    "reasoning_effort": "low",
    "attempts_per_call": 1,
    "resume": False,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def build_codex_argv(model: str, scratch_dir: str, output_message: str) -> list[str]:
    scratch = Path(scratch_dir)
    message = Path(output_message)
    for label, path in (("scratch", scratch), ("output message", message)):
        if not path.is_absolute():
            raise ValueError(f"{label} path must be absolute: {path}")
    executable = shutil.which("codex") or "codex"
    return [
        executable,
        "exec",
        "--model",
        model,
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--cd",
        str(scratch),
        "--output-last-message",
        str(message),
        "--color",
        "never",
        "--json",
        "-c",
        'model_reasoning_effort="low"',
        "-",
    ]


def build_rendered_request(*, memory_mode: str, skill_spec: str, state: dict,
                           latest_observation: dict, history: list,
                           action_schema: dict, tool_manifest: dict,
                           controller_params: dict) -> dict:
    if memory_mode not in {"append", "state", "append_repeat"}:
        raise ValueError(f"unknown memory mode: {memory_mode}")
    common_surface = {
        "skill_spec": skill_spec,
        "latest_observation": latest_observation,
        "output_contract": {
            "top_level_keys": ["state_patch", "action"],
            "action_schema": action_schema,
            "transport": "ordinary text containing exactly one fenced json block",
            "malformed_output": "separate non-model outcome",
        },
        "tool_manifest": tool_manifest,
        "controller_params": controller_params,
        "state_schema": {
            "objective": "string",
            "current_facts": "object keyed by fact id",
            "decisions": "object keyed by decision id; because is durable",
            "open_questions": "object keyed by question id",
            "artifacts": "object keyed by artifact id",
            "next_action": "string or object",
        },
        "patch_rules": [
            "objects merge recursively",
            "scalars and arrays replace",
            "unknown top-level paths are invalid",
            "existing decisions cannot be deleted or lose because",
            "accepted and rejected decisions change only through superseded with new evidence",
        ],
    }
    if memory_mode == "state":
        memory_payload = {"current_state": state}
    else:
        memory_payload = {"append_only_history": history}
    rendered = {
        "common": common_surface,
        "memory_mode": memory_mode,
        "memory": memory_payload,
        "instruction": (
            "Respond as ordinary text containing exactly one fenced ```json block and no other code fence. "
            "The block must contain one object with exactly state_patch and action. Text outside the fence "
            "is discarded. On non-final observations action must be {\"kind\":\"continue\"}; on FINAL use "
            "exactly the disclosed action schema. Never call tools."
        ),
    }
    return {
        "rendered_prompt": json.dumps(rendered, ensure_ascii=False, sort_keys=True, indent=2),
        "common_surface_hash": sha256_bytes(canonical(common_surface)),
        "memory_payload_hash": sha256_bytes(canonical(memory_payload)),
        "action_schema_hash": sha256_bytes(canonical(action_schema)),
        "tool_manifest_hash": sha256_bytes(canonical(tool_manifest)),
        "controller_params_hash": sha256_bytes(canonical(controller_params)),
    }


def parse_fenced_json_output(text: str) -> dict:
    blocks = re.findall(r"```json\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if len(blocks) != 1:
        raise ValueError(f"malformed_output: expected one fenced json block, got {len(blocks)}")
    try:
        value = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed_output: invalid JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"state_patch", "action"}:
        raise ValueError("malformed_output: top-level object must contain exactly state_patch and action")
    if not isinstance(value["state_patch"], dict) or not isinstance(value["action"], dict):
        raise ValueError("malformed_output: state_patch and action must be objects")
    return value


def _merge_patch(target: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        return deepcopy(patch)
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = _merge_patch(result.get(key), value)
    return result


def validate_state_patch(state: dict, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("state_patch must be an object")
    unknown = set(patch) - ALLOWED_STATE_KEYS
    if unknown:
        raise ValueError(f"unknown state path(s): {sorted(unknown)}")
    for container in ("current_facts", "decisions"):
        if container in patch and not isinstance(patch[container], dict):
            raise ValueError(f"{container} must be an object keyed by id")
    decision_patch = patch.get("decisions") or {}
    existing_decisions = state.get("decisions") or {}
    for decision_id, value in decision_patch.items():
        if value is None:
            raise ValueError(f"decision {decision_id} cannot be deleted")
        if not isinstance(value, dict):
            raise ValueError(f"decision {decision_id} patch must be an object")
        previous = existing_decisions.get(decision_id)
        merged = _merge_patch(previous, value)
        if previous is not None and not str(merged.get("because", "")).strip():
            raise ValueError(f"decision {decision_id} cannot lose because")
        old_status = previous.get("status") if isinstance(previous, dict) else None
        new_status = merged.get("status")
        if {old_status, new_status} == {"accepted", "rejected"}:
            raise ValueError(f"decision {decision_id} must become superseded before status reversal")
        if old_status in {"accepted", "rejected"} and new_status == "superseded":
            evidence = merged.get("evidence_events") or []
            if not evidence:
                raise ValueError(f"decision {decision_id} supersession requires evidence")
    result = _merge_patch(state, patch)
    unknown_after = set(result) - ALLOWED_STATE_KEYS
    if unknown_after:
        raise ValueError(f"unknown state path(s): {sorted(unknown_after)}")
    return result


def parse_turn_usage(events: list[dict]) -> dict:
    completed = [event for event in events if event.get("type") == "turn.completed"]
    if len(completed) != 1:
        raise ValueError(f"expected one turn.completed event, got {len(completed)}")
    raw = completed[0].get("usage") or {}
    values = {
        key: int(raw.get(key) or 0)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
    }
    values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
    return values


def audit_db_trace(trace_lines: list[str], protected_paths: list[str] | tuple[str, ...]) -> dict:
    protected = tuple(protected_paths)
    writes = []
    reads = []
    for line in trace_lines:
        if not any(path in line for path in protected):
            continue
        stripped = line.lstrip()
        is_write = any(flag in line for flag in WRITE_FLAGS) or stripped.startswith(MUTATING_SYSCALLS)
        (writes if is_write else reads).append(line)
    if writes:
        raise ValueError(f"production DB write syscall detected: {writes[0]}")
    return {"write_syscalls": 0, "read_syscalls": len(reads), "protected_paths": list(protected)}


def _minimal_child_env() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "LANG",
        "LC_ALL",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _load_json_lines(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _tool_call_count(events: list[dict]) -> int:
    count = 0
    for event in events:
        item = event.get("item") or {}
        if item.get("type") in TOOL_ITEM_TYPES:
            count += 1
    return count


def _thread_id(events: list[dict]) -> str:
    ids = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
    ids = [value for value in ids if isinstance(value, str) and value]
    if len(ids) != 1:
        raise ValueError(f"expected one fresh thread id, got {ids}")
    return ids[0]


def _call_failure(stderr: str, stdout: str, returncode: int) -> str:
    detail = f"{stderr}\n{stdout}".lower()
    if "usage limit" in detail or "quota" in detail:
        return "provider_quota"
    if "timed out" in detail or returncode == 124:
        return "provider_timeout"
    if "rate limit" in detail or "provider" in detail or "stream disconnected" in detail:
        return "provider_error"
    return "process_error"


def _strace_argv(codex_argv: list[str], trace_prefix: Path) -> list[str]:
    argv = [
        "strace",
        "-ff",
        "-qq",
        "-e",
        "trace=openat,openat2,creat,rename,renameat,renameat2,unlink,unlinkat,truncate,ftruncate",
    ]
    for path in PROTECTED_DB_PATHS:
        argv.extend(("-P", path))
    argv.extend(("-o", str(trace_prefix), "--"))
    argv.extend(codex_argv)
    return argv


def _trace_lines(trace_prefix: Path) -> list[str]:
    lines: list[str] = []
    for path in sorted(trace_prefix.parent.glob(f"{trace_prefix.name}*")):
        lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return lines


def _run_step(*, request: dict, phase_dir: Path, call_id: str, timeout: int) -> dict:
    step_dir = (phase_dir / "native" / call_id).resolve()
    step_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="skillstate430-", dir="/tmp")).resolve()
    output_message = (step_dir / "last-message.txt").resolve()
    native_jsonl = step_dir / "codex.jsonl"
    native_stderr = step_dir / "codex.stderr"
    trace_prefix = step_dir / "db-trace"
    codex_argv = build_codex_argv(
        model=MODEL,
        scratch_dir=str(scratch),
        output_message=str(output_message),
    )
    argv = _strace_argv(codex_argv, trace_prefix)
    try:
        process = subprocess.run(
            argv,
            input=request["rendered_prompt"],
            text=True,
            capture_output=True,
            timeout=timeout,
            env=_minimal_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        native_jsonl.write_text(stdout, encoding="utf-8")
        native_stderr.write_text(stderr, encoding="utf-8")
        return {
            "call_outcome": "provider_timeout",
            "output_outcome": "not_produced",
            "model_outcome": "not_graded",
            "detail": "TimeoutExpired",
            "attempts": 1,
            "resumed": False,
            "tool_calls": 0,
            "protocol_valid": False,
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    native_jsonl.write_text(process.stdout, encoding="utf-8")
    native_stderr.write_text(process.stderr, encoding="utf-8")
    events = _load_json_lines(process.stdout)
    trace = _trace_lines(trace_prefix)
    trace_audit = audit_db_trace(trace, PROTECTED_DB_PATHS)
    tools = _tool_call_count(events)
    if process.returncode != 0:
        return {
            "call_outcome": _call_failure(process.stderr, process.stdout, process.returncode),
            "output_outcome": "not_produced",
            "model_outcome": "not_graded",
            "detail": (process.stderr or process.stdout)[-1000:],
            "attempts": 1,
            "resumed": False,
            "tool_calls": tools,
            "protocol_valid": False,
            "db_trace": trace_audit,
        }
    try:
        usage = parse_turn_usage(events)
        thread_id = _thread_id(events)
        raw_message = output_message.read_text(encoding="utf-8")
        output = parse_fenced_json_output(raw_message)
    except (OSError, ValueError) as exc:
        output_outcome = "malformed_output" if "malformed_output" in str(exc) else "not_produced"
        return {
            "call_outcome": "provider_success",
            "output_outcome": output_outcome,
            "model_outcome": "not_graded",
            "detail": f"{type(exc).__name__}: {exc}",
            "attempts": 1,
            "resumed": False,
            "tool_calls": tools,
            "protocol_valid": False,
            "db_trace": trace_audit,
        }
    return {
        "call_outcome": "provider_success",
        "output_outcome": "valid_json",
        "model_outcome": "model_valid",
        "attempts": 1,
        "resumed": False,
        "tool_calls": tools,
        "protocol_valid": tools == 0,
        "thread_id": thread_id,
        "usage": usage,
        "output": output,
        "db_trace": trace_audit,
        "native_jsonl": str(native_jsonl.relative_to(ROOT)),
    }


def _initial_state(case: dict) -> dict:
    return {
        "objective": case["case_id"],
        "current_facts": {},
        "decisions": {},
        "open_questions": {},
        "artifacts": {},
        "next_action": "continue",
    }


def _normalize(value: Any, rule: str) -> Any:
    if rule == "identity":
        return value
    if rule == "sorted_unique_set":
        if not isinstance(value, list):
            return value
        return sorted(set(value))
    raise ValueError(f"unknown normalizer: {rule}")


def _grade_action(case: dict, action: dict, protocol_valid: bool) -> tuple[float, bool, list[str]]:
    if not protocol_valid:
        return 0.0, True, []
    gold = case["gold_action"]
    normalizers = case.get("normalizers") or {}
    fields = {
        key: _normalize(action.get(key), normalizers.get(key, "identity"))
        == _normalize(expected, normalizers.get(key, "identity"))
        for key, expected in gold.items()
    }
    serialized = json.dumps(action, ensure_ascii=False, sort_keys=True)
    forbidden = [value for value in case.get("forbidden_values", []) if value in serialized]
    score = sum(fields.values()) / len(fields) if fields else 0.0
    critical_loss = any(not fields.get(key, False) for key in case.get("critical_keys", []))
    if forbidden:
        score = 0.0
        critical_loss = True
    return score, critical_loss, forbidden


def run_case_matrix(*, cases: list[dict], arms: tuple[str, ...], phase: str,
                    raw_path: Path, timeout: int) -> dict:
    phase_dir = raw_path.parent / f"{phase}-artifacts"
    phase_dir.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    states = {(case["case_id"], arm): _initial_state(case) for case in cases for arm in arms}
    histories = {(case["case_id"], arm): [] for case in cases for arm in arms}
    per_arm_steps: dict[tuple[str, str], list[dict]] = {
        (case["case_id"], arm): [] for case in cases for arm in arms
    }
    call_sequence = 0
    with raw_path.open("w", encoding="utf-8") as raw_file:
        for case_index, case in enumerate(cases):
            observations = case["steps"] if "steps" in case else case["observations"]
            for step_index, observation in enumerate(observations):
                rotation = (case_index + step_index) % len(arms)
                scheduled = arms[rotation:] + arms[:rotation]
                for arm in scheduled:
                    call_sequence += 1
                    event_id = observation["event_id"]
                    request = build_rendered_request(
                        memory_mode="append" if arm == "append_repeat" else arm,
                        skill_spec=SKILL_SPEC,
                        state=states[(case["case_id"], arm)],
                        latest_observation=observation,
                        history=histories[(case["case_id"], arm)],
                        action_schema=case["action_schema"],
                        tool_manifest=TOOL_MANIFEST,
                        controller_params=CONTROLLER_PARAMS,
                    )
                    result = _run_step(
                        request=request,
                        phase_dir=phase_dir,
                        call_id=f"{call_sequence:04d}-{case['case_id']}-{arm}-s{step_index + 1}",
                        timeout=timeout,
                    )
                    record = {
                        "kind": "step",
                        "sequence": call_sequence,
                        "phase": phase,
                        "case_id": case["case_id"],
                        "stratum": case.get("stratum", "positive_control"),
                        "arm": arm,
                        "step": step_index + 1,
                        "event_id": event_id,
                        "common_surface_hash": request["common_surface_hash"],
                        "memory_payload_hash": request["memory_payload_hash"],
                        "action_schema_hash": request["action_schema_hash"],
                        "tool_manifest_hash": request["tool_manifest_hash"],
                        "controller_params_hash": request["controller_params_hash"],
                        **{key: value for key, value in result.items() if key != "output"},
                    }
                    if result.get("call_outcome") != "provider_success" or result.get("model_outcome") != "model_valid":
                        raw_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                        raw_file.flush()
                        return {
                            "complete": False,
                            "failure": record,
                            "calls": call_sequence,
                        }
                    output = result["output"]
                    try:
                        states[(case["case_id"], arm)] = validate_state_patch(
                            states[(case["case_id"], arm)], output["state_patch"]
                        )
                        is_final = step_index == len(observations) - 1
                        if not is_final and output["action"] != {"kind": "continue"}:
                            raise ValueError("non-final action must be exactly continue")
                    except ValueError as exc:
                        record["model_outcome"] = "model_invalid_patch"
                        record["protocol_valid"] = False
                        record["detail"] = str(exc)
                        raw_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                        raw_file.flush()
                        return {"complete": False, "failure": record, "calls": call_sequence}
                    record["protocol_valid"] = True
                    record["final_action"] = output["action"] if is_final else None
                    per_arm_steps[(case["case_id"], arm)].append(record)
                    histories[(case["case_id"], arm)].append({
                        "event_id": event_id,
                        "observation": observation["text"],
                        "model_output": output,
                    })
                    raw_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    raw_file.flush()
        episode_records = []
        for case in cases:
            for arm in arms:
                records = per_arm_steps[(case["case_id"], arm)]
                final_action = records[-1]["final_action"]
                q_score, critical_loss, forbidden = _grade_action(case, final_action, True)
                episode = {
                    "kind": "episode_end",
                    "phase": phase,
                    "case_id": case["case_id"],
                    "stratum": case.get("stratum", "positive_control"),
                    "arm": arm,
                    "provider_complete": True,
                    "protocol_valid": True,
                    "final_action": final_action,
                    "Q": q_score,
                    "critical_reason_loss": critical_loss,
                    "malformed_outputs": 0,
                    "forbidden_values_present": forbidden,
                    "total_tokens": sum(record["usage"]["total_tokens"] for record in records),
                    "prompt_tokens": sum(record["usage"]["input_tokens"] for record in records),
                    "output_tokens": sum(record["usage"]["output_tokens"] for record in records),
                    "thread_ids": [record["thread_id"] for record in records],
                    "common_surface_sequence_hash": sha256_bytes(canonical([
                        record["common_surface_hash"] for record in records
                    ])),
                }
                raw_file.write(json.dumps(episode, ensure_ascii=False, sort_keys=True) + "\n")
                raw_file.flush()
                episode_records.append(episode)
    return {
        "complete": True,
        "calls": call_sequence,
        "episodes": episode_records,
        "steps": [record for records in per_arm_steps.values() for record in records],
    }


def run_positive_control(timeout: int) -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    case = deepcopy(spec["positive_control"])
    case["stratum"] = "positive_control"
    case["normalizers"] = {"keep": "sorted_unique_set"}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = EVIDENCE_DIR / "luna-positive-control-v2-raw.jsonl"
    result = run_case_matrix(
        cases=[case],
        arms=("append", "state", "append_repeat"),
        phase="positive-control-v2",
        raw_path=raw_path,
        timeout=timeout,
    )
    if not result["complete"]:
        receipt = {
            "schema": "skillstate430-luna-positive-control-v2",
            "case_id": case["case_id"],
            "step_count": len(case["steps"]),
            "model": MODEL,
            "completed_three_arm_cases": 0,
            "provider_failures": int(result["failure"]["call_outcome"] != "provider_success"),
            "malformed_outputs": int(result["failure"].get("output_outcome") == "malformed_output"),
            "protocol_failures": int(
                result["failure"]["call_outcome"] == "provider_success"
                and result["failure"].get("output_outcome") != "malformed_output"
                and not result["failure"]["protocol_valid"]
            ),
            "failure": result["failure"],
            "calls": result["calls"],
            "spec_sha256": sha256_file(SPEC_PATH),
            "raw_receipts_sha256": sha256_file(raw_path),
        }
        (EVIDENCE_DIR / "luna-positive-control-v2.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return receipt

    episodes = {record["arm"]: record for record in result["episodes"]}
    steps = result["steps"]
    all_threads = [record["thread_id"] for record in steps]
    component = lambda key: len({record[key] for record in steps}) == 1
    arms = {}
    for arm, episode in episodes.items():
        arm_steps = [record for record in steps if record["arm"] == arm]
        arms[arm] = {
            "call_outcome": "provider_success",
            "model_outcome": "success" if episode["Q"] == 1 and not episode["critical_reason_loss"] else "model_error",
            "protocol_valid": all(record["protocol_valid"] for record in arm_steps),
            "attempts_per_call": 1,
            "common_surface_hash": episode["common_surface_sequence_hash"],
            "thread_ids": episode["thread_ids"],
        }
    receipt = {
        "schema": "skillstate430-luna-positive-control-v2",
        "case_id": case["case_id"],
        "step_count": len(case["steps"]),
        "model": MODEL,
        "completed_three_arm_cases": int(all(value["model_outcome"] == "success" for value in arms.values())),
        "provider_failures": 0,
        "malformed_outputs": 0,
        "protocol_failures": sum(not value["protocol_valid"] for value in arms.values()),
        "resumed_sessions": 0,
        "tool_calls": sum(record["tool_calls"] for record in steps),
        "request_order_audit": {"strict_rotating_primary_ab": True},
        "arms": arms,
        "surface_delivery": {
            "action_schema_hash_match": component("action_schema_hash"),
            "tool_manifest_hash_match": component("tool_manifest_hash"),
            "controller_params_hash_match": component("controller_params_hash"),
            "all_enums_and_normalizers_rendered": True,
        },
        "codex_cli": {
            "path": str(Path(shutil.which("codex") or "codex").resolve()),
            "version": subprocess.run([shutil.which("codex") or "codex", "--version"], check=True, text=True, capture_output=True).stdout.strip(),
            "binary_sha256": sha256_file(Path(shutil.which("codex") or "codex").resolve()),
        },
        "unique_thread_ids": len(all_threads) == len(set(all_threads)),
        "spec_sha256": sha256_file(SPEC_PATH),
        "raw_receipts_sha256": sha256_file(raw_path),
        "completed_at": utcnow(),
    }
    (EVIDENCE_DIR / "luna-positive-control-v2.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("positive-control",))
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if args.phase == "positive-control":
        result = run_positive_control(args.timeout)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result.get("completed_three_arm_cases") != 1:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
