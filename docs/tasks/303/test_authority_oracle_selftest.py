"""Green checks for #303 oracle mechanics; no local authority implementation lives here."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle_support  # noqa: E402
from oracle_support import (  # noqa: E402
    RFC8032_VECTOR_2,
    RFC8032_WRONG_PUBLIC_KEY,
    SAFE_INSTALLER_SOURCE,
    apply_artifact_attack,
    artifact_identity_path,
    assert_shipped_activation_surface,
    exercise_public_activation_authorization,
    exercise_public_manager_activation,
    independent_ed25519_verify,
    parse_activation_unit_command,
    parse_systemd_execstart_property,
    wait_for_concurrent_ready,
)


def _assert_release_uses_selected_unit(
    source: str,
    *,
    test_name: str,
    kind: str,
    argv_name: str,
    exercise_name: str,
) -> None:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == test_name
    )
    selectors = []
    exercises = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        called = ast.unparse(node.func)
        if called == "selected_activation_unit_command":
            selectors.append(node)
        if called == exercise_name:
            exercises.append(node)
    assert len(selectors) == 1
    assert len(selectors[0].args) == 1
    assert isinstance(selectors[0].args[0], ast.Constant)
    assert selectors[0].args[0].value == kind
    assignment = next(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign) and node.value is selectors[0]
    )
    assert isinstance(assignment.targets[0], ast.Tuple)
    assert isinstance(assignment.targets[0].elts[0], ast.Name)
    assert assignment.targets[0].elts[0].id == argv_name
    assert len(exercises) == 1
    assert isinstance(exercises[0].args[0], ast.Name)
    assert exercises[0].args[0].id == argv_name


def _assert_release_calls_surface_inventory(source: str, *, test_name: str) -> None:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == test_name
    )
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "assert_shipped_activation_surface"
    ]
    assert len(calls) == 1
    assert len(calls[0].args) == 1
    assert isinstance(calls[0].args[0], ast.Name)
    assert calls[0].args[0].id == "ROOT"


def test_gate1_and_gate2_helpers_observe_but_do_not_implement_authority():
    support_tree = ast.parse(Path(oracle_support.__file__).read_text(encoding="utf-8"))
    forbidden_parameters = {
        "activation_entrypoint",
        "runtime_operation",
        "policy_authorize",
        "apply_activation",
        "commit_activation",
        "runner",
        "before_execute",
    }
    for node in ast.walk(support_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parameters = {argument.arg for argument in node.args.args + node.args.kwonlyargs}
            assert not parameters.intersection(forbidden_parameters), (
                f"oracle helper {node.name} accepts an injected authority implementation"
            )

    assert list(inspect.signature(exercise_public_manager_activation).parameters) == [
        "activation_argv",
        "source_artifacts",
        "tmp_path",
    ]
    assert list(inspect.signature(exercise_public_activation_authorization).parameters) == [
        "authorization_argv",
        "tmp_path",
    ]

    release_a = Path(__file__).with_name("test_release_a_recovery.py").read_text(
        encoding="utf-8"
    )
    release_b = Path(__file__).with_name("test_release_b_identity.py").read_text(
        encoding="utf-8"
    )
    self_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    self_functions = {
        node.name
        for node in ast.walk(self_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    _assert_release_uses_selected_unit(
        release_a,
        test_name=(
            "test_ta_real_installed_artifacts_cannot_change_between_verification_and_execution"
        ),
        kind="recovery",
        argv_name="activation_argv",
        exercise_name="exercise_public_manager_activation",
    )
    _assert_release_uses_selected_unit(
        release_b,
        test_name=(
            "test_tb_public_activation_consumer_atomically_consumes_concurrent_replay"
        ),
        kind="boundary",
        argv_name="authorization_argv",
        exercise_name="exercise_public_activation_authorization",
    )
    _assert_release_calls_surface_inventory(
        release_a,
        test_name="test_ta_only_shipped_activation_authority_entries_are_fixed_units",
    )
    _assert_release_calls_surface_inventory(
        release_b,
        test_name="test_tb_boundary_unit_is_the_only_shipped_authorization_caller",
    )
    for source in (release_a, release_b):
        assert "public_activation_command" not in source
        assert "public_authorization_command" not in source
    for forbidden in (
        "_reference_artifact_entrypoint",
        "_reference_policy_authorize",
        "_reference_runtime_operation",
        "activate_installed_artifacts",
        "authorize_pending_activation",
        ):
        assert forbidden not in release_a
        assert forbidden not in release_b
        assert forbidden not in self_functions


def test_gate1_and_gate2_parse_the_actual_shell_free_systemd_callers():
    manager = Path(
        "/usr/libexec/orchestra-runtime/control-planes/" + "a" * 40 + "/runtime-manager"
    )
    for operation in ("activate", "authorize-commit"):
        unit = (
            "[Service]\n"
            "Type=oneshot\n"
            "User=root\n"
            f"ExecStart={manager} {operation} --state-root "
            "/var/lib/orchestra-runtime --activation-id %i\n"
        )
        assert parse_activation_unit_command(
            unit,
            expected_manager=manager,
            expected_operation=operation,
        ) == [
            str(manager),
            operation,
            "--state-root",
            "/var/lib/orchestra-runtime",
            "--activation-id",
            "%i",
        ]
        effective = (
            f"{{ path={manager} ; argv[]={manager} {operation} --state-root "
            "/var/lib/orchestra-runtime --activation-id task303-oracle ; "
            "ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; "
            "code=(null) ; status=0/0 }"
        )
        assert parse_systemd_execstart_property(effective) == [
            str(manager),
            operation,
            "--state-root",
            "/var/lib/orchestra-runtime",
            "--activation-id",
            "task303-oracle",
        ]
        for effective_bypass in (
            effective.replace(str(manager), "/bin/true"),
            effective.replace("ignore_errors=no", "ignore_errors=yes"),
            effective + effective,
        ):
            with pytest.raises(AssertionError):
                parsed = parse_systemd_execstart_property(effective_bypass)
                assert parsed[0] == str(manager)
        for bypass in (
            unit.replace(str(manager), "/bin/true"),
            unit.replace(operation, "direct-apply"),
            unit + f"ExecStartPost={manager} {operation}\n",
            unit + f"ExecCondition={manager} direct-apply\n",
            unit + "Environment=UV_PROJECT_ENVIRONMENT=/home/kesha/orchestra/.venv\n",
            unit.replace("User=root\n", "User=kesha\n"),
            unit + "RootDirectory=/hostile-root\n",
        ):
            with pytest.raises(AssertionError):
                parse_activation_unit_command(
                    bypass,
                    expected_manager=manager,
                    expected_operation=operation,
                )


def _write_minimal_activation_surface(root: Path) -> None:
    (root / "app/routes").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "deploy").mkdir()
    (root / "app/routes/system.py").write_text(
        "def health():\n    return {'ok': True}\n", encoding="utf-8"
    )
    (root / "scripts/manage_orchestra_runtime.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8"
    )
    (root / "scripts/build-orchestra-runtime-package.py").write_text(
        "UNIT_FILES = ('orchestra-runtime-recovery@.service', "
        "'orchestra-boundary-activate@.service')\n",
        encoding="utf-8",
    )
    (root / "deploy/install.sh").write_text(
        SAFE_INSTALLER_SOURCE, encoding="utf-8"
    )
    units = {
        "recovery": ("orchestra-runtime-recovery@.service", "activate"),
        "boundary": ("orchestra-boundary-activate@.service", "authorize-commit"),
    }
    for _, (name, operation) in units.items():
        (root / "deploy" / name).write_text(
            "[Service]\n"
            "Type=oneshot\n"
            "User=root\n"
            f"ExecStart=@CONTROL_PLANE_ROOT@/runtime-manager {operation} "
            "--state-root /var/lib/orchestra-runtime --activation-id %i\n",
            encoding="utf-8",
        )
    (root / "deploy/orchestra-authority-surface.json").write_text(
        json.dumps(
            {
                "schema": "orchestra.activation-surface.v1",
                "authority_owner": "scripts/manage_orchestra_runtime.py",
                "non_authority_packager": "scripts/build-orchestra-runtime-package.py",
                "activation_callers": {
                    "recovery": "deploy/orchestra-runtime-recovery@.service",
                    "boundary": "deploy/orchestra-boundary-activate@.service",
                },
                "installer": "deploy/install.sh",
                "source_roots": ["app", "scripts", "deploy"],
            }
        ),
        encoding="utf-8",
    )


def test_gate1_and_gate2_inventory_all_shipped_authority_consumers(tmp_path):
    clean = tmp_path / "clean"
    _write_minimal_activation_surface(clean)
    surface = assert_shipped_activation_surface(clean)
    assert surface["activation_callers"] == {
        "recovery": "deploy/orchestra-runtime-recovery@.service",
        "boundary": "deploy/orchestra-boundary-activate@.service",
    }
    assert "app/routes/system.py" in surface["files_scanned"]

    attacks = {
        "indirect_installer_activation": (
            "deploy/install.sh",
            "unit=orchestra-runtime-recovery@task303.service\n"
            "systemctl start --wait \"$unit\"\n",
        ),
        "constructed_installer_activation": (
            "deploy/install.sh",
            "unit=orchestra-runtime-recovery@task303.service\n"
            "ctl=/usr/bin/sys\n"
            "ctl=\"${ctl}temctl\"\n"
            "action=sta\n"
            "action=\"${action}rt\"\n"
            "\"$ctl\" \"$action\" --wait \"$unit\"\n",
        ),
        "direct_manager_invocation": (
            "deploy/install.sh",
            "manager=/usr/libexec/orchestra-runtime/control-planes/x/runtime-manager\n"
            "\"$manager\" activate --state-root /var/lib/orchestra-runtime "
            "--activation-id task303\n",
        ),
        "alternate_application_route": (
            "app/routes/system.py",
            "\nfrom scripts.manage_orchestra_runtime import authorize_commit\n"
            "def bypass(request):\n    return authorize_commit(request)\n",
        ),
    }
    for name, (relative, payload) in attacks.items():
        attacked = tmp_path / name
        shutil.copytree(clean, attacked)
        target = attacked / relative
        target.write_text(target.read_text(encoding="utf-8") + payload, encoding="utf-8")
        with pytest.raises(AssertionError, match="alternate shipped activation authority"):
            assert_shipped_activation_surface(attacked)


def test_gate1_artifact_attacks_physically_change_path_or_content(tmp_path):
    original = b"#!/usr/bin/env python3\nprint('trusted')\n"
    for attack in ("rename", "symlink", "inode_preserving_content"):
        root = tmp_path / attack
        root.mkdir()
        artifact = root / "runtime_manager.py"
        artifact.write_bytes(original)
        artifact.chmod(0o500)
        verified = artifact_identity_path(artifact)
        apply_artifact_attack(
            artifact,
            attack,
            sentinel=root / "HOSTILE_EXECUTED",
            role="runtime_manager",
            verified=verified,
        )
        if attack == "symlink":
            assert artifact.is_symlink()
            assert artifact.resolve().read_bytes() != original
            continue
        observed = artifact_identity_path(artifact)
        assert observed["sha256"] != verified["sha256"]
        if attack == "rename":
            assert observed["inode"] != verified["inode"]
        else:
            assert observed["inode"] == verified["inode"]
            assert observed["size"] == verified["size"]


def test_gate2_oracle_uses_independent_ed25519_known_vectors(tmp_path):
    vector = RFC8032_VECTOR_2
    assert independent_ed25519_verify(
        vector["public_key"], vector["message"], vector["signature"], tmp_path / "valid"
    )
    assert not independent_ed25519_verify(
        vector["public_key"], vector["message"], bytes(64), tmp_path / "garbage"
    )
    changed = bytearray(vector["signature"])
    changed[-1] ^= 1
    assert not independent_ed25519_verify(
        vector["public_key"], vector["message"], bytes(changed), tmp_path / "bit-flip"
    )
    assert not independent_ed25519_verify(
        RFC8032_WRONG_PUBLIC_KEY,
        vector["message"],
        vector["signature"],
        tmp_path / "wrong-key",
    )


def test_gate2_concurrency_barrier_requires_both_distinct_contenders(tmp_path):
    ready = tmp_path / "ready"
    ready.mkdir()
    contenders = [
        SimpleNamespace(pid=41001, poll=lambda: None, kill=lambda: None),
        SimpleNamespace(pid=41002, poll=lambda: None, kill=lambda: None),
    ]
    for contender in contenders:
        (ready / f"{contender.pid}.json").write_text(
            json.dumps(
                {
                    "operation": "authorize-commit",
                    "phase": "validated_before_consume",
                    "pid": contender.pid,
                }
            ),
            encoding="utf-8",
        )
    rows = wait_for_concurrent_ready(ready, contenders, timeout=0.1)
    assert {row["pid"] for row in rows} == {41001, 41002}

    only_one = tmp_path / "only-one"
    only_one.mkdir()
    (only_one / "41001.json").write_text(
        json.dumps(
            {
                "operation": "authorize-commit",
                "phase": "validated_before_consume",
                "pid": 41001,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="both authorization contenders"):
        wait_for_concurrent_ready(only_one, contenders, timeout=0.02)
