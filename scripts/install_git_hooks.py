#!/usr/bin/env python3
"""Install Orchestra's shared publication gate locally or across registered projects.

Run from the canonical Orchestra checkout with --registered after merging. No network,
service restart, remote changes, or silent replacement of foreign hooks.
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "orchestra-secret-gate"
HOOKS = ("pre-commit", "commit-msg", "pre-push")
ROOT = Path(__file__).resolve().parents[1]


class HookInstallError(RuntimeError):
    pass


def _git_path(repo: Path, *args: str) -> Path:
    done = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", *args],
                          capture_output=True, text=True)
    if done.returncode:
        raise HookInstallError(f"not an accessible git repository: {repo}")
    return Path(done.stdout.strip())


def _hooks_dir_git_actually_uses(repo: Path | None = None) -> Path:
    return _git_path(repo or Path.cwd(), "--git-path", "hooks")


def hook_python(orchestra_root: Path) -> Path:
    """Use Orchestra's venv or system Python, never the caller/project's venv."""
    python = orchestra_root / ".venv" / "bin" / "python"
    if python.is_file() and os.access(python, os.X_OK):
        return python
    # PATH and sys.executable may belong to a foreign project's activated venv.
    system_python = shutil.which("python3", path=os.defpath)
    if not system_python:
        raise HookInstallError("Orchestra venv and system python3 are unavailable")
    return Path(system_python).resolve()


def hook_text(name: str, orchestra_root: Path) -> str:
    root = orchestra_root.resolve()
    scanner = root / "scripts" / "secret_scan.py"
    python = hook_python(root)
    flags = {"pre-commit": "--staged", "pre-push": "--pre-push",
             "commit-msg": '--commit-msg "$1"'}
    return (
        f"#!/bin/sh\n# {MARKER} (V-1047)\nset -e\n"
        f"scan={shlex.quote(str(scanner))}\n"
        'if [ ! -f "$scan" ]; then\n'
        '  echo "secret-gate: нет $scan (главный чекаут на ветке без гейта)." >&2\n'
        "  exit 1\nfi\n"
        f'exec {shlex.quote(str(python))} "$scan" {flags[name]}\n'
    )


def install_hooks(repo: str | Path, orchestra_root: str | Path = ROOT) -> list[Path]:
    """Idempotent install/update; preflight all hook names before changing this repo.

    Linked worktrees share common hooks. Refuse core.hooksPath redirects rather than
    accidentally modifying a global directory shared with unrelated repositories.
    """
    repo, root = Path(repo).resolve(), Path(orchestra_root).resolve()
    if not (root / "scripts" / "secret_scan.py").is_file():
        raise HookInstallError("canonical Orchestra secret scanner is missing")
    common = _git_path(repo, "--git-common-dir")
    destination = common / "hooks"
    if _hooks_dir_git_actually_uses(repo).resolve() != destination.resolve():
        raise HookInstallError(f"refusing core.hooksPath redirect for {repo}; configure common hooks first")
    for name in HOOKS:
        path = destination / name
        if path.is_symlink() or (path.exists() and
                                (not path.is_file() or MARKER not in path.read_text(errors="replace"))):
            raise HookInstallError(f"foreign hook preserved: {path}; chain it explicitly before retrying")
    destination.mkdir(parents=True, exist_ok=True)
    installed = []
    for name in HOOKS:
        path = destination / name
        text = hook_text(name, root)
        if not path.exists() or path.read_text() != text:
            # Replace atomically: an interrupted installer leaves the previous gate usable.
            with tempfile.NamedTemporaryFile(mode="w", dir=destination, delete=False) as output:
                temporary = Path(output.name)
                try:
                    output.write(text)
                    output.flush()
                    os.fchmod(output.fileno(), 0o755)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        elif path.stat().st_mode & 0o777 != 0o755:
            path.chmod(0o755)
        installed.append(path)
    return installed


def registered_scopes(orchestra_root: Path, catalog: Path | None = None) -> list[Path]:
    import yaml

    source = catalog or orchestra_root / ".orchestra" / "projects.yaml"
    data = yaml.safe_load(source.read_text())
    if not isinstance(data, dict) or data.get("version") != 1:
        raise HookInstallError("project catalog must be a version: 1 mapping")
    scopes = data.get("include_scopes", [])
    if not isinstance(scopes, list) or any(not isinstance(p, str) or not Path(p).is_absolute()
                                           for p in scopes):
        raise HookInstallError("include_scopes must be a list of absolute project paths")
    return list(dict.fromkeys([orchestra_root.resolve(), *(Path(p).resolve() for p in scopes)]))


def install_registered_hooks(orchestra_root: str | Path = ROOT, catalog: Path | None = None) -> list[Path]:
    root = Path(orchestra_root).resolve()
    installed, failures = [], []
    for repo in registered_scopes(root, catalog):
        try:
            installed.extend(install_hooks(repo, root))
        except (HookInstallError, OSError) as error:
            # Keep installing the remaining registered repositories, but never report
            # success while one of them remains uncovered.
            failures.append(f"{repo}: {error}")
    if failures:
        raise HookInstallError("gate installation refused for: " + ", ".join(failures)
                               + "; foreign hooks/core.hooksPath must be resolved explicitly")
    return installed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registered", action="store_true", help="Orchestra + catalog include_scopes")
    parser.add_argument("--catalog", type=Path, help="explicit catalog path for --registered")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        installed = (install_registered_hooks(ROOT, args.catalog) if args.registered
                     else install_hooks(args.repo, ROOT))
        for path in installed:
            print(f"installed {path}")
        return 0
    except (HookInstallError, OSError, ValueError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
