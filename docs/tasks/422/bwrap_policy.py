from __future__ import annotations

from pathlib import Path


POLICY_ID = "orchestra-422-bwrap-v1"
TOOL_ENV = {
    "HOME": "/workspace",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/opt/venv/bin:/usr/local/bin:/usr/bin:/bin",
    "PWD": "/workspace",
    "PYTHONPATH": "/workspace",
}
FORBIDDEN_TOOL_ENV = frozenset({
    "OPENROUTER_API_KEY",
    "OPENROUTER_KEY",
    "INTERNAL_TOKEN",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "https_proxy",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
})


def build_bwrap_argv(
    workspace: str | Path,
    venv: str | Path,
    command: list[str],
) -> list[str]:
    workspace = str(Path(workspace).resolve())
    venv = str(Path(venv).resolve())
    argv = [
        "bwrap",
        "--unshare-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/usr/local", "/usr/local",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
    ]
    if Path("/lib64").exists():
        argv += ["--ro-bind", "/lib64", "/lib64"]
    argv += [
        "--ro-bind", venv, "/opt/venv",
        "--bind", workspace, "/workspace",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]
    for key, value in sorted(TOOL_ENV.items()):
        argv += ["--setenv", key, value]
    argv += ["--chdir", "/workspace", "--", *command]
    return argv
