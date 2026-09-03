"""Green self-tests for the V10 unprivileged delivery boundary."""

import ast
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_v10_support import (  # noqa: E402
    ACTIVATION_ONLY_KEYS,
    DELIVERY_REPORT_KEYS,
    PACKAGE_MANIFEST_KEYS,
    REQUIRED_PACKAGE_MEMBERS,
    inspect_package,
    synthetic_tar,
    validate_delivery_report,
    validate_package,
    validate_public_source_content,
)


ROOT = Path(__file__).resolve().parents[3]


def _valid_report() -> dict:
    return {
        "schema": "orchestra.task303.delivery.v1",
        "release": "A",
        "source_commit": "a" * 40,
        "delivery_ready": True,
        "activation_ready": False,
        "privileged_evidence": "pending",
        "activation_authorized": False,
        "isolation_claimed": False,
        "production_state_unchanged": True,
        "activation_receipt": None,
        "protected_secret_comparison": "pending_privileged_activation",
        "package": {
            "path": "/var/tmp/orchestra-task303-packages/release-a.tar",
            "sha256": "b" * 64,
            "manifest_sha256": "c" * 64,
        },
        "source_tests": {
            "exit_code": 0,
            "output_sha256": "d" * 64,
            "nodeids": ["test-node"],
        },
        "deferred_activation_gate": {
            "status": "pending",
            "evidence_kind": "root-owned-installed-state-and-pid1",
        },
    }


def test_v10_delivery_report_cannot_claim_activation_or_isolation():
    report = _valid_report()
    validate_delivery_report(report, release="A")
    mutations = {
        "activation_ready": True,
        "privileged_evidence": "complete",
        "activation_authorized": True,
        "isolation_claimed": True,
        "activation_receipt": {"nonce": "forged"},
        "protected_secret_comparison": "complete",
    }
    for key, value in mutations.items():
        changed = json.loads(json.dumps(report))
        changed[key] = value
        with pytest.raises(AssertionError):
            validate_delivery_report(changed, release="A")
    for key in ACTIVATION_ONLY_KEYS:
        changed = json.loads(json.dumps(report))
        changed[key] = "forged"
        with pytest.raises(AssertionError):
            validate_delivery_report(changed, release="A")
    assert not ACTIVATION_ONLY_KEYS.intersection(DELIVERY_REPORT_KEYS)


def test_v10_delivery_package_rejects_authority_state_and_escaping_links(tmp_path):
    safe_members = {
        name: b"payload\n" for name in REQUIRED_PACKAGE_MEMBERS["A"]
    }
    package = tmp_path / "safe.tar"
    package.write_bytes(synthetic_tar(safe_members))
    package.chmod(0o600)
    observed = inspect_package(package, allowed_members=set(safe_members))
    manifest = {
        "schema": "orchestra.runtime-package.v1",
        "release": "A",
        "source_commit": "a" * 40,
        "delivery_only": True,
        "activation_ready": False,
        "privileged_evidence": "pending",
        "isolation_claimed": False,
        "provider_credential_store_included": False,
        "protected_secret_comparison": "pending_privileged_activation",
        "activation_state_included": False,
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "python_version": "3.12.11",
        "members": observed,
    }
    assert set(manifest) == PACKAGE_MANIFEST_KEYS
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validate_package(
        package,
        manifest_path,
        release="A",
        source_commit="a" * 40,
        expected_members=observed,
    )

    for name, value in {
        "/var/lib/orchestra-runtime/receipt.json": b"forged",
        "state/keys/private": b"forged",
        "app-source/app/provider-credentials.json": b"refresh_token=forged",
        "app-source/.ssh/id_ed25519": b"forged-private-key",
        "state/activation-receipt.json": b"forged-signature",
        "runtime/bin/python": ("symlink", "../../../etc/shadow"),
    }.items():
        hostile = tmp_path / (hashlib.sha256(name.encode()).hexdigest() + ".tar")
        members = dict(safe_members)
        members[name] = value
        hostile.write_bytes(synthetic_tar(members))
        with pytest.raises(AssertionError):
            inspect_package(hostile, allowed_members=set(safe_members))

    linked = dict(safe_members)
    linked["runtime/bin/python"] = (
        "symlink",
        "../../state/activation-receipt.json",
    )
    linked_package = tmp_path / "sensitive-relative-link.tar"
    linked_package.write_bytes(synthetic_tar(linked))
    with pytest.raises(AssertionError):
        inspect_package(linked_package, allowed_members=set(safe_members))

    for name, content in {
        "app-source/app/provider-credentials.json": b'{"refresh_token":"SECRET"}\n',
        "app-source/app/provider_credentials.py": b"refresh_token=SECRET\n",
        "app-source/app/embedded_token.py": b'x="sk-or-v1-abcdefghijklmnop"\n',
        "app-source/app/embedded_key.py": (
            b'key="-----BEGIN PRIVATE KEY-----\\nforged\\n'
            b'-----END PRIVATE KEY-----"\n'
        ),
    }.items():
        tracked = dict(safe_members)
        tracked[name] = content
        tracked_package = tmp_path / (hashlib.sha256(("tracked:" + name).encode()).hexdigest() + ".tar")
        tracked_package.write_bytes(synthetic_tar(tracked))
        with pytest.raises(AssertionError):
            inspect_package(tracked_package, allowed_members=set(tracked))

    validate_public_source_content(
        "app-source/app/provider_boundary.py",
        b'refresh_token = os.environ.get("PROVIDER_REFRESH_TOKEN", "")\n',
    )


def test_v10_delivery_runner_has_no_activation_executable_surface():
    path = ROOT / "docs/tasks/303/v10_delivery_gate.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    raw_calls = []
    subprocess_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            dotted = f"{getattr(node.func.value, 'id', '')}.{node.func.attr}"
            if dotted in {"os.system", "os.execv", "os.execve", "subprocess.Popen"}:
                raw_calls.append(dotted)
            if dotted == "subprocess.run":
                subprocess_calls.append(node.lineno)
    assert raw_calls == []
    assert len(subprocess_calls) == 1
    assert "shell=True" not in source
    assert "systemctl" not in source
    assert "authorize-commit" not in source
    assert source.count("validate_public_source_content(package_name, content)") == 1
    assert source.count("_public_source_entry(") == 4
    assert source.count('"scripts/manage_orchestra_runtime.py"') == 1
    assert '"control-plane/runtime-manager": "scripts/manage_orchestra_runtime.py"' in source
