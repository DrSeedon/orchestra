"""Frozen RED oracle for #303 Release D (scoped env, guards, and observability)."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_support import (  # noqa: E402
    assert_bound_consumed_attestation,
    sha256_path,
    trusted_artifact,
    trusted_service_source,
)


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ONLY_KEYS = {
    "INTERNAL_TOKEN",
    "VIRTUAL_ENV",
    "UV_PROJECT_ENVIRONMENT",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GROK_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
}
BYPASSES = {
    "inherited_active_venv",
    "inline_absolute_uv_project_environment",
    "uv_venv_clear",
    "uv_pip_absolute_python",
    "symlink_alias",
    "absolute_uv",
    "direct_python_write",
    "sudo",
}


def _load(relative: str, name: str):
    path = ROOT / relative
    assert path.is_file(), f"T-D missing behavior: {relative} does not exist"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_td_worker_and_each_mcp_server_receive_only_their_scoped_environment(tmp_path):
    runtime_env = _load("app/runtime_env.py", "task303_runtime_env")
    source = {
        "PATH": "/service/.venv/bin:/usr/bin:/bin",
        "HOME": "/home/service",
        "LANG": "C.UTF-8",
        "HTTPS_PROXY": "http://proxy.invalid",
        **{key: f"canary-{key}" for key in SERVICE_ONLY_KEYS},
    }
    worker = runtime_env.build_worker_env(
        source,
        home=str(tmp_path / "worker-home"),
        path="/usr/bin:/bin",
    )
    assert not SERVICE_ONLY_KEYS.intersection(worker)
    assert set(worker) <= set(runtime_env.WORKER_ENV_ALLOWLIST)
    assert worker["HOME"] == str(tmp_path / "worker-home")
    assert worker["PATH"] == "/usr/bin:/bin"

    server_a = runtime_env.build_mcp_server_env(
        source,
        server_env={"SERVER_A_TOKEN": "a-canary", "INTERNAL_TOKEN": "override"},
        capability="cap-a",
        home=str(tmp_path / "mcp-a"),
        path="/usr/bin:/bin",
    )
    server_b = runtime_env.build_mcp_server_env(
        source,
        server_env={"SERVER_B_TOKEN": "b-canary"},
        capability="cap-b",
        home=str(tmp_path / "mcp-b"),
        path="/usr/bin:/bin",
    )
    assert "INTERNAL_TOKEN" not in server_a and "INTERNAL_TOKEN" not in server_b
    assert server_a["ORCHESTRA_CAPABILITY"] == "cap-a"
    assert server_b["ORCHESTRA_CAPABILITY"] == "cap-b"
    assert server_a["SERVER_A_TOKEN"] == "a-canary" and "SERVER_B_TOKEN" not in server_a
    assert server_b["SERVER_B_TOKEN"] == "b-canary" and "SERVER_A_TOKEN" not in server_b


def test_td_capability_is_bound_to_session_scope_mode_and_not_operator_authority():
    capability = _load("app/mcp_capability.py", "task303_mcp_capability")
    store = capability.McpCapabilityStore(secret=b"task303-test-secret")
    token = store.issue(session_id="session-a", scope="/project/a", access_mode="full")
    assert store.authorize(
        token,
        session_id="session-a",
        scope="/project/a",
        access_mode="full",
        route_class="mcp",
    ) is True
    rejected = (
        {"session_id": "session-b", "scope": "/project/a", "access_mode": "full", "route_class": "mcp"},
        {"session_id": "session-a", "scope": "/project/b", "access_mode": "full", "route_class": "mcp"},
        {"session_id": "session-a", "scope": "/project/a", "access_mode": "read-only", "route_class": "mcp"},
        {"session_id": "session-a", "scope": "/project/a", "access_mode": "full", "route_class": "operator"},
    )
    for claims in rejected:
        with pytest.raises(PermissionError):
            store.authorize(token, **claims)
    store.revoke_session("session-a")
    with pytest.raises(PermissionError):
        store.authorize(
            token,
            session_id="session-a",
            scope="/project/a",
            access_mode="full",
            route_class="mcp",
        )


def test_td_guard_resolves_symlinks_and_emits_no_values(tmp_path):
    runtime_env = _load("app/runtime_env.py", "task303_runtime_env_guard")
    worktree = tmp_path / "worktree"
    cache = tmp_path / "cache"
    protected = tmp_path / "service-runtime"
    worktree.mkdir()
    cache.mkdir()
    protected.mkdir()
    alias = worktree / "runtime-alias"
    alias.symlink_to(protected, target_is_directory=True)
    canary = "task303-path-secret-canary"
    decision = runtime_env.audit_project_environment_target(
        key="UV_PROJECT_ENVIRONMENT",
        value=str(alias / canary),
        worktree=worktree,
        project_cache=cache,
        protected_roots=[protected],
        session_id="session-a",
        provider="codex",
        source="mcp",
    )
    assert decision.allowed is False
    encoded = json.dumps(decision.event, sort_keys=True)
    assert canary not in encoded and str(alias) not in encoded and str(protected) not in encoded
    assert decision.event == {
        "type": "ENV_BOUNDARY_EVENT",
        "session_id": "session-a",
        "provider": "codex",
        "source": "mcp",
        "key": "UV_PROJECT_ENVIRONMENT",
        "target_class": "protected_root",
        "action": "reject",
    }


def test_td_env_cleanup_deletes_only_registered_unchanged_replaced_copies(tmp_path):
    runtime_env = _load("app/runtime_env.py", "task303_runtime_env_cleanup")
    source = tmp_path / "source.env"
    source.write_text("PROJECT_TOKEN=scoped\n", encoding="utf-8")
    copied_hash = _sha256(source.read_bytes())
    unchanged = tmp_path / "unchanged.env"
    modified = tmp_path / "modified.env"
    no_replacement = tmp_path / "no-replacement.env"
    for path in (unchanged, modified, no_replacement):
        path.write_bytes(source.read_bytes())
    modified.write_text("PROJECT_TOKEN=user-edited\n", encoding="utf-8")
    records = [
        {"source": str(source), "destination": str(unchanged), "copied_sha256": copied_hash, "replacement_ready": True},
        {"source": str(source), "destination": str(modified), "copied_sha256": copied_hash, "replacement_ready": True},
        {"source": str(source), "destination": str(no_replacement), "copied_sha256": copied_hash, "replacement_ready": False},
    ]
    result = runtime_env.cleanup_injected_env_copies(records, manifest_complete=True)
    assert not unchanged.exists()
    assert modified.exists() and no_replacement.exists()
    assert result["removed"] == [str(unchanged)]
    assert set(result["retained"]) == {str(modified), str(no_replacement)}
    with pytest.raises(ValueError):
        runtime_env.cleanup_injected_env_copies([], manifest_complete=True)
    with pytest.raises(ValueError):
        runtime_env.cleanup_injected_env_copies(records, manifest_complete=False)


def test_td_release_b_attacks_still_fail_with_the_path_guard_disabled(tmp_path):
    evidence = ROOT / "docs/tasks/303/release-d-evidence.json"
    assert evidence.is_file(), (
        "T-D missing evidence: Release B was not rerun with the path guard disabled"
    )
    attestation, report = assert_bound_consumed_attestation(
        "D",
        "worker_boundary_audit",
        evidence,
        tmp_path / "one-shot-state",
    )
    assert attestation["exit_code"] == 0
    assert report["schema"] == "orchestra.task303.release-d.v2"
    expected_hashes = {
        relative: sha256_path(trusted_service_source(relative))
        for relative in (
            "app/runtime_env.py",
            "app/mcp_capability.py",
            "app/main.py",
            "app/mcp_stdio.py",
            "app/manager.py",
            "app/runtime_registry.py",
            "app/workspace.py",
        )
    }
    audit_path, audit_entry, _ = trusted_artifact("worker_boundary_audit")
    expected_hashes["scripts/audit-worker-boundary.py"] = audit_entry["sha256"]
    assert sha256_path(audit_path) == audit_entry["sha256"]
    assert report["implementation_sha256"] == expected_hashes
    assert report["path_guard_enabled"] is False
    assert report["release_b_identity_enabled"] is True
    assert report["per_server_env_non_leakage"] == "pass"
    assert report["default_worktree_env_copy"] is False
    assert report["canary_leak_counts"] == {
        "argv": 0,
        "environ": 0,
        "mcp_config": 0,
        "worktree": 0,
        "audit_log": 0,
    }
    attacks = report["bypass_attacks"]
    assert set(attacks) == BYPASSES
    for name, row in attacks.items():
        assert row["errno"] == "EACCES", name
        assert row["service_canary_unchanged"] is True, name
    assert report["archive_revocation"] == "pass"
    assert report["kill_revocation"] == "pass"
    assert report["capability_rejections"] == {
        "cross_session": "pass",
        "cross_scope": "pass",
        "cross_access_mode": "pass",
        "operator_route": "pass",
    }
