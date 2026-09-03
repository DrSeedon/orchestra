"""RED acceptance for the user-approved incident-scoped #303 replacement.

This intentionally does not assert UID or credential isolation.  It protects the
specific service-runtime replacement mechanism from incident #302.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
ACTIVATION_KEYS = {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}


def _unit_value(source: str, key: str) -> list[str]:
    return [
        line.split("=", 1)[1].strip()
        for line in source.splitlines()
        if line.strip().startswith(f"{key}=")
    ]


def _load_runtime_env():
    path = ROOT / "app/runtime_env.py"
    spec = importlib.util.spec_from_file_location("task303_incident_runtime_env", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = {
        "build_project_env",
        "sanitize_project_mcp_servers",
        "guard_uv_invocation",
        "project_cli_path",
    }
    missing = sorted(name for name in required if not hasattr(module, name))
    assert not missing, f"#303 incident boundary missing runtime helpers: {missing}"
    return module


def _function_calls(relative: str, function_name: str) -> set[str]:
    source = (ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        (
            item
            for item in ast.walk(tree)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == function_name
        ),
        None,
    )
    assert node is not None, f"#303 seam moved or disappeared: {relative}:{function_name}"
    calls = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            calls.add(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            calls.add(item.func.attr)
    return calls


def test_incident_service_and_mcp_do_not_depend_on_repo_venv():
    runtime_pattern = re.compile(
        r"^/opt/orchestra/runtimes/(?!current(?:/|$))[^/]+/bin/python "
        r"-m uvicorn app\.main:app(?:\s|$)"
    )
    for relative in ("deploy/orchestra.service", "deploy/orchestra.service.template"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        starts = _unit_value(source, "ExecStart")
        assert len(starts) == 1 and runtime_pattern.match(starts[0]), (
            f"#303 incident boundary missing: {relative} must start uvicorn with a "
            "direct, concrete versioned /opt runtime Python"
        )
        assert not _unit_value(source, "ExecStartPre"), (
            f"#303 incident boundary missing: {relative} must not synchronize at service start"
        )
        unset = " ".join(_unit_value(source, "UnsetEnvironment")).split()
        assert ACTIVATION_KEYS.issubset(unset), (
            f"#303 incident boundary missing: {relative} does not unset both activation keys"
        )
        assert ".venv" not in source and "uv run" not in source

    runtime_source = (ROOT / "app/runtime_env.py").read_text(encoding="utf-8")
    assert "MCP_STDIO_CMD = [sys.executable, _MCP_SCRIPT]" in runtime_source
    assert "/home/kesha/orchestra/.venv" not in runtime_source


def test_incident_project_env_and_uv_guard_are_fail_loud(tmp_path):
    runtime_env = _load_runtime_env()
    worktree = tmp_path / "agent-worktree"
    outside = tmp_path / "service-repo"
    guard_dir = tmp_path / "root-owned-project-bin"
    worktree.mkdir()
    outside.mkdir()
    guard_dir.mkdir()
    (worktree / "escape").symlink_to(outside, target_is_directory=True)

    source = {
        "PATH": "/home/kesha/orchestra/.venv/bin:/usr/bin:/bin",
        "HOME": "/home/kesha",
        "VIRTUAL_ENV": "/home/kesha/orchestra/.venv",
        "UV_PROJECT_ENVIRONMENT": "/home/kesha/orchestra/.venv",
    }
    clean = runtime_env.build_project_env(
        source,
        worktree=worktree,
        guard_dir=guard_dir,
    )
    assert ACTIVATION_KEYS.isdisjoint(clean)
    assert Path(clean["ORCHESTRA_PROJECT_WORKTREE"]) == worktree.resolve()
    assert clean["PATH"].split(":", 1)[0] == str(guard_dir.resolve())

    servers = runtime_env.sanitize_project_mcp_servers({
        "project": {
            "command": "tool",
            "env": {
                "KEEP": "yes",
                "VIRTUAL_ENV": "/service/.venv",
                "UV_PROJECT_ENVIRONMENT": "/service/.venv",
            },
        }
    })
    assert servers["project"]["env"] == {"KEEP": "yes"}

    allowed = (
        ("uv run --frozen", {}),
        ("UV_PROJECT_ENVIRONMENT=.venv uv run --frozen", {}),
        ("uv --project . run --frozen", {}),
        ("uv --directory . run --frozen", {}),
        ("uv venv .venv", {}),
    )
    for command, environ in allowed:
        runtime_env.guard_uv_invocation(
            command,
            environ=environ,
            worktree=worktree,
        )

    denied = (
        ("uv run --frozen", {"UV_PROJECT_ENVIRONMENT": str(outside / ".venv")}),
        ("uv run --active", {"VIRTUAL_ENV": str(outside / ".venv")}),
        (f"UV_PROJECT_ENVIRONMENT={outside / '.venv'} uv run --frozen", {}),
        (f"uv --project {outside} run --frozen", {}),
        (f"uv --directory {outside} run --frozen", {}),
        (f"uv venv {outside / '.venv'}", {}),
        ("uv venv escape/.venv", {}),
    )
    for command, environ in denied:
        with pytest.raises(RuntimeError, match="uv target outside canonical worktree"):
            runtime_env.guard_uv_invocation(
                command,
                environ=environ,
                worktree=worktree,
            )

    assert runtime_env.project_cli_path("claude", guard_dir=guard_dir) == str(
        guard_dir.resolve() / "claude"
    )

    launcher = ROOT / "scripts/orchestra-project-launch.py"
    assert launcher.is_file() and os.access(launcher, os.X_OK), (
        "#303 incident boundary missing: executable project launcher is absent"
    )
    fake_uv = tmp_path / "real-uv"
    marker = tmp_path / "real-uv-ran"
    fake_uv.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        f"open({str(marker)!r}, 'w').write('ran')\n"
        "print(json.dumps({k: os.environ.get(k) for k in "
        "('VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT')}))\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    wrapped_uv = guard_dir / "uv"
    wrapped_uv.symlink_to(launcher)
    base_env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "ORCHESTRA_REAL_UV": str(fake_uv),
        "ORCHESTRA_PROJECT_WORKTREE": str(worktree),
    }

    denied_env = {**base_env, "UV_PROJECT_ENVIRONMENT": str(outside / ".venv")}
    denied_run = subprocess.run(
        [str(wrapped_uv), "run", "--frozen"],
        cwd=worktree,
        env=denied_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert denied_run.returncode != 0
    assert "uv target outside canonical worktree" in denied_run.stderr
    assert not marker.exists(), "guard executed real uv after denying its target"

    allowed_env = {
        **base_env,
        "VIRTUAL_ENV": str(worktree / ".venv"),
        "UV_PROJECT_ENVIRONMENT": str(worktree / ".venv"),
    }
    allowed_run = subprocess.run(
        [str(wrapped_uv), "run", "--frozen"],
        cwd=worktree,
        env=allowed_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert allowed_run.returncode == 0, allowed_run.stderr
    assert json.loads(allowed_run.stdout) == {
        "VIRTUAL_ENV": None,
        "UV_PROJECT_ENVIRONMENT": None,
    }


def test_incident_every_project_execution_seam_uses_the_boundary():
    expected = {
        ("app/runtime_registry.py", "build_backend"): {"sanitize_project_mcp_servers"},
        ("app/backend_codex.py", "_build_env"): {"build_project_env"},
        ("app/backend_grok.py", "_build_env"): {"build_project_env"},
        ("app/backend_opencode.py", "_build_daemon_env"): {"build_project_env"},
        ("app/backend_claude.py", "_make_client"): {
            "build_project_env",
            "project_cli_path",
        },
        ("app/bg_jobs.py", "_spawn_bg_process"): {
            "build_project_env",
            "guard_uv_invocation",
        },
        ("app/acceptance.py", "run_command"): {
            "build_project_env",
            "guard_uv_invocation",
        },
        ("app/merge_test_gate.py", "run_pytest"): {
            "build_project_env",
            "guard_uv_invocation",
        },
        ("app/routes/bg.py", "bg_job_create"): {"canonical_project_worktree"},
    }
    missing = {}
    for seam, required in expected.items():
        absent = sorted(required - _function_calls(*seam))
        if absent:
            missing[f"{seam[0]}:{seam[1]}"] = absent
    assert not missing, f"#303 project-execution seams bypass the boundary: {missing}"

    mcp_source = (ROOT / "app/mcp_stdio.py").read_text(encoding="utf-8")
    assert '"created_by_session_id": SESSION_ID' in mcp_source, (
        "#303 background commands are not bound to their creator's canonical worktree"
    )
