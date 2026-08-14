"""#206: --check краснеет на расхождении манифеста с файлами, зеленеет на согласованном."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_pipeline_manifest.py"
_SPEC = importlib.util.spec_from_file_location("check_pipeline_manifest", _SCRIPT)
check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)

DEFAULT = check.DEFAULT_MANIFEST


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_check_passes_on_current_default():
    errors = check.disagreements(DEFAULT)
    assert errors == []
    roles = yaml.safe_load(DEFAULT.read_text())["roles"]
    assert len(roles) >= 5
    proc = _run("--check")
    assert proc.returncode == 0, proc.stderr
    assert "OK:" in proc.stdout


def test_check_fails_when_manifest_names_missing_module(tmp_path):
    data = yaml.safe_load(DEFAULT.read_text())
    data["roles"]["worker"]["modules"] = list(data["roles"]["worker"]["modules"]) + [
        "this-module-does-not-exist-xyz",
    ]
    planted = tmp_path / "pipeline.yaml"
    planted.write_text(yaml.safe_dump(data, allow_unicode=True))
    (tmp_path / "prompts" / "roles").mkdir(parents=True)
    (tmp_path / "prompts" / "modules").mkdir(parents=True)
    for role in data["roles"]:
        (tmp_path / "prompts" / "roles" / f"{role}.md").write_text("x")
    for spec in data["roles"].values():
        for mod in spec.get("modules") or []:
            path = tmp_path / "prompts" / "modules" / f"{mod}.md"
            if mod != "this-module-does-not-exist-xyz":
                path.write_text("x")

    errors = check.disagreements(planted)
    assert any("this-module-does-not-exist-xyz" in e for e in errors), errors
    proc = _run("--check", "--manifest", str(planted))
    assert proc.returncode == 1
    assert "this-module-does-not-exist-xyz" in proc.stderr


def test_check_fails_when_role_file_missing(tmp_path):
    planted = tmp_path / "pipeline.yaml"
    planted.write_text("roles:\n  ghost-role:\n    modules: []\n")
    (tmp_path / "prompts" / "roles").mkdir(parents=True)
    errors = check.disagreements(planted)
    assert any("ghost-role" in e for e in errors), errors
    proc = _run("--check", "--manifest", str(planted))
    assert proc.returncode == 1
    assert "ghost-role" in proc.stderr


def test_check_fails_on_empty_roles(tmp_path):
    planted = tmp_path / "pipeline.yaml"
    planted.write_text("name: empty\nroles: {}\n")
    errors = check.disagreements(planted)
    assert errors, "empty roles must not look like agreement"
    proc = _run("--check", "--manifest", str(planted))
    assert proc.returncode == 1


def test_check_fails_when_prompt_quotes_manifest_model_id(tmp_path):
    """#209: копия id в прозе — тот же класс, что протухшая скобка (xhigh)."""
    data = yaml.safe_load(DEFAULT.read_text())
    planted = tmp_path / "pipeline.yaml"
    planted.write_text(yaml.safe_dump(data, allow_unicode=True))
    (tmp_path / "prompts" / "roles").mkdir(parents=True)
    (tmp_path / "prompts" / "modules").mkdir(parents=True)
    for role, spec in data["roles"].items():
        (tmp_path / "prompts" / "roles" / f"{role}.md").write_text("role body\n")
        for mod in spec.get("modules") or []:
            (tmp_path / "prompts" / "modules" / f"{mod}.md").write_text("module body\n")
    quoted = tmp_path / "prompts" / "modules" / "model-routing.md"
    quoted.write_text("Use `claude-opus-5[1m]` as the worker default.\n")

    errors = check.disagreements(planted)
    assert any("claude-opus-5[1m]" in e and "quotes manifest model" in e for e in errors), errors
    proc = _run("--check", "--manifest", str(planted))
    assert proc.returncode == 1
    assert "claude-opus-5[1m]" in proc.stderr
