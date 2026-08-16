"""Green self-tests for the V12 deterministic final-prefix runtime contract."""

import ast
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle_v12_support as support  # noqa: E402
import test_v11_delivery_oracle as v11_tests  # noqa: E402
import v10_delivery_gate as v10  # noqa: E402
import v12_delivery_gate as gate  # noqa: E402
from oracle_v11_support import inspect_package, synthetic_tar  # noqa: E402
from oracle_v12_support import (  # noqa: E402
    REQUIRED_PACKAGE_MEMBERS,
    derive_install_prefix,
    runtime_tree_inventory,
    validate_package,
)


ROOT = Path(__file__).resolve().parents[3]
SOURCE_COMMIT = "a" * 40
INSTALL_PREFIX = derive_install_prefix("A", SOURCE_COMMIT)
V9_TO_V11_SHA256 = {
    **v11_tests.V9_AND_V10_SHA256,
    "oracle_v11_support.py": "4e150be3a3c4e544fcdc782ae6205648645b2f0325cc356db9aaa84c858e7507",
    "v11_delivery_gate.py": "36d866b22bf145cd17bc587315c7a4dac6c26216ab9bcbbd2941f35f0faadbad",
    "test_v11_delivery_oracle.py": "dc8fe816d94815cfb2054c64dab58914768ecc4719d7330011851362bd42f0ea",
}


def _hash_record(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
    return f"sha256={digest}"


def _fixture_reference(root: Path) -> Path:
    reference = root / "reference"
    scripts = reference / "bin"
    site = reference / "lib/python3.12/site-packages"
    dist = site / "fixture-1.0.dist-info"
    scripts.mkdir(parents=True)
    dist.mkdir(parents=True)
    python = scripts / "python"
    python.write_bytes(b"python-3.12\n")
    python.chmod(0o755)
    (reference / "pyvenv.cfg").write_text("version = 3.12\n", encoding="utf-8")
    prefix = str(reference)
    activation = {
        "activate": f"header\nVIRTUAL_ENV='{prefix}'\n",
        "activate.bat": f'header\n@for %%i in ("{prefix}") do @set "VIRTUAL_ENV=%%~fi"\n',
        "activate.csh": f"header\nsetenv VIRTUAL_ENV '{prefix}'\n",
        "activate.fish": f"header\nset -gx VIRTUAL_ENV '{prefix}'\n",
        "activate.nu": f"header\n    let virtual_env = '{prefix}'\n",
    }
    for name, text in activation.items():
        (scripts / name).write_text(text, encoding="utf-8")
    tool = f"#!{prefix}/bin/python\nprint('ok')\n".encode()
    (scripts / "fixture-tool").write_bytes(tool)
    (scripts / "fixture-tool").chmod(0o755)
    module = site / "fixture.py"
    module.write_bytes(b"VALUE = 1\n")
    rows = [
        ["../../../bin/fixture-tool", _hash_record(tool), str(len(tool))],
        ["fixture.py", _hash_record(module.read_bytes()), str(module.stat().st_size)],
        ["fixture-1.0.dist-info/RECORD", "", ""],
    ]
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    (dist / "RECORD").write_text(stream.getvalue(), encoding="utf-8")
    (reference / "lib64").symlink_to("lib", target_is_directory=True)
    return reference


def _manifest(package: Path, observed: dict, *, install_prefix: str = INSTALL_PREFIX) -> dict:
    return {
        "schema": "orchestra.runtime-package.v2",
        "release": "A",
        "source_commit": SOURCE_COMMIT,
        "install_prefix": install_prefix,
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


def _normalized_members(reference: Path) -> tuple[dict[str, bytes | tuple[str, str]], dict]:
    content, links, directories, stats = support._normalized_runtime_bytes(
        reference,
        install_prefix=INSTALL_PREFIX,
    )
    assert stats == {"activation": 5, "shebang": 1, "record": 1}
    members: dict[str, bytes | tuple[str, str]] = dict(content)
    members.update({name: ("symlink", target) for name, target in links.items()})
    members.update({name: b"payload\n" for name in REQUIRED_PACKAGE_MEMBERS["A"] - set(members)})
    package = reference.parent / "expected.tar"
    package.write_bytes(synthetic_tar(members))
    observed = inspect_package(
        package,
        allowed_members=set(members),
        allowed_runtime_directories=directories,
    )
    return members, observed


def _validate_members(
    tmp_path: Path,
    members: dict[str, bytes | tuple[str, str]],
    expected: dict,
    *,
    install_prefix: str = INSTALL_PREFIX,
):
    package = tmp_path / "candidate.tar"
    package.write_bytes(synthetic_tar(members))
    package.chmod(0o600)
    observed = inspect_package(
        package,
        allowed_members=set(expected),
        allowed_runtime_directories={"runtime/bin", "runtime/lib", "runtime/lib/python3.12", "runtime/lib/python3.12/site-packages", "runtime/lib/python3.12/site-packages/fixture-1.0.dist-info"},
    )
    manifest = tmp_path / "candidate.json"
    manifest.write_text(json.dumps(_manifest(package, observed, install_prefix=install_prefix)), encoding="utf-8")
    return validate_package(
        package,
        manifest,
        release="A",
        source_commit=SOURCE_COMMIT,
        expected_members=expected,
        expected_runtime_directories={"runtime/bin", "runtime/lib", "runtime/lib/python3.12", "runtime/lib/python3.12/site-packages", "runtime/lib/python3.12/site-packages/fixture-1.0.dist-info"},
    )


def test_v12_preserves_every_v9_v10_and_v11_oracle_byte():
    task_dir = ROOT / "docs/tasks/303"
    observed = {
        name: hashlib.sha256((task_dir / name).read_bytes()).hexdigest()
        for name in V9_TO_V11_SHA256
    }
    assert observed == V9_TO_V11_SHA256


def test_v12_retains_v11_pending_only_toc_tou_and_link_controls(tmp_path):
    v11_tests.test_v11_retains_v10_pending_report_and_secret_mutations(tmp_path)
    v11_tests.test_v11_explicit_archive_directories_are_not_silently_discarded(tmp_path)
    with pytest.MonkeyPatch.context() as monkeypatch:
        v11_tests.test_v11_validation_rejects_path_replacement_after_pinned_snapshot(
            tmp_path, monkeypatch
        )


def test_v12_two_fresh_real_runtimes_normalize_to_one_final_prefix():
    with tempfile.TemporaryDirectory(prefix="task303-v12-two-build-", dir="/var/tmp") as raw:
        scratch = Path(raw)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "INTERNAL_TOKEN"}
        }
        environment["HOME"] = str(scratch / "home")
        environment["UV_CACHE_DIR"] = "/var/tmp/orchestra-task303-uv-cache-kesha"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        Path(environment["HOME"]).mkdir(mode=0o700)
        uv = shutil.which("uv", path=os.environ.get("PATH"))
        assert uv
        one, one_dirs, one_stats = gate._reference_runtime_inventory(
            scratch / "one",
            uv=str(Path(uv).resolve()),
            environment=environment,
            install_prefix=INSTALL_PREFIX,
        )
        two, two_dirs, two_stats = gate._reference_runtime_inventory(
            scratch / "two",
            uv=str(Path(uv).resolve()),
            environment=environment,
            install_prefix=INSTALL_PREFIX,
        )
        assert one == two
        assert one_dirs == two_dirs
        assert one_stats == two_stats == {"activation": 5, "shebang": 17, "record": 16}
        assert len(one) == 3438 and len(one_dirs) == 408


def test_v12_fixture_prefix_normalization_and_record_recompute_are_satisfiable(tmp_path):
    first = _fixture_reference(tmp_path / "first")
    second = _fixture_reference(tmp_path / "second")
    one, one_dirs, one_stats = runtime_tree_inventory(first, install_prefix=INSTALL_PREFIX)
    two, two_dirs, two_stats = runtime_tree_inventory(second, install_prefix=INSTALL_PREFIX)
    assert one == two and one_dirs == two_dirs
    assert one_stats == two_stats == {"activation": 5, "shebang": 1, "record": 1}
    members, expected = _normalized_members(first)
    validation = _validate_members(tmp_path, members, expected)
    assert validation["manifest"]["install_prefix"] == INSTALL_PREFIX


def test_v12_rejects_unclassified_embedded_build_prefix(tmp_path):
    reference = _fixture_reference(tmp_path)
    module = reference / "lib/python3.12/site-packages/fixture.py"
    module.write_text(f"BUILD_ROOT = {str(reference)!r}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="unclassified embedded runtime prefix"):
        runtime_tree_inventory(reference, install_prefix=INSTALL_PREFIX)


def test_v12_rejects_arbitrary_or_mismatched_install_prefix(tmp_path):
    reference = _fixture_reference(tmp_path / "source")
    with pytest.raises(AssertionError, match="fixed versioned path"):
        runtime_tree_inventory(reference, install_prefix="/tmp/oracle-private-prefix")
    members, expected = _normalized_members(reference)
    with pytest.raises(AssertionError):
        _validate_members(
            tmp_path,
            members,
            expected,
            install_prefix="/opt/orchestra/runtimes/" + "b" * 40 + "-a-py312",
        )


def test_v12_rejects_shebang_record_mismatch(tmp_path):
    reference = _fixture_reference(tmp_path / "source")
    members, expected = _normalized_members(reference)
    record = "runtime/lib/python3.12/site-packages/fixture-1.0.dist-info/RECORD"
    members[record] = (reference / record.removeprefix("runtime/")).read_bytes()
    with pytest.raises(AssertionError, match="normalized independent inventory"):
        _validate_members(tmp_path, members, expected)


def test_v12_rejects_candidate_manifest_common_mode_prefix_lie(tmp_path):
    reference = _fixture_reference(tmp_path / "source")
    members, expected = _normalized_members(reference)
    lie = b"/opt/orchestra/runtimes/" + b"b" * 40 + b"-a-py312"
    script = members["runtime/bin/fixture-tool"]
    assert isinstance(script, bytes)
    members["runtime/bin/fixture-tool"] = script.replace(INSTALL_PREFIX.encode(), lie)
    record = "runtime/lib/python3.12/site-packages/fixture-1.0.dist-info/RECORD"
    record_bytes = members[record]
    assert isinstance(record_bytes, bytes)
    rows = list(csv.reader(io.StringIO(record_bytes.decode())))
    payload = members["runtime/bin/fixture-tool"]
    for row in rows:
        if row[0] == "../../../bin/fixture-tool":
            row[1], row[2] = _hash_record(payload), str(len(payload))
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    members[record] = stream.getvalue().encode()
    with pytest.raises(AssertionError, match="normalized independent inventory"):
        _validate_members(tmp_path, members, expected)


def test_v12_runner_passes_only_the_derived_final_prefix_to_the_builder():
    source = (ROOT / "docs/tasks/303/v12_delivery_gate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "--install-prefix" in source
    assert "derive_install_prefix(release, source_commit)" in source
    assert "--reference-runtime" not in source
    assert "oracle-private-prefix" not in source
    assert "systemctl" not in source and "authorize-commit" not in source
    raw_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        dotted = f"{getattr(node.func.value, 'id', '')}.{node.func.attr}"
        if dotted in {"os.system", "os.execv", "os.execve", "subprocess.Popen", "subprocess.run"}:
            raw_calls.append(dotted)
    assert raw_calls == []
    assert source.count("v10._run_command(") == 3
