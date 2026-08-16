"""Frozen RED oracle for #303 Release C (provider credential boundary)."""

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_support import (  # noqa: E402
    PROVIDER_MANIFEST,
    assert_bound_consumed_attestation,
    assert_root_regular,
    load_control_selection,
    sha256_path,
    trusted_service_source,
)


ROOT = Path(__file__).resolve().parents[3]
PROVIDERS = {"codex", "claude", "grok", "opencode"}
BACKENDS = {
    "codex": "app/backend_codex.py",
    "claude": "app/backend_claude.py",
    "grok": "app/backend_grok.py",
    "opencode": "app/backend_opencode.py",
}
DIRECT_READ_CHANNELS = {"read", "bash", "test", "mcp", "background"}
LEAK_SURFACES = {"argv", "environ", "project_config", "worktree", "task_logs"}
EXPECTED_LAUNCHERS = {
    "codex": "codex",
    "claude": "claude",
    "grok": "grok",
    "opencode": "opencode",
}
PROVIDER_BINARY_ROOT = Path("/usr/libexec/orchestra-runtime/providers")


def _merged_config_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        encoded_path = str(path.resolve()).encode()
        data = path.read_bytes()
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _assert_manifest_provider(provider: str, entry: dict, controller_uid: int) -> None:
    launcher = Path(entry["launcher"]["path"])
    expected_root = PROVIDER_BINARY_ROOT / provider / entry["launcher"]["sha256"]
    assert launcher.name == EXPECTED_LAUNCHERS[provider], provider
    assert launcher.is_relative_to(expected_root), provider
    launcher_stat = assert_root_regular(launcher)
    assert entry["launcher"] == {
        "path": str(launcher),
        "device": launcher_stat.st_dev,
        "inode": launcher_stat.st_ino,
        "size": launcher_stat.st_size,
        "sha256": sha256_path(launcher),
    }, provider

    config_paths = []
    for config in entry["config_files"]:
        path = Path(config["path"])
        file_stat = assert_root_regular(path)
        assert config == {
            "path": str(path),
            "device": file_stat.st_dev,
            "inode": file_stat.st_ino,
            "size": file_stat.st_size,
            "sha256": sha256_path(path),
        }, provider
        config_paths.append(path)
    assert config_paths, provider
    assert entry["effective_config_sha256"] == _merged_config_sha256(config_paths), provider

    auth = entry["auth_store"]
    auth_path = Path(auth["path"])
    assert auth_path.is_absolute() and ".." not in auth_path.parts, provider
    assert auth["owner_uid"] == controller_uid, provider
    assert auth["mode"] == "0700", provider
    assert len(auth["device_inode_fingerprint"]) == 64, provider
    assert len(auth["content_fingerprint"]) == 64, provider


def _load_provider_manifest(attestation: dict | None = None) -> dict:
    assert_root_regular(PROVIDER_MANIFEST, private=True)
    manifest = json.loads(PROVIDER_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "orchestra.provider-selection.v1"
    assert manifest["selection_source"] == "operator-pinned-package"
    selection, selection_digest = load_control_selection()
    assert manifest["source_commit"] == selection["source_commit"]
    assert manifest["control_selection_sha256"] == selection_digest
    assert set(manifest["providers"]) == PROVIDERS
    assert isinstance(manifest["controller_uid"], int) and manifest["controller_uid"] > 0
    if attestation is not None:
        assert manifest["activation_id"] == attestation["activation_id"]
        assert attestation["provider_manifest_sha256"] == sha256_path(PROVIDER_MANIFEST)
    for provider, entry in manifest["providers"].items():
        _assert_manifest_provider(provider, entry, manifest["controller_uid"])
    return manifest


def _assert_resolver_matches_manifest(resolver, manifest: dict) -> None:
    for provider, entry in manifest["providers"].items():
        resolved = resolver.resolve_provider_inputs(provider)
        assert set(resolved) == {"binary", "config_files", "auth_store"}, provider
        assert os.path.abspath(resolved["binary"]) == entry["launcher"]["path"], provider
        assert [os.path.abspath(path) for path in resolved["config_files"]] == [
            item["path"] for item in entry["config_files"]
        ], provider
        assert os.path.abspath(resolved["auth_store"]) == entry["auth_store"]["path"], provider


def _load_boundary():
    candidate = ROOT / "app/provider_boundary.py"
    assert candidate.is_file(), (
        "T-C missing behavior: provider credentials and project tools share one authority domain"
    )
    path = trusted_service_source("app/provider_boundary.py")
    spec = importlib.util.spec_from_file_location("task303_provider_boundary", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_provider_inputs():
    path = trusted_service_source("app/provider_inputs.py")
    assert path.is_file(), "T-C missing behavior: deployed provider inputs have no independent owner"
    spec = importlib.util.spec_from_file_location("task303_provider_inputs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _called_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def test_tc_backends_use_controller_launch_and_project_tools_use_release_b():
    _load_boundary()
    broker = trusted_service_source("app/project_tool_broker.py")
    assert broker.is_file(), "T-C missing behavior: the uncredentialed tool broker is absent"
    broker_calls = _called_names(broker)
    assert "launch_project_process" in broker_calls
    assert not {
        "create_subprocess_exec", "create_subprocess_shell", "Popen", "run", "system"
    }.intersection(broker_calls)
    for provider, relative in BACKENDS.items():
        calls = _called_names(trusted_service_source(relative))
        assert "launch_provider_controller" in calls, (
            f"T-C bypass remains: {provider} does not launch through the controller boundary"
        )
    registry_calls = _called_names(trusted_service_source("app/runtime_registry.py"))
    assert "resolve_provider_inputs" in registry_calls
    assert "enforcement_latch" in registry_calls


def test_tc_all_provider_probe_rows_are_current_complete_and_non_leaking(tmp_path):
    evidence = ROOT / "docs/tasks/303/release-c-evidence.json"
    assert evidence.is_file(), (
        "T-C missing evidence: all-provider auth/refresh/EACCES rehearsal has not passed"
    )
    attestation, report = assert_bound_consumed_attestation(
        "C",
        "provider_boundary_rehearsal",
        evidence,
        tmp_path / "one-shot-state",
    )
    assert attestation["exit_code"] == 0
    assert report["schema"] == "orchestra.task303.release-c.v2"
    assert report["controller_uid"] != report["project_uid"]
    assert report["credential_store"]["controller_readable"] is True
    assert report["credential_store"]["service_read_errno"] == "EACCES"
    assert report["credential_store"]["project_read_errno"] == "EACCES"
    assert report["controller_service_secret_read_errno"] == "EACCES"
    assert report["global_enforcement_latch"] == "enabled"
    assert report["boundary_sha256"] == sha256_path(
        trusted_service_source("app/provider_boundary.py")
    )
    assert report["broker_sha256"] == sha256_path(
        trusted_service_source("app/project_tool_broker.py")
    )
    assert report["controller_unit_sha256"] == sha256_path(
        trusted_service_source("deploy/orchestra-provider-controller@.service")
    )
    assert report["controller_user_manager_sha256"] == sha256_path(
        trusted_service_source("deploy/manage-provider-controller-user.sh")
    )
    assert report["provider_inputs_sha256"] == sha256_path(
        trusted_service_source("app/provider_inputs.py")
    )

    rows = report["providers"]
    assert set(rows) == PROVIDERS
    manifest = _load_provider_manifest(attestation)
    assert report["provider_manifest_sha256"] == sha256_path(PROVIDER_MANIFEST)
    assert attestation["protected_store_fingerprints"] == {
        provider: entry["auth_store"]["content_fingerprint"]
        for provider, entry in manifest["providers"].items()
    }
    provider_inputs = _load_provider_inputs()
    _assert_resolver_matches_manifest(provider_inputs, manifest)

    class BinTrueResolver:
        @staticmethod
        def resolve_provider_inputs(provider):
            return {
                "binary": "/bin/true",
                "config_files": [item["path"] for item in manifest["providers"][provider]["config_files"]],
                "auth_store": manifest["providers"][provider]["auth_store"]["path"],
            }

    with pytest.raises(AssertionError):
        _assert_resolver_matches_manifest(BinTrueResolver(), manifest)
    common_mode_lie = copy.deepcopy(manifest)
    true_stat = Path("/bin/true").stat()
    common_mode_lie["providers"]["codex"]["launcher"] = {
        "path": "/bin/true",
        "device": true_stat.st_dev,
        "inode": true_stat.st_ino,
        "size": true_stat.st_size,
        "sha256": sha256_path(Path("/bin/true")),
    }
    with pytest.raises(AssertionError):
        _assert_manifest_provider("codex", common_mode_lie["providers"]["codex"], manifest["controller_uid"])

    for provider, row in rows.items():
        manifest_row = manifest["providers"][provider]
        assert row["binary"] == manifest_row["launcher"], provider
        assert row["config_files"] == manifest_row["config_files"], provider
        assert row["config_sha256"] == manifest_row["effective_config_sha256"], provider
        assert row["credential_store_fingerprint"] == manifest_row["auth_store"]["content_fingerprint"], provider
        assert row["source_sha256"] == sha256_path(
            trusted_service_source(BACKENDS[provider])
        ), provider

        controller = row["controller"]
        assert controller["uid"] == report["controller_uid"], provider
        assert controller["neutral_cwd"] is True, provider
        assert controller["project_paths_visible"] is False, provider
        assert controller["native_arbitrary_tools_disabled"] is True, provider
        assert controller["broker_only_project_operations"] is True, provider

        positive = row["positive"]
        assert positive["startup"]["passed"] is True, provider
        assert len(positive["startup"]["session_hash"]) == 64, provider
        assert positive["authenticated_turn"]["passed"] is True, provider
        assert len(positive["authenticated_turn"]["transcript_hash"]) == 64, provider
        assert positive["refresh"]["passed"] is True, provider
        assert positive["refresh"]["proof_kind"] in {
            "forced_expiry_refresh",
            "documented_reauthentication",
        }, provider
        assert positive["refresh"]["before_fingerprint"] != positive["refresh"]["after_fingerprint"], provider

        negatives = row["direct_read_attempts"]
        assert set(negatives) == DIRECT_READ_CHANNELS, provider
        for channel, attempt in negatives.items():
            assert attempt["brokered"] is True, (provider, channel)
            assert attempt["observed_uid"] == report["project_uid"], (provider, channel)
            assert attempt["errno"] == "EACCES", (provider, channel)
            assert attempt["canary_leaked"] is False, (provider, channel)

        leak_scan = row["leak_scan"]
        assert set(leak_scan) == LEAK_SURFACES, provider
        assert all(count == 0 for count in leak_scan.values()), provider


def test_tc_one_failed_or_unknown_provider_holds_the_global_latch_closed():
    boundary = _load_boundary()
    evidence = ROOT / "docs/tasks/303/release-c-evidence.json"
    assert evidence.is_file()
    report = json.loads(evidence.read_text(encoding="utf-8"))
    manifest = _load_provider_manifest()
    assert boundary.enforcement_latch(report, provider_manifest=manifest) is True

    for provider in PROVIDERS:
        mutated = json.loads(json.dumps(report))
        mutated["providers"][provider]["positive"]["authenticated_turn"]["passed"] = False
        assert boundary.enforcement_latch(mutated, provider_manifest=manifest) is False, provider
        no_refresh = json.loads(json.dumps(report))
        no_refresh["providers"][provider]["positive"]["refresh"]["passed"] = False
        assert boundary.enforcement_latch(no_refresh, provider_manifest=manifest) is False, provider
        readable = json.loads(json.dumps(report))
        readable["providers"][provider]["direct_read_attempts"]["bash"]["errno"] = None
        assert boundary.enforcement_latch(readable, provider_manifest=manifest) is False, provider
        leaked = json.loads(json.dumps(report))
        leaked["providers"][provider]["leak_scan"]["task_logs"] = 1
        assert boundary.enforcement_latch(leaked, provider_manifest=manifest) is False, provider

    missing = json.loads(json.dumps(report))
    missing["providers"].pop("grok")
    assert boundary.enforcement_latch(missing, provider_manifest=manifest) is False
    unknown = json.loads(json.dumps(report))
    unknown["providers"]["unknown"] = unknown["providers"]["codex"]
    assert boundary.enforcement_latch(unknown, provider_manifest=manifest) is False
    bad_hash = json.loads(json.dumps(report))
    bad_hash["providers"]["codex"]["binary"]["sha256"] = "0" * 64
    assert boundary.enforcement_latch(bad_hash, provider_manifest=manifest) is False
    bad_config = json.loads(json.dumps(report))
    bad_config["providers"]["codex"]["config_sha256"] = "0" * 64
    assert boundary.enforcement_latch(bad_config, provider_manifest=manifest) is False

    shared_lie = copy.deepcopy(manifest)
    true_path = Path("/bin/true")
    true_stat = true_path.stat()
    true_identity = {
        "path": str(true_path),
        "device": true_stat.st_dev,
        "inode": true_stat.st_ino,
        "size": true_stat.st_size,
        "sha256": sha256_path(true_path),
    }
    shared_lie["providers"]["codex"]["launcher"] = true_identity
    shared_report = copy.deepcopy(report)
    shared_report["providers"]["codex"]["binary"] = true_identity
    assert boundary.enforcement_latch(shared_report, provider_manifest=shared_lie) is False
