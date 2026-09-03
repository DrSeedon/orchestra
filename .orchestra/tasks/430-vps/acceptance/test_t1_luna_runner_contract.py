from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "scripts/skillstate430/run_luna_benchmark.py"


def test_t1_luna_runner_contract() -> None:
    assert RUNNER.is_file(), "T1 missing stateless Luna runner"
    api = runpy.run_path(str(RUNNER))
    required = {
        "audit_db_trace",
        "build_codex_argv",
        "build_rendered_request",
        "parse_fenced_json_output",
        "validate_state_patch",
        "parse_turn_usage",
    }
    assert required <= set(api), f"T1 missing runner API: {sorted(required - set(api))}"

    argv = api["build_codex_argv"](
        model="gpt-5.6-luna",
        scratch_dir="/tmp/skillstate430-empty",
        output_message="/tmp/skillstate430-last.json",
    )
    joined = " ".join(argv)
    for token in (
        "codex exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "--skip-git-repo-check",
        "--sandbox read-only",
        "--model gpt-5.6-luna",
        "--output-last-message",
        "--cd /tmp/skillstate430-empty",
    ):
        assert token in joined, f"T1 Luna argv missing {token!r}: {joined}"
    assert "resume" not in argv, "T1 must start a fresh Codex thread for every step"
    assert "--output-schema" not in argv, "T1 Appendix A.4 replica must not add provider structured output"
    assert argv[-1] == "-", "T1 rendered prompt must arrive via stdin"
    for flag in ("--cd", "--output-last-message"):
        value = argv[argv.index(flag) + 1]
        assert Path(value).is_absolute(), f"T1 {flag} must be absolute before Codex changes cwd: {value}"

    parsed = api["parse_fenced_json_output"](
        "Reasoning is discarded.\n```json\n{\"state_patch\":{},\"action\":{\"kind\":\"continue\"}}\n```"
    )
    assert set(parsed) == {"state_patch", "action"}
    with pytest.raises(ValueError, match="malformed_output"):
        api["parse_fenced_json_output"]("no fenced JSON here")
    with pytest.raises(ValueError, match="malformed_output"):
        api["parse_fenced_json_output"]("```json\n{bad json}\n```")
    with pytest.raises(ValueError, match="malformed_output"):
        api["parse_fenced_json_output"](
            "```json\n{\"state_patch\":{},\"action\":{}}\n```\n```json\n{}\n```"
        )

    action_schema = {
        "type": "object",
        "properties": {
            "decision": {"enum": ["KEEP_FTS", "DELETE_CURRENT_DB"]},
            "tags": {"type": "array", "items": {"type": "string"}, "x-normalization": "sorted_set"},
        },
        "required": ["decision", "tags"],
        "additionalProperties": False,
    }
    tool_manifest = {"actions": ["continue", "finalize"], "external_tools": []}
    controller = {"patch": "recursive_merge_v1", "temperature": 0, "reasoning_effort": "low"}
    common = {
        "skill_spec": "Preserve current facts and rejected decisions with reasons.",
        "state": {"objective": "decide", "decisions": {}},
        "latest_observation": {"event_id": "E01", "text": "candidate"},
        "history": [{"event_id": "E00", "text": "baseline"}],
        "action_schema": action_schema,
        "tool_manifest": tool_manifest,
        "controller_params": controller,
    }
    append = api["build_rendered_request"](memory_mode="append", **common)
    state = api["build_rendered_request"](memory_mode="state", **common)
    for key in ("common_surface_hash", "action_schema_hash", "tool_manifest_hash", "controller_params_hash"):
        assert append[key] == state[key], f"T1 controllable surface differs at {key}"
    assert append["memory_payload_hash"] != state["memory_payload_hash"]
    for literal in ("KEEP_FTS", "DELETE_CURRENT_DB", "sorted_set", "continue", "finalize"):
        assert literal in append["rendered_prompt"] and literal in state["rendered_prompt"], (
            f"T1 rendered prompt omits disclosed enum/normalizer/action {literal}"
        )

    initial = {
        "objective": "decide",
        "current_facts": {},
        "decisions": {"D1": {"status": "rejected", "because": "wrong store", "evidence_events": ["E1"]}},
        "open_questions": {},
        "artifacts": {},
        "next_action": "continue",
    }
    valid = api["validate_state_patch"](initial, {"current_facts": {"F1": {"value": 6, "status": "current", "evidence_event": "E2"}}})
    assert valid["current_facts"]["F1"]["value"] == 6
    with pytest.raises(ValueError, match="decision"):
        api["validate_state_patch"](initial, {"decisions": {"D1": None}})
    with pytest.raises(ValueError, match="unknown"):
        api["validate_state_patch"](initial, {"private_reasoning": "must not persist"})

    usage = api["parse_turn_usage"]([
        {"type": "turn.completed", "usage": {
            "input_tokens": 100,
            "cached_input_tokens": 60,
            "output_tokens": 20,
            "reasoning_output_tokens": 5,
        }}
    ])
    assert usage == {
        "input_tokens": 100,
        "cached_input_tokens": 60,
        "output_tokens": 20,
        "reasoning_output_tokens": 5,
        "total_tokens": 120,
    }, "T1 reasoning tokens are a subset of output_tokens and must not be double-counted"

    protected = [
        "/home/kesha/orchestra/data/orchestra.db",
        "/home/kesha/orchestra/data/orchestra.db-wal",
        "/home/kesha/orchestra/data/orchestra.db-shm",
    ]
    clean = api["audit_db_trace"](
        ['openat(AT_FDCWD, "/home/kesha/orchestra/data/orchestra.db", O_RDONLY|O_CLOEXEC) = 3'],
        protected,
    )
    assert clean["write_syscalls"] == 0
    with pytest.raises(ValueError, match="production DB write"):
        api["audit_db_trace"](
            ['openat(AT_FDCWD, "/home/kesha/orchestra/data/orchestra.db-wal", O_RDWR|O_CREAT) = 4'],
            protected,
        )
