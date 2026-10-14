"""Run tests with repo-local options; nested foreign worktrees must not inherit Orchestra's xdist flags."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def _git_common_dir(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def main() -> int:
    cwd = Path.cwd().resolve()
    orchestra_common = _git_common_dir(ROOT)
    current_common = _git_common_dir(cwd)
    orchestra_project = bool(orchestra_common and current_common == orchestra_common)
    command = [sys.executable, "-m", "pytest"]
    project_root = ROOT if orchestra_project else _project_root(cwd)
    config = _project_config(project_root)
    with tempfile.TemporaryDirectory(prefix="orchestra-test-runner-") as temporary:
        if config is None:
            config = Path(temporary) / "pytest.ini"
            config.write_text("[pytest]\n", encoding="utf-8")
        command += ["--rootdir", str(project_root), "-c", str(config)]
        if orchestra_project:
            command += ["-m", "not live_probe", "-n", "2", "--dist=loadscope", "tests/"]
            cwd = ROOT
        else:
            command += ["."]
        return subprocess.run(command, cwd=cwd, check=False).returncode


def _project_root(path: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=path,
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return path
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else path


def _project_config(project_root: Path) -> Path | None:
    return next((
        project_root / name
        for name in ("pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
        if (project_root / name).is_file()
    ), None)


if __name__ == "__main__":
    raise SystemExit(main())
