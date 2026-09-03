"""Green self-tests for the V11 runtime directory-link refreeze."""

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v10_delivery_oracle as v10_tests  # noqa: E402
import v11_delivery_gate as gate  # noqa: E402
import oracle_v11_support as support  # noqa: E402
from oracle_v11_support import (  # noqa: E402
    REQUIRED_PACKAGE_MEMBERS,
    inspect_package,
    synthetic_tar,
    validate_package,
)


ROOT = Path(__file__).resolve().parents[3]
V9_AND_V10_SHA256 = {
    "oracle_support.py": "6a0d1262f55b3fc4e3d8382a4a3f351bd7b1f184a1918e65f1ec9e82d0f9e421",
    "test_authority_oracle_selftest.py": "1f7d042c59c5e57e48f979b06d725fb2e4827986d23876fe7c250193cb9db66f",
    "test_release_a_recovery.py": "ed79bd5541ae7c7be876ae6d75324d714c8e871dce181e47b7621734776facc5",
    "test_release_b_identity.py": "a4fb65f1bc54ff195ada6bb9e07d519dbd5817ac5b85a7350714847ac5dca426",
    "test_release_c_credentials.py": "372460aa70f4427fe185eaf0349ed0d40ea340bffcbe1d683604be231fb0d99b",
    "test_release_d_env.py": "be89030df06a5c3d25f28e92ba9fb5c8a4c71ad9903beb90487ead2181df1f3d",
    "oracle_v10_support.py": "172b279e6c884cdafcf5ade420e4e34fc9a09eef7f614e57c95035c11d83c6a9",
    "v10_delivery_gate.py": "f3be12d4834776ec0b4fff2b5eb39e0ab495c8dde7b2243ca50f9adf254a764a",
    "test_v10_delivery_oracle.py": "8411c2b987380fc6e0ab444af0dd4096f39627eea27463b26c63cd98bc4fb4ef",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference_tree(root: Path) -> Path:
    reference = root / "reference"
    (reference / "bin").mkdir(parents=True)
    (reference / "lib/python3.12/site-packages").mkdir(parents=True)
    python = reference / "bin/python"
    python.write_bytes(b"python-3.12\n")
    python.chmod(0o755)
    (reference / "pyvenv.cfg").write_text("version = 3.12\n", encoding="utf-8")
    (reference / "lib/python3.12/site-packages/module.py").write_bytes(b"VALUE = 1\n")
    (reference / "lib64").symlink_to("lib", target_is_directory=True)
    return reference


def _package_manifest(package: Path, observed: dict) -> dict:
    return {
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


def _safe_package_members() -> dict[str, bytes | tuple[str, str]]:
    members: dict[str, bytes | tuple[str, str]] = {
        name: b"payload\n" for name in REQUIRED_PACKAGE_MEMBERS["A"]
    }
    members["runtime/lib/python3.12/site-packages/module.py"] = b"VALUE = 1\n"
    members["runtime/lib64"] = ("symlink", "lib")
    return members


def test_v11_retains_v10_pending_report_and_secret_mutations(tmp_path):
    v10_tests.test_v10_delivery_report_cannot_claim_activation_or_isolation()
    v10_tests.test_v10_delivery_package_rejects_authority_state_and_escaping_links(tmp_path)
    v10_tests.test_v10_delivery_runner_has_no_activation_executable_surface()


def test_v11_preserves_every_v9_and_v10_oracle_byte():
    task_dir = ROOT / "docs/tasks/303"
    observed = {name: _sha256(task_dir / name) for name in V9_AND_V10_SHA256}
    assert observed == V9_AND_V10_SHA256


def test_v11_reference_and_package_accept_exact_canonical_lib64_link(tmp_path):
    reference = _reference_tree(tmp_path)
    inventory, allowed_directories = gate._runtime_tree_inventory(reference)
    assert inventory["runtime/lib64"] == {
        "type": "symlink",
        "mode": "0777",
        "target": "lib",
    }
    assert "runtime/lib" in allowed_directories

    package = tmp_path / "safe-lib64.tar"
    package.write_bytes(synthetic_tar(_safe_package_members()))
    package.chmod(0o600)
    observed = inspect_package(
        package,
        allowed_members=set(_safe_package_members()),
        allowed_runtime_directories={"runtime/lib"},
    )
    assert observed["runtime/lib64"] == inventory["runtime/lib64"]
    manifest = _package_manifest(package, observed)
    manifest_path = tmp_path / "safe-lib64-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validation = validate_package(
        package,
        manifest_path,
        release="A",
        source_commit="a" * 40,
        expected_members=observed,
        expected_runtime_directories={"runtime/lib"},
    )
    assert validation["package_sha256"] == hashlib.sha256(package.read_bytes()).hexdigest()
    assert validation["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "mutation",
    [
        "absolute",
        "escape",
        "dangling",
        "chained_escape",
        "cycle",
        "special_device",
        "protected_state",
        "noncanonical",
    ],
)
def test_v11_reference_rejects_unsafe_directory_links(tmp_path, mutation):
    case = tmp_path / mutation
    reference = _reference_tree(case)
    link = reference / "lib64"
    link.unlink()
    if mutation == "absolute":
        link.symlink_to((reference / "lib").resolve(), target_is_directory=True)
    elif mutation == "escape":
        outside = case / "outside"
        outside.mkdir()
        link.symlink_to("../outside", target_is_directory=True)
    elif mutation == "dangling":
        link.symlink_to("missing", target_is_directory=True)
    elif mutation == "chained_escape":
        outside = case / "outside"
        outside.mkdir()
        (reference / "z-alias").symlink_to("../outside", target_is_directory=True)
        link.symlink_to("z-alias", target_is_directory=True)
    elif mutation == "cycle":
        (reference / "z-alias").symlink_to("lib64", target_is_directory=True)
        link.symlink_to("z-alias", target_is_directory=True)
    elif mutation == "special_device":
        os.mkfifo(reference / "device")
        link.symlink_to("device")
    elif mutation == "protected_state":
        (reference / "state").mkdir()
        link.symlink_to("state", target_is_directory=True)
    elif mutation == "noncanonical":
        link.symlink_to("./lib", target_is_directory=True)
    with pytest.raises(AssertionError):
        gate._runtime_tree_inventory(reference)


@pytest.mark.parametrize(
    ("mutation", "replacement", "extra_members", "allowed_directories"),
    [
        ("absolute", ("symlink", "/runtime/lib"), {}, {"runtime/lib"}),
        ("escape", ("symlink", "../../etc"), {}, {"runtime/lib"}),
        ("dangling", ("symlink", "missing"), {}, {"runtime/lib"}),
        (
            "chained_escape",
            ("symlink", "z-alias"),
            {"runtime/z-alias": ("symlink", "../../etc")},
            {"runtime/lib"},
        ),
        (
            "cycle",
            ("symlink", "z-alias"),
            {"runtime/z-alias": ("symlink", "lib64")},
            {"runtime/lib"},
        ),
        ("special_device", ("fifo", ""), {}, {"runtime/lib"}),
        ("protected_state", ("symlink", "state"), {}, {"runtime/lib", "runtime/state"}),
        ("noncanonical", ("symlink", "./lib"), {}, {"runtime/lib"}),
    ],
)
def test_v11_package_rejects_unsafe_directory_links(
    tmp_path,
    mutation,
    replacement,
    extra_members,
    allowed_directories,
):
    members = _safe_package_members()
    members["runtime/lib64"] = replacement
    members.update(extra_members)
    package = tmp_path / f"hostile-{mutation}.tar"
    package.write_bytes(synthetic_tar(members))
    with pytest.raises(AssertionError):
        inspect_package(
            package,
            allowed_members=set(members),
            allowed_runtime_directories=allowed_directories,
        )


@pytest.mark.parametrize("replacement", [("symlink", "lib-real"), b"not-a-link\n"])
def test_v11_candidate_reference_link_mismatch_fails_closed(tmp_path, replacement):
    reference_members = _safe_package_members()
    reference_members["runtime/lib-real/module.py"] = b"ALT = 1\n"
    expected_package = tmp_path / "expected.tar"
    expected_package.write_bytes(synthetic_tar(reference_members))
    expected_package.chmod(0o600)
    expected = inspect_package(
        expected_package,
        allowed_members=set(reference_members),
        allowed_runtime_directories={"runtime/lib", "runtime/lib-real"},
    )

    candidate_members = dict(reference_members)
    candidate_members["runtime/lib64"] = replacement
    candidate = tmp_path / ("candidate-" + hashlib.sha256(repr(replacement).encode()).hexdigest() + ".tar")
    candidate.write_bytes(synthetic_tar(candidate_members))
    candidate.chmod(0o600)
    allowed_members = set(expected)
    observed = inspect_package(
        candidate,
        allowed_members=allowed_members,
        allowed_runtime_directories={"runtime/lib", "runtime/lib-real"},
    )
    assert observed != expected
    manifest = _package_manifest(candidate, observed)
    manifest_path = candidate.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError, match="bytes/modes/links differ"):
        validate_package(
            candidate,
            manifest_path,
            release="A",
            source_commit="a" * 40,
            expected_members=expected,
            expected_runtime_directories={"runtime/lib", "runtime/lib-real"},
        )


def test_v11_explicit_archive_directories_are_not_silently_discarded(tmp_path):
    members = _safe_package_members()
    members["runtime/lib"] = ("directory", "")
    package = tmp_path / "explicit-directory.tar"
    package.write_bytes(synthetic_tar(members))
    with pytest.raises(AssertionError, match="explicit package directory"):
        inspect_package(
            package,
            allowed_members=set(_safe_package_members()),
            allowed_runtime_directories={"runtime/lib"},
        )


def _alternate_tar(members: dict[str, bytes | tuple[str, str]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, value in reversed(sorted(members.items())):
            info = tarfile.TarInfo(name)
            info.mtime = 1
            info.uid = info.gid = 0
            if isinstance(value, tuple):
                kind, target = value
                assert kind == "symlink"
                info.type = tarfile.SYMTYPE
                info.linkname = target
                info.mode = 0o777
                archive.addfile(info)
            else:
                info.mode = 0o555
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
    return buffer.getvalue()


def test_v11_validation_rejects_path_replacement_after_pinned_snapshot(tmp_path, monkeypatch):
    members = _safe_package_members()
    package = tmp_path / "candidate.tar"
    package.write_bytes(synthetic_tar(members))
    package.chmod(0o600)
    observed = inspect_package(
        package,
        allowed_members=set(members),
        allowed_runtime_directories={"runtime/lib"},
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_package_manifest(package, observed)),
        encoding="utf-8",
    )
    hostile = tmp_path / "replacement.tar"
    hostile.write_bytes(_alternate_tar(members))
    hostile.chmod(0o600)
    assert hashlib.sha256(hostile.read_bytes()).hexdigest() != hashlib.sha256(
        package.read_bytes()
    ).hexdigest()

    real_open = support.tarfile.open
    replaced = False

    def replace_before_inspection(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            os.replace(hostile, package)
            replaced = True
        return real_open(*args, **kwargs)

    monkeypatch.setattr(support.tarfile, "open", replace_before_inspection)
    with pytest.raises(AssertionError, match="path identity changed during validation"):
        validate_package(
            package,
            manifest_path,
            release="A",
            source_commit="a" * 40,
            expected_members=observed,
            expected_runtime_directories={"runtime/lib"},
        )
    assert replaced is True


def test_v11_runner_has_no_new_activation_executable_surface():
    path = ROOT / "docs/tasks/303/v11_delivery_gate.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    raw_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        dotted = f"{getattr(node.func.value, 'id', '')}.{node.func.attr}"
        if dotted in {
            "os.system",
            "os.execv",
            "os.execve",
            "subprocess.Popen",
            "subprocess.run",
        }:
            raw_calls.append(dotted)
    assert raw_calls == []
    assert "shell=True" not in source
    assert "systemctl" not in source
    assert "authorize-commit" not in source
    assert source.count("v10._run_command(") == 3
    assert "sha256_path(package)" not in source
    assert 'validation["package_sha256"]' in source
    assert 'validation["manifest_sha256"]' in source
    build_start = source.index("def _build_package(")
    expected_at = source.index("_expected_package_inventory(", build_start)
    builder_at = source.index("completed = v10._run_command(", expected_at)
    assert expected_at < builder_at
