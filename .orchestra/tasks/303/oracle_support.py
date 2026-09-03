"""Immutable helpers for the #303 release-gate acceptance oracles."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import time
from typing import Any


RUNTIME_ROOT = Path("/var/lib/orchestra-runtime")
CONTROL_SELECTION = RUNTIME_ROOT / "control-plane-selected.json"
ACTIVATION_ROOT = RUNTIME_ROOT / "activations"
ATTESTATION_ROOT = RUNTIME_ROOT / "attestations/task303"
ATTESTATION_STATE = RUNTIME_ROOT / "attestation-state"
ATTESTATION_PRIVATE_KEY = RUNTIME_ROOT / "keys/attestation-ed25519.key"
ATTESTATION_PUBLIC_KEY = RUNTIME_ROOT / "keys/attestation-ed25519.pub"
PROVIDER_MANIFEST = RUNTIME_ROOT / "provider-selection.json"
MAX_ATTESTATION_LIFETIME_NS = 10 * 60 * 1_000_000_000
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_HEX128_RE = re.compile(r"[0-9a-f]{128}")

ARTIFACT_ROLES = ("runtime_manager", "activation_probe", "activation_hook")
PUBLIC_ACTIVATION_COMMAND = "activate"
PUBLIC_AUTHORIZATION_COMMAND = "authorize-commit"
ACTIVATION_UNITS = {
    "recovery": (
        Path("/etc/systemd/system/orchestra-runtime-recovery@.service"),
        PUBLIC_ACTIVATION_COMMAND,
    ),
    "boundary": (
        Path("/etc/systemd/system/orchestra-boundary-activate@.service"),
        PUBLIC_AUTHORIZATION_COMMAND,
    ),
}
AUTHORITY_SURFACE_MANIFEST = Path("deploy/orchestra-authority-surface.json")
AUTHORITY_OWNER_SOURCE = Path("scripts/manage_orchestra_runtime.py")
AUTHORITY_PACKAGER_SOURCE = Path("scripts/build-orchestra-runtime-package.py")
AUTHORITY_CALLER_SOURCES = {
    "recovery": Path("deploy/orchestra-runtime-recovery@.service"),
    "boundary": Path("deploy/orchestra-boundary-activate@.service"),
}
AUTHORITY_INSTALLER_SOURCE = Path("deploy/install.sh")
SAFE_INSTALLER_SOURCE = """#!/bin/sh
set -eu
if [ "$(/usr/bin/id -u)" -eq 0 ]; then
    echo "deploy/install.sh is an unprivileged package-builder wrapper; use the recovery runbook for root installation" >&2
    exit 77
fi
script_dir=${0%/*}
[ "$script_dir" != "$0" ] || script_dir=.
exec /usr/bin/python3 "$script_dir/../scripts/build-orchestra-runtime-package.py" "$@"
"""
AUTHORITY_STATE_PATHS = (
    "current",
    "deploy-state/active.json",
    "activation-state/admission.json",
    "activation-state/process.json",
    "activation-state/apply.jsonl",
    "attestation-state/consumed",
)
OPENSSL = Path("/usr/bin/openssl")
RFC8032_VECTOR_2 = {
    "seed": bytes.fromhex(
        "4ccd089b28ff96da9db6c346ec114e0f"
        "5b8a319f35aba624da8cf6ed4fb8a6fb"
    ),
    "public_key": bytes.fromhex(
        "3d4017c3e843895a92b70aa74d1b7ebc"
        "9c982ccf2ec4968cc0cd55f12af4660c"
    ),
    "message": bytes.fromhex("72"),
    "signature": bytes.fromhex(
        "92a009a9f0d4cab8720e820b5f642540"
        "a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c"
        "387b2eaeb4302aeeb00d291612bb0c00"
    ),
}
RFC8032_WRONG_PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a"
    "0ee172f3daa62325af021a68f707511a"
)


def _shipped_authority_sources(root: Path) -> list[Path]:
    paths = list((root / "app").rglob("*.py"))
    for directory in (root / "scripts", root / "deploy"):
        paths.extend(path for path in directory.rglob("*") if path.is_file() or path.is_symlink())
    relative = {path.relative_to(root): path for path in paths}
    assert relative, "shipped authority source inventory is empty"
    return [relative[name] for name in sorted(relative, key=lambda item: item.as_posix())]


def _shell_segments(source: str) -> list[list[str]]:
    logical = source.replace("\\\n", " ").splitlines()
    segments: list[list[str]] = []
    for raw_line in logical:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for segment in re.split(r"(?:&&|\|\||;)", line):
            try:
                tokens = shlex.split(segment, comments=True, posix=True)
            except ValueError:
                tokens = re.findall(r"[^\s;&|]+", segment)
            if tokens:
                segments.append(tokens)
    return segments


def _python_authority_references(source: str) -> list[str]:
    tree = ast.parse(source)
    references: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend(alias.name for alias in node.names if "manage_orchestra_runtime" in alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "manage_orchestra_runtime" in module:
                references.append(module)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if (
                str(RUNTIME_ROOT) in value
                or "orchestra-runtime-recovery@" in value
                or "orchestra-boundary-activate@" in value
                or re.search(r"(?<![\w-])(?:activate|authorize-commit)(?![\w-])", value)
            ):
                references.append(value)
    return references


def assert_shipped_activation_surface(root: Path) -> dict[str, Any]:
    """Prove the two fixed units are the only shipped callers of root activation authority."""
    manifest_path = root / AUTHORITY_SURFACE_MANIFEST
    assert manifest_path.is_file() and not manifest_path.is_symlink(), (
        "T-A missing behavior: no shipped activation-surface manifest exists"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "schema": "orchestra.activation-surface.v1",
        "authority_owner": AUTHORITY_OWNER_SOURCE.as_posix(),
        "non_authority_packager": AUTHORITY_PACKAGER_SOURCE.as_posix(),
        "activation_callers": {
            kind: path.as_posix() for kind, path in AUTHORITY_CALLER_SOURCES.items()
        },
        "installer": AUTHORITY_INSTALLER_SOURCE.as_posix(),
        "source_roots": ["app", "scripts", "deploy"],
    }, "activation-surface manifest is not the fixed independently expected inventory"

    sources = _shipped_authority_sources(root)
    relative_sources = {path.relative_to(root) for path in sources}
    required = {
        AUTHORITY_OWNER_SOURCE,
        AUTHORITY_PACKAGER_SOURCE,
        AUTHORITY_INSTALLER_SOURCE,
        AUTHORITY_SURFACE_MANIFEST,
        *AUTHORITY_CALLER_SOURCES.values(),
    }
    missing = sorted((required - relative_sources), key=lambda item: item.as_posix())
    assert not missing, f"activation surface is missing shipped files: {missing}"

    violations: list[str] = []
    allowed_reference_files = {
        AUTHORITY_OWNER_SOURCE,
        AUTHORITY_SURFACE_MANIFEST,
        *AUTHORITY_CALLER_SOURCES.values(),
    }
    for path in sources:
        relative = path.relative_to(root)
        assert not path.is_symlink(), f"shipped authority source is a symlink: {relative}"
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise AssertionError(f"shipped source inventory contains non-UTF-8 file: {relative}") from exc

        if relative == AUTHORITY_INSTALLER_SOURCE:
            assert source == SAFE_INSTALLER_SOURCE, (
                "alternate shipped activation authority exists: deploy/install.sh is not "
                "the exact root-refusing package-builder wrapper"
            )
            continue

        if relative in AUTHORITY_CALLER_SOURCES.values():
            kind = next(kind for kind, value in AUTHORITY_CALLER_SOURCES.items() if value == relative)
            expected_operation = ACTIVATION_UNITS[kind][1]
            parse_activation_unit_command(
                source,
                expected_manager=Path("@CONTROL_PLANE_ROOT@/runtime-manager"),
                expected_operation=expected_operation,
            )
            continue

        if path.suffix == ".py" and relative != AUTHORITY_OWNER_SOURCE:
            references = _python_authority_references(source)
            if relative == AUTHORITY_PACKAGER_SOURCE:
                references = [
                    reference
                    for reference in references
                    if not (
                        "orchestra-runtime-recovery@" in reference
                        or "orchestra-boundary-activate@" in reference
                    )
                ]
            if references:
                violations.append(f"{relative}:python_authority_reference")

        if relative.parts[0] in {"scripts", "deploy"} and path.suffix != ".py":
            segments = _shell_segments(source)
            manager_named = "manage_orchestra_runtime.py" in source or "runtime-manager" in source
            root_authority_named = manager_named or any(
                marker in source
                for marker in (
                    str(RUNTIME_ROOT),
                    "orchestra-runtime-recovery@",
                    "orchestra-boundary-activate@",
                    PUBLIC_AUTHORIZATION_COMMAND,
                )
            )
            operations = {
                token
                for segment in segments
                for token in segment
                if token in {PUBLIC_ACTIVATION_COMMAND, PUBLIC_AUTHORIZATION_COMMAND}
            }
            if relative not in allowed_reference_files and operations:
                violations.append(f"{relative}:manager_operation:{sorted(operations)}")
            if relative != AUTHORITY_OWNER_SOURCE and manager_named:
                for segment in segments:
                    if any("manage_orchestra_runtime.py" in token or "runtime-manager" in token for token in segment):
                        if any("$" in token for token in segment):
                            violations.append(f"{relative}:indirect_manager_command")
                        if any(token in {PUBLIC_ACTIVATION_COMMAND, PUBLIC_AUTHORIZATION_COMMAND} for token in segment):
                            violations.append(f"{relative}:direct_manager_authority")

            for segment in segments:
                if (
                    root_authority_named
                    and segment[0].lstrip('"\'').startswith("$")
                    and any(
                        token in {"start", "restart", "enable", PUBLIC_ACTIVATION_COMMAND, PUBLIC_AUTHORIZATION_COMMAND}
                        for token in segment[1:]
                    )
                ):
                    violations.append(f"{relative}:indirect_authority_executable")
                executables = [index for index, token in enumerate(segment) if Path(token).name == "systemctl"]
                for index in executables:
                    invocation = segment[index:]
                    allowed_installer_command = invocation in (
                        ["systemctl", "daemon-reload"],
                        ["/usr/bin/systemctl", "daemon-reload"],
                        ["systemctl", "enable", "--now", "orchestra.socket"],
                        ["/usr/bin/systemctl", "enable", "--now", "orchestra.socket"],
                        ["systemctl", "reload", "nginx"],
                        ["/usr/bin/systemctl", "reload", "nginx"],
                    )
                    if (
                        relative == AUTHORITY_INSTALLER_SOURCE
                        and not allowed_installer_command
                    ) or (
                        relative != AUTHORITY_INSTALLER_SOURCE and root_authority_named
                    ):
                        violations.append(f"{relative}:non_install_systemctl:{invocation}")
                if root_authority_named and any(Path(token).name == "systemd-run" for token in segment):
                    violations.append(f"{relative}:systemd_run")
                if relative == AUTHORITY_INSTALLER_SOURCE and any(
                    re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=(?:.*/)?systemctl", token)
                    for token in segment
                ):
                    violations.append(f"{relative}:indirect_systemctl")

    assert not violations, "alternate shipped activation authority exists: " + "; ".join(sorted(set(violations)))
    return {
        "authority_owner": AUTHORITY_OWNER_SOURCE.as_posix(),
        "activation_callers": {
            kind: path.as_posix() for kind, path in AUTHORITY_CALLER_SOURCES.items()
        },
        "files_scanned": [path.relative_to(root).as_posix() for path in sources],
    }


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while block := os.read(fd, 1024 * 1024):
        digest.update(block)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def artifact_identity_fd(fd: int) -> dict[str, Any]:
    observed = os.fstat(fd)
    assert stat.S_ISREG(observed.st_mode), "control artifact is not a regular file"
    return {
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "size": observed.st_size,
        "mode": stat.S_IMODE(observed.st_mode),
        "sha256": _sha256_fd(fd),
    }


def artifact_identity_path(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return artifact_identity_fd(fd)
    finally:
        os.close(fd)


def snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    """Return an exact content/type snapshot used around authorization attempts."""
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for path in [root, *sorted(root.rglob("*"))]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        observed = path.lstat()
        row: dict[str, Any] = {
            "mode": stat.S_IMODE(observed.st_mode),
            "device": observed.st_dev,
            "inode": observed.st_ino,
        }
        if stat.S_ISDIR(observed.st_mode):
            row["type"] = "directory"
        elif stat.S_ISREG(observed.st_mode):
            row.update(
                type="file",
                size=observed.st_size,
                sha256=sha256_path(path),
            )
        elif stat.S_ISLNK(observed.st_mode):
            row.update(type="symlink", target=os.readlink(path))
        else:
            row["type"] = "special"
        result[relative] = row
    return result


def canonical_attestation_payload(attestation: dict[str, Any]) -> bytes:
    unsigned = copy.deepcopy(attestation)
    unsigned.pop("signature", None)
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def independent_ed25519_verify(
    public_key: bytes,
    message: bytes,
    signature: bytes,
    workdir: Path,
) -> bool:
    """Verify with the system OpenSSL CLI, independently of production Python code."""
    assert OPENSSL.is_file(), "independent Ed25519 verifier is unavailable"
    assert len(public_key) == 32
    workdir.mkdir(parents=True, exist_ok=True)
    public_path = workdir / "public.der"
    message_path = workdir / "message.bin"
    signature_path = workdir / "signature.bin"
    public_path.write_bytes(bytes.fromhex("302a300506032b6570032100") + public_key)
    message_path.write_bytes(message)
    signature_path.write_bytes(signature)
    completed = subprocess.run(
        [
            str(OPENSSL),
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(public_path),
            "-keyform",
            "DER",
            "-rawin",
            "-in",
            str(message_path),
            "-sigfile",
            str(signature_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.returncode == 0


def sign_ed25519_test_message(seed: bytes, message: bytes, workdir: Path) -> bytes:
    """Sign scratch oracle input with the RFC 8032 seed through OpenSSL."""
    assert OPENSSL.is_file()
    assert len(seed) == 32
    workdir.mkdir(parents=True, exist_ok=True)
    private_path = workdir / "private.der"
    message_path = workdir / "message.bin"
    signature_path = workdir / "signature.bin"
    private_path.write_bytes(bytes.fromhex("302e020100300506032b657004220420") + seed)
    private_path.chmod(0o600)
    message_path.write_bytes(message)
    completed = subprocess.run(
        [
            str(OPENSSL),
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_path),
            "-keyform",
            "DER",
            "-rawin",
            "-in",
            str(message_path),
            "-out",
            str(signature_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    signature = signature_path.read_bytes()
    assert len(signature) == 64
    return signature


def _copy_artifacts_to_install(
    source_artifacts: dict[str, Path], install_root: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, Path]]:
    install_root.mkdir(parents=True)
    manifest: dict[str, dict[str, Any]] = {}
    installed: dict[str, Path] = {}
    for role in ARTIFACT_ROLES:
        source = source_artifacts[role]
        destination = install_root / f"{role}.py"
        shutil.copyfile(source, destination)
        destination.chmod(0o500)
        identity = artifact_identity_path(destination)
        installed[role] = destination
        manifest[role] = {
            "path": str(destination),
            "identity": identity,
            "argv_tail": ["--task303-identity-probe", role],
            "expected_stdout": f"task303-identity:{role}",
        }
    return manifest, installed


def _hostile_script(sentinel: Path, role: str) -> bytes:
    return (
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text({role!r}, encoding='utf-8')\n"
        f"print('hostile:{role}')\n"
    ).encode("utf-8")


def apply_artifact_attack(
    path: Path,
    attack: str,
    *,
    sentinel: Path,
    role: str,
    verified: dict[str, Any],
) -> None:
    """Physically alter an oracle fixture; this function never authorizes execution."""
    hostile = _hostile_script(sentinel, role)
    if attack == "rename":
        replacement = path.parent / f"replacement-{role}.py"
        replacement.write_bytes(hostile)
        replacement.chmod(0o500)
        os.replace(replacement, path)
    elif attack == "symlink":
        replacement = path.parent / f"symlink-target-{role}.py"
        replacement.write_bytes(hostile)
        replacement.chmod(0o500)
        path.unlink()
        path.symlink_to(replacement)
    elif attack == "inode_preserving_content":
        original = bytearray(path.read_bytes())
        assert original
        offset = original.find(b"\n") + 1
        assert 0 < offset < len(original)
        original[offset] ^= 1
        path.chmod(0o700)
        with path.open("r+b", buffering=0) as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o500)
        assert path.stat().st_ino == verified["inode"]
        assert path.stat().st_size == verified["size"]
    else:
        raise AssertionError(f"unknown attack: {attack}")


def snapshot_authority_state(state_root: Path) -> dict[str, Any]:
    """Snapshot only the selector/admission/process/ledger paths owned by production."""
    observed: dict[str, Any] = {}
    for relative in AUTHORITY_STATE_PATHS:
        path = state_root / relative
        if not path.exists() and not path.is_symlink():
            observed[relative] = {"type": "missing"}
            continue
        tree = snapshot_tree(path)
        observed[relative] = tree
    return observed


def _assert_single_apply_state(
    state_root: Path,
    *,
    activation_id: str,
    winner_pid: int | None = None,
    loser_pid: int | None = None,
) -> None:
    assert (state_root / "current").resolve(strict=True) == (
        state_root / "releases/new"
    ).resolve(strict=True)
    active = json.loads((state_root / "deploy-state/active.json").read_text())
    admission = json.loads((state_root / "activation-state/admission.json").read_text())
    process = json.loads((state_root / "activation-state/process.json").read_text())
    assert active["activation_id"] == admission["activation_id"] == process["activation_id"] == activation_id
    assert active["apply_count"] == admission["apply_count"] == process["apply_count"] == 1
    assert active["release"] == "new" and admission["open"] is True
    assert process["start_count"] == 1
    apply_rows = [
        json.loads(line)
        for line in (state_root / "activation-state/apply.jsonl").read_text().splitlines()
        if line
    ]
    assert len(apply_rows) == 1
    assert apply_rows[0]["activation_id"] == activation_id
    assert apply_rows[0]["apply_count"] == 1
    if winner_pid is not None:
        assert apply_rows[0]["actor_pid"] == winner_pid
    if loser_pid is not None:
        assert str(loser_pid) not in json.dumps(
            {
                "active": active,
                "admission": admission,
                "process": process,
                "apply": apply_rows,
            },
            sort_keys=True,
        )


def _wait_for_path(path: Path, process: subprocess.Popen[str], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"public manager exited before {path.name}: {stdout or stderr}"
            )
        time.sleep(0.01)
    process.kill()
    stdout, stderr = process.communicate()
    raise AssertionError(f"public manager did not reach {path}: {stdout or stderr}")


def parse_activation_unit_command(
    unit_text: str,
    *,
    expected_manager: Path,
    expected_operation: str,
) -> list[str]:
    """Parse the one deliberately shell-free ExecStart used as activation authority."""
    lines = [line.strip() for line in unit_text.splitlines()]
    exec_lines = [
        line.removeprefix("ExecStart=")
        for line in lines
        if line.startswith("ExecStart=")
    ]
    assert len(exec_lines) == 1, "activation unit must have exactly one ExecStart"
    assert not any(
        line.startswith("Exec") and not line.startswith("ExecStart=") for line in lines
    ), "activation authority must not have another executable directive"
    assert not any(
        line.startswith(("Environment=", "EnvironmentFile="))
        for line in lines
    ), "activation authority must not depend on an injected environment"
    assert [line for line in lines if line.startswith("Type=")] == ["Type=oneshot"]
    assert [line for line in lines if line.startswith("User=")] == ["User=root"]
    forbidden_context = (
        "RootDirectory=",
        "RootImage=",
        "BindPaths=",
        "BindReadOnlyPaths=",
        "TemporaryFileSystem=",
        "MountImages=",
        "ExtensionImages=",
    )
    assert not any(line.startswith(forbidden_context) for line in lines), (
        "activation unit may not remap the selected executable"
    )
    argv = shlex.split(exec_lines[0], posix=True)
    assert argv == [
        str(expected_manager),
        expected_operation,
        "--state-root",
        str(RUNTIME_ROOT),
        "--activation-id",
        "%i",
    ], "installed activation unit does not enter the pinned public manager operation"
    return argv


def parse_systemd_execstart_property(value: str) -> list[str]:
    """Extract argv from the deliberately single-command `systemctl show` record."""
    assert value.count("{ path=") == 1 and value.count("argv[]=") == 1
    match = re.fullmatch(
        r"\{ path=([^;]+) ; argv\[\]=([^;]+) ; ignore_errors=no ;.*\}", value
    )
    assert match, "unexpected effective ExecStart representation"
    executable = match.group(1).strip()
    argv = shlex.split(match.group(2).strip(), posix=True)
    assert argv and argv[0] == executable
    return argv


def _assert_systemd_loaded_command(unit_path: Path, template_argv: list[str]) -> None:
    probe_id = "task303-oracle"
    unit_name = unit_path.name.replace("@.service", f"@{probe_id}.service")
    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"):
        env.pop(key, None)
    completed = subprocess.run(
        [
            "/usr/bin/systemctl",
            "show",
            unit_name,
            "--property=LoadState",
            "--property=FragmentPath",
            "--property=DropInPaths",
            "--property=ExecStart",
            "--no-pager",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    properties = dict(
        line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
    )
    assert properties.get("LoadState") == "loaded"
    assert Path(properties.get("FragmentPath", "")) == unit_path
    assert properties.get("DropInPaths") == "", "activation unit has effective drop-ins"
    expected = _retarget_activation_command(template_argv, RUNTIME_ROOT, probe_id)
    assert parse_systemd_execstart_property(properties.get("ExecStart", "")) == expected


def selected_activation_unit_command(kind: str) -> tuple[list[str], Path, dict[str, Any]]:
    """Derive authority from the installed systemd caller, not a declarative argv."""
    assert kind in ACTIVATION_UNITS, kind
    expected_path, expected_operation = ACTIVATION_UNITS[kind]
    manager, _, selection = trusted_artifact("runtime_manager")
    entry = selection["activation_units"][kind]
    unit_path = Path(entry["path"])
    assert unit_path == expected_path
    assert_root_regular(unit_path)
    assert entry["source_commit"] == selection["source_commit"]
    assert entry["sha256"] == sha256_path(unit_path)
    argv = parse_activation_unit_command(
        unit_path.read_text(encoding="utf-8"),
        expected_manager=manager,
        expected_operation=expected_operation,
    )
    _assert_systemd_loaded_command(unit_path, argv)
    return argv, unit_path, entry


def _retarget_activation_command(
    command: list[str], state_root: Path, activation_id: str
) -> list[str]:
    result = list(command)
    assert result[2:6] == [
        "--state-root",
        str(RUNTIME_ROOT),
        "--activation-id",
        "%i",
    ]
    result[3] = str(state_root)
    result[5] = activation_id
    return result


def _manager_process(command: list[str], arguments: list[str]) -> subprocess.Popen[str]:
    assert command and Path(command[0]).is_absolute()
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env.pop("PYTHONPATH", None)
    env["PATH"] = "/usr/bin:/bin"
    return subprocess.Popen(
        [*command, *arguments],
        cwd=Path(command[0]).parent,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _json_stdout(process: subprocess.Popen[str], timeout: float = 30) -> tuple[int, dict[str, Any]]:
    stdout, stderr = process.communicate(timeout=timeout)
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, stderr or "public manager emitted no result"
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise AssertionError(stderr or stdout) from exc
    return process.returncode, result


def exercise_public_manager_activation(
    activation_argv: list[str],
    source_artifacts: dict[str, Path],
    tmp_path: Path,
) -> dict[str, Any]:
    """Attack the installed recovery unit's public operation after its verify barrier."""
    assert set(source_artifacts) == set(ARTIFACT_ROLES)

    def run_case(case_root: Path, target_role: str | None, attack: str | None):
        manifest, installed = _copy_artifacts_to_install(
            source_artifacts, case_root / "install"
        )
        manifest_path = case_root / "artifacts.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        state_root = case_root / "state"
        sync_root = case_root / "sync"
        sentinel = case_root / "HOSTILE_EXECUTED"
        process = _manager_process(
            _retarget_activation_command(
                activation_argv, state_root, "task303-artifact-gate"
            ),
            [
                "--artifact-manifest",
                str(manifest_path),
                "--oracle-sync-dir",
                str(sync_root),
            ],
        )
        ready_path = sync_root / "artifacts-verified.json"
        _wait_for_path(ready_path, process)
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        assert ready == {
            "operation": PUBLIC_ACTIVATION_COMMAND,
            "phase": "artifacts_verified",
            "verified": {role: manifest[role]["identity"] for role in ARTIFACT_ROLES},
        }
        before = snapshot_authority_state(state_root)
        if target_role is not None:
            apply_artifact_attack(
                installed[target_role],
                attack or "",
                sentinel=sentinel,
                role=target_role,
                verified=manifest[target_role]["identity"],
            )
        (sync_root / "continue").write_text("continue\n", encoding="utf-8")
        returncode, result = _json_stdout(process)
        return {
            "manifest": manifest,
            "before": before,
            "after": snapshot_authority_state(state_root),
            "returncode": returncode,
            "result": result,
            "sentinel": sentinel,
            "state_root": state_root,
        }

    control = run_case(tmp_path / "control", None, None)
    assert control["returncode"] == 0
    assert control["result"]["operation"] == PUBLIC_ACTIVATION_COMMAND
    assert control["result"]["authorized"] is True
    assert control["result"]["reason"] == "authorized"
    assert control["result"]["apply_count"] == 1
    assert control["before"] != control["after"]
    _assert_single_apply_state(
        control["state_root"], activation_id="task303-artifact-gate"
    )
    assert control["result"]["verified"] == control["result"]["executed"]
    assert control["result"]["executed"] == {
        role: control["manifest"][role]["identity"] for role in ARTIFACT_ROLES
    }
    assert not control["sentinel"].exists()

    attacks = []
    for role in ARTIFACT_ROLES:
        for attack in ("rename", "symlink", "inode_preserving_content"):
            name = f"{role}:{attack}"
            row = run_case(tmp_path / name.replace(":", "-"), role, attack)
            attacks.append(name)
            assert row["returncode"] != 0, f"artifact swap was accepted: {name}"
            assert row["result"] == {
                "operation": PUBLIC_ACTIVATION_COMMAND,
                "authorized": False,
                "reason": f"artifact_identity_changed:{role}",
                "apply_count": 0,
            }, f"artifact swap was accepted: {name}"
            assert row["after"] == row["before"], (
                f"real selector/admission/process/ledger state changed after {name}"
            )
            assert not row["sentinel"].exists(), f"hostile payload executed: {name}"
    return {
        "control_verified": control["result"]["verified"],
        "control_executed": control["result"]["executed"],
        "attacks": sorted(attacks),
    }


def signed_scratch_attestation(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    context = {
        "activation_id": "task303-oracle-activation",
        "boot_id": "11111111-2222-3333-4444-555555555555",
        "host_id_sha256": "1" * 64,
        "target_pid": 424242,
        "target_starttime": 987654321,
        "runtime": {
            "path": "/var/lib/orchestra-runtime/releases/oracle/bin/python",
            "device": 17,
            "inode": 23,
            "size": 31,
            "sha256": "2" * 64,
        },
    }
    attestation = {
        "schema": "orchestra.task303.activation-authorization.v1",
        "signature_algorithm": "ed25519",
        "public_key_sha256": hashlib.sha256(
            RFC8032_VECTOR_2["public_key"]
        ).hexdigest(),
        "run_nonce": "3" * 64,
        "issued_at_ns": 1_000_000_000,
        "expires_at_ns": 601_000_000_000,
        "context": copy.deepcopy(context),
    }
    signature = sign_ed25519_test_message(
        RFC8032_VECTOR_2["seed"],
        canonical_attestation_payload(attestation),
        root / "sign",
    )
    attestation["signature"] = signature.hex()
    return attestation, context


def _write_authority_fixture(state_root: Path, activation_id: str) -> None:
    (state_root / "releases/old").mkdir(parents=True)
    (state_root / "releases/new").mkdir(parents=True)
    (state_root / "current").symlink_to(state_root / "releases/old")
    (state_root / "deploy-state").mkdir()
    (state_root / "activation-state").mkdir()
    (state_root / "attestation-state/consumed").mkdir(parents=True)
    (state_root / "deploy-state/active.json").write_text(
        json.dumps({"activation_id": activation_id, "apply_count": 0, "release": "old"}),
        encoding="utf-8",
    )
    (state_root / "activation-state/admission.json").write_text(
        json.dumps({"activation_id": activation_id, "apply_count": 0, "open": False}),
        encoding="utf-8",
    )
    (state_root / "activation-state/process.json").write_text(
        json.dumps({"activation_id": activation_id, "apply_count": 0, "start_count": 0}),
        encoding="utf-8",
    )
    (state_root / "activation-state/apply.jsonl").write_bytes(b"")


def _authorization_arguments(
    attestation_path: Path,
    context_path: Path,
    public_key_path: Path,
    *,
    sync_root: Path | None = None,
    now_ns: int = 2_000_000_000,
) -> list[str]:
    result = [
        "--attestation",
        str(attestation_path),
        "--expected-context",
        str(context_path),
        "--public-key",
        str(public_key_path),
        "--now-ns",
        str(now_ns),
    ]
    if sync_root is not None:
        result.extend(("--oracle-sync-dir", str(sync_root)))
    return result


def _write_authorization_inputs(
    root: Path,
    attestation: dict[str, Any],
    context: dict[str, Any],
    public_key: bytes,
) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    attestation_path = root / "attestation.json"
    context_path = root / "expected-context.json"
    public_key_path = root / "public-key.raw"
    attestation_path.write_text(json.dumps(attestation, sort_keys=True), encoding="utf-8")
    context_path.write_text(json.dumps(context, sort_keys=True), encoding="utf-8")
    public_key_path.write_bytes(public_key)
    return attestation_path, context_path, public_key_path


def _assert_applied_once(state_root: Path, winner_pid: int, loser_pid: int) -> None:
    _assert_single_apply_state(
        state_root,
        activation_id="task303-oracle-activation",
        winner_pid=winner_pid,
        loser_pid=loser_pid,
    )


def wait_for_concurrent_ready(
    ready_dir: Path,
    contenders: list[subprocess.Popen[str]],
    timeout: float = 20,
) -> list[dict[str, Any]]:
    """Wait for one validated-before-consume record from every live contender."""
    expected_pids = {process.pid for process in contenders}
    assert len(expected_pids) == len(contenders) == 2
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = sorted(ready_dir.glob("*.json")) if ready_dir.exists() else []
        if len(ready) == 2:
            rows = [json.loads(path.read_text(encoding="utf-8")) for path in ready]
            assert {row["pid"] for row in rows} == expected_pids
            return rows
        for contender in contenders:
            assert contender.poll() is None, "authorization contender exited before barrier"
        time.sleep(0.01)
    for contender in contenders:
        contender.kill()
    raise AssertionError("both authorization contenders did not reach the pre-consume barrier")


def exercise_public_activation_authorization(
    authorization_argv: list[str], tmp_path: Path
) -> dict[str, Any]:
    """Drive attacks through the installed boundary unit's exact public operation."""
    base, context = signed_scratch_attestation(tmp_path / "fixture")
    payload = canonical_attestation_payload(base)
    signature = bytes.fromhex(base["signature"])
    assert independent_ed25519_verify(
        RFC8032_VECTOR_2["public_key"],
        payload,
        signature,
        tmp_path / "independent-valid",
    )

    valid_root = tmp_path / "concurrent-replay"
    state_root = valid_root / "state"
    _write_authority_fixture(state_root, context["activation_id"])
    inputs = _write_authorization_inputs(
        valid_root / "input", base, context, RFC8032_VECTOR_2["public_key"]
    )
    sync_root = valid_root / "sync"
    command = _retarget_activation_command(
        authorization_argv, state_root, context["activation_id"]
    )
    arguments = _authorization_arguments(*inputs, sync_root=sync_root)
    before = snapshot_authority_state(state_root)
    contenders = [
        _manager_process(command, arguments) for _ in range(2)
    ]
    ready_rows = wait_for_concurrent_ready(sync_root / "ready", contenders)
    assert all(
        row["operation"] == PUBLIC_AUTHORIZATION_COMMAND
        and row["phase"] == "validated_before_consume"
        for row in ready_rows
    )
    assert snapshot_authority_state(state_root) == before
    (sync_root / "release").write_text("release\n", encoding="utf-8")
    completed = [_json_stdout(process) for process in contenders]
    assert sorted(code for code, _ in completed) == [0, 73]
    results = [result for _, result in completed]
    assert sorted(result["reason"] for result in results) == ["authorized", "replay"]
    assert all(result["operation"] == PUBLIC_AUTHORIZATION_COMMAND for result in results)
    winner = next(result for result in results if result["authorized"] is True)
    loser = next(result for result in results if result["authorized"] is False)
    assert winner["apply_count"] == 1 and loser["apply_count"] == 0
    assert winner["pid"] in {process.pid for process in contenders}
    assert loser["pid"] in {process.pid for process in contenders}
    _assert_applied_once(state_root, winner["pid"], loser["pid"])
    receipts = list((state_root / "attestation-state/consumed").glob("*.json"))
    assert len(receipts) == 1
    assert receipts[0].name == f"{base['run_nonce']}.json"
    assert json.loads(receipts[0].read_text(encoding="utf-8")) == {
        "activation_id": context["activation_id"],
        "run_nonce": base["run_nonce"],
        "attestation_sha256": hashlib.sha256(inputs[0].read_bytes()).hexdigest(),
        "actor_pid": winner["pid"],
        "consumption_count": 1,
    }

    replay_before = snapshot_authority_state(state_root)
    replay = _manager_process(
        _retarget_activation_command(
            authorization_argv, state_root, context["activation_id"]
        ),
        _authorization_arguments(*inputs),
    )
    replay_code, replay_result = _json_stdout(replay)
    assert replay_code == 73
    assert replay_result["authorized"] is False
    assert replay_result["reason"] == "replay"
    assert replay_result["apply_count"] == 0
    replay_after = snapshot_authority_state(state_root)
    assert replay_after == replay_before, (
        "replay changed real selector/admission/process/ledger state"
    )

    garbage = copy.deepcopy(base)
    garbage["signature"] = "0" * 128
    bit_flip = copy.deepcopy(base)
    changed_signature = bytearray(signature)
    changed_signature[0] ^= 1
    bit_flip["signature"] = bytes(changed_signature).hex()
    wrong_context = copy.deepcopy(context)
    wrong_context["activation_id"] = "task303-wrong-activation"
    cross_host = copy.deepcopy(context)
    cross_host["boot_id"] = "00000000-0000-0000-0000-000000000000"
    cross_host["host_id_sha256"] = "0" * 64
    cross_pid = copy.deepcopy(context)
    cross_pid["target_pid"] += 1
    cross_pid["target_starttime"] += 1
    runtime_drift = copy.deepcopy(context)
    runtime_drift["runtime"]["inode"] += 1
    runtime_drift["runtime"]["sha256"] = "0" * 64
    invalid_arms = {
        "shape_valid_garbage": (
            garbage,
            context,
            RFC8032_VECTOR_2["public_key"],
            2_000_000_000,
            "signature_invalid",
        ),
        "signature_bit_flip": (
            bit_flip,
            context,
            RFC8032_VECTOR_2["public_key"],
            2_000_000_000,
            "signature_invalid",
        ),
        "wrong_public_key": (
            base,
            context,
            RFC8032_WRONG_PUBLIC_KEY,
            2_000_000_000,
            "signature_invalid",
        ),
        "wrong_activation_context": (
            base,
            wrong_context,
            RFC8032_VECTOR_2["public_key"],
            2_000_000_000,
            "context_mismatch",
        ),
        "cross_host": (
            base,
            cross_host,
            RFC8032_VECTOR_2["public_key"],
            2_000_000_000,
            "context_mismatch",
        ),
        "cross_pid": (
            base,
            cross_pid,
            RFC8032_VECTOR_2["public_key"],
            2_000_000_000,
            "context_mismatch",
        ),
        "runtime_drift": (
            base,
            runtime_drift,
            RFC8032_VECTOR_2["public_key"],
            2_000_000_000,
            "context_mismatch",
        ),
        "stale": (
            base,
            context,
            RFC8032_VECTOR_2["public_key"],
            base["expires_at_ns"] + 1,
            "expired",
        ),
    }
    for name, (record, expected, public_key, now_ns, reason) in invalid_arms.items():
        root = tmp_path / name
        state = root / "state"
        _write_authority_fixture(state, context["activation_id"])
        paths = _write_authorization_inputs(root / "input", record, expected, public_key)
        state_before = snapshot_authority_state(state)
        process = _manager_process(
            _retarget_activation_command(
                authorization_argv, state, context["activation_id"]
            ),
            _authorization_arguments(*paths, now_ns=now_ns),
        )
        code, result = _json_stdout(process)
        assert code != 0, name
        assert result["operation"] == PUBLIC_AUTHORIZATION_COMMAND, name
        assert result["authorized"] is False, name
        assert result["reason"] == reason, name
        assert result["apply_count"] == 0, name
        assert snapshot_authority_state(state) == state_before, (
            f"invalid attestation changed real selector/admission/process/ledger state: {name}"
        )

    return {
        "known_vector": "RFC8032-test-vector-2",
        "invalid_arms": sorted(invalid_arms),
        "concurrent_results": sorted(result["reason"] for result in results),
        "apply_count": 1,
        "receipt_count": len(receipts),
        "replay_state_unchanged": replay_after == replay_before,
    }


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def assert_root_regular(path: Path, *, private: bool = False) -> os.stat_result:
    """Reject symlinks and every root-owned path component writable by another UID."""
    assert path.is_absolute(), path
    assert path.exists(), f"missing trusted file: {path}"
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        current_stat = current.lstat()
        assert not stat.S_ISLNK(current_stat.st_mode), f"symlink in trusted path: {current}"
        if current == path:
            assert stat.S_ISREG(current_stat.st_mode), f"not a regular file: {current}"
        assert current_stat.st_uid == 0, f"non-root owner in trusted path: {current}"
        assert current_stat.st_mode & 0o022 == 0, f"writable trusted path: {current}"
    result = path.lstat()
    if private:
        assert result.st_mode & 0o077 == 0, f"private file is group/world accessible: {path}"
    return result


def assert_root_directory(path: Path, *, private: bool = False) -> os.stat_result:
    assert path.is_absolute(), path
    assert path.is_dir(), f"missing trusted directory: {path}"
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        current_stat = current.lstat()
        assert not stat.S_ISLNK(current_stat.st_mode), f"symlink in trusted path: {current}"
        assert current_stat.st_uid == 0, f"non-root owner in trusted path: {current}"
        assert current_stat.st_mode & 0o022 == 0, f"writable trusted path: {current}"
    result = path.lstat()
    assert stat.S_ISDIR(result.st_mode), path
    if private:
        assert result.st_mode & 0o077 == 0, f"private directory is accessible: {path}"
    return result


def sha256_root_tree(path: Path) -> str:
    """Hash a symlink-free, root-owned, non-writable directory tree deterministically."""
    assert_root_directory(path)
    digest = hashlib.sha256()
    entries = sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix())
    assert entries, f"trusted tree is empty: {path}"
    for entry in entries:
        entry_stat = entry.lstat()
        assert not stat.S_ISLNK(entry_stat.st_mode), f"symlink in trusted tree: {entry}"
        assert entry_stat.st_uid == 0, f"non-root owner in trusted tree: {entry}"
        assert entry_stat.st_mode & 0o022 == 0, f"writable trusted tree: {entry}"
        relative = entry.relative_to(path).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if stat.S_ISREG(entry_stat.st_mode):
            digest.update(b"F")
            digest.update(bytes.fromhex(sha256_path(entry)))
        elif stat.S_ISDIR(entry_stat.st_mode):
            digest.update(b"D")
        else:
            raise AssertionError(f"special file in trusted tree: {entry}")
    return digest.hexdigest()


def load_control_selection() -> tuple[dict[str, Any], str]:
    assert_root_regular(CONTROL_SELECTION, private=True)
    selection_bytes = CONTROL_SELECTION.read_bytes()
    selection = json.loads(selection_bytes)
    assert selection["schema"] == "orchestra.runtime-control-plane.v1"
    source_commit = selection["source_commit"]
    assert _COMMIT_RE.fullmatch(source_commit)
    assert _HEX64_RE.fullmatch(selection["package_sha256"])
    release_dir = Path(selection["release_dir"])
    assert release_dir == Path(
        f"/usr/libexec/orchestra-runtime/control-planes/{source_commit}"
    )
    assert_root_directory(release_dir)
    assert selection["independent_package_verification"] == "passed"
    assert selection["package_copy_source_executed"] is False
    return selection, hashlib.sha256(selection_bytes).hexdigest()


def trusted_artifact(role: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    selection, _ = load_control_selection()
    entry = selection["artifacts"][role]
    path = Path(entry["path"])
    release_dir = Path(selection["release_dir"])
    assert _under(path, release_dir), (role, path)
    assert entry["source_commit"] == selection["source_commit"]
    observed = assert_root_regular(path, private=True)
    assert stat.S_IMODE(observed.st_mode) == 0o500, (
        f"root authority artifact is not root-only mode 0500: {role} {path}"
    )
    assert entry["sha256"] == sha256_path(path)
    return path, entry, selection


def trusted_service_source(relative: str) -> Path:
    selection, _ = load_control_selection()
    source = selection["application_source"]
    root = Path(source["path"])
    assert source["source_commit"] == selection["source_commit"]
    assert source["tree_sha256"] == sha256_root_tree(root)
    path = root / relative
    assert _under(path, root)
    assert_root_regular(path)
    return path


def _proc_starttime(pid: int) -> int:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    # comm may contain spaces and parentheses; field 3 begins after the final ') '.
    fields_from_state = raw[raw.rfind(")") + 2 :].split()
    return int(fields_from_state[19])


def runtime_fingerprint(pid: int) -> dict[str, Any]:
    exe = Path(f"/proc/{pid}/exe")
    target = os.readlink(exe)
    opened_stat = exe.stat()
    return {
        "path": target,
        "device": opened_stat.st_dev,
        "inode": opened_stat.st_ino,
        "size": opened_stat.st_size,
        "sha256": sha256_path(exe),
    }


def current_live_binding(attestation: dict[str, Any]) -> dict[str, Any]:
    pid = attestation["target_pid"]
    assert isinstance(pid, int) and pid > 1
    return {
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "host_id_sha256": hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest(),
        "target_pid": pid,
        "target_starttime": _proc_starttime(pid),
        "runtime": runtime_fingerprint(pid),
    }


def assert_bound_consumed_attestation(
    release: str,
    producer_role: str,
    evidence: Path,
    scratch_state: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate real evidence independently, then attack the installed field validator."""
    attestation_path = ATTESTATION_ROOT / f"release-{release.lower()}.json"
    assert_root_regular(attestation_path, private=True)
    assert_root_directory(ATTESTATION_ROOT, private=True)
    assert_root_regular(ATTESTATION_PRIVATE_KEY, private=True)
    assert_root_regular(ATTESTATION_PUBLIC_KEY)
    assert_root_directory(ATTESTATION_STATE, private=True)

    attestation_bytes = attestation_path.read_bytes()
    attestation = json.loads(attestation_bytes)
    assert attestation["schema"] == "orchestra.task303.attestation.v2"
    assert attestation["release"] == release
    assert attestation["executor_uid"] == 0
    assert _HEX64_RE.fullmatch(attestation["run_nonce"])
    assert _HEX128_RE.fullmatch(attestation["signature"])
    assert attestation["signature_algorithm"] == "ed25519"
    assert attestation["public_key_sha256"] == sha256_path(ATTESTATION_PUBLIC_KEY)
    public_key = ATTESTATION_PUBLIC_KEY.read_bytes()
    assert len(public_key) == 32, "attestation public key must be raw Ed25519 bytes"
    assert independent_ed25519_verify(
        public_key,
        canonical_attestation_payload(attestation),
        bytes.fromhex(attestation["signature"]),
        scratch_state / "evidence-signature-verification",
    ), "attestation Ed25519 signature failed independent verification"

    activation_id = attestation["activation_id"]
    request_path = ACTIVATION_ROOT / activation_id / "request.json"
    assert_root_regular(request_path, private=True)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["activation_id"] == activation_id
    assert request["run_nonce"] == attestation["run_nonce"]
    assert request["release"] == release
    assert request["state"] == "consumed"

    live = current_live_binding(attestation)
    assert attestation["boot_id"] == live["boot_id"]
    assert attestation["host_id_sha256"] == live["host_id_sha256"]
    assert attestation["target_pid"] == live["target_pid"]
    assert attestation["target_starttime"] == live["target_starttime"]
    assert attestation["runtime"] == live["runtime"]

    issued = attestation["issued_at_ns"]
    finished = attestation["finished_at_ns"]
    consumed = attestation["consumed_at_ns"]
    expires = attestation["expires_at_ns"]
    assert 0 < issued <= finished <= consumed <= expires
    assert expires - issued <= MAX_ATTESTATION_LIFETIME_NS

    _, control_digest = load_control_selection()
    assert attestation["control_selection_sha256"] == control_digest
    wrapper, wrapper_entry, _ = trusted_artifact("boundary_attestor")
    producer, producer_entry, _ = trusted_artifact(producer_role)
    assert attestation["wrapper"] == {
        "path": str(wrapper),
        "sha256": wrapper_entry["sha256"],
    }
    assert attestation["producer"] == {
        "path": str(producer),
        "sha256": producer_entry["sha256"],
    }

    result_path = Path(attestation["result_path"])
    assert _under(result_path, ATTESTATION_STATE / "results")
    assert_root_regular(result_path, private=True)
    assert attestation["result_sha256"] == sha256_path(result_path)
    assert attestation["result_sha256"] == sha256_path(evidence)
    assert attestation["producer_command"] == [
        str(producer),
        "--production-shaped",
        "--activation-id",
        activation_id,
        "--run-nonce",
        attestation["run_nonce"],
        "--output",
        str(result_path),
    ]

    receipt_path = ATTESTATION_STATE / "consumed" / f"{attestation['run_nonce']}.json"
    assert_root_regular(receipt_path, private=True)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt == {
        "activation_id": activation_id,
        "attestation_sha256": hashlib.sha256(attestation_bytes).hexdigest(),
        "boot_id": live["boot_id"],
        "host_id_sha256": live["host_id_sha256"],
        "target_pid": live["target_pid"],
        "target_starttime": live["target_starttime"],
        "consumed_at_ns": consumed,
        "consumption_count": 1,
    }

    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["activation_id"] == activation_id
    assert report["run_nonce"] == attestation["run_nonce"]
    return attestation, report
