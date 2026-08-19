"""#206: --check краснеет на расхождении манифеста с файлами, зеленеет на согласованном."""
from __future__ import annotations

import importlib.util
import shutil
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


def _policy_copy(tmp_path: Path) -> Path:
    root = tmp_path / "default"
    shutil.copytree(DEFAULT.parent / "prompts", root / "prompts")
    shutil.copy2(DEFAULT, root / "pipeline.yaml")
    return root / "pipeline.yaml"


def _policy_errors(manifest: Path) -> list[str]:
    data = yaml.safe_load(manifest.read_text())
    return check._review_policy_errors(manifest.parent, data)


def test_review_policy_rejects_silent_worker_bypass(tmp_path):
    manifest = _policy_copy(tmp_path)
    worker = manifest.parent / "prompts" / "roles" / "worker.md"
    worker.write_text(
        worker.read_text().replace(check._REVIEW_POLICY_POINTER, "review when useful")
    )

    errors = _policy_errors(manifest)
    assert any("roles/worker.md" in error and "pointer" in error for error in errors), errors


def test_review_policy_rejects_self_downgrade_without_evidence(tmp_path):
    manifest = _policy_copy(tmp_path)
    owner = manifest.parent / "prompts" / "skills" / "codex-debate.md"
    owner.write_text(
        owner.read_text().replace(
            "The author never self-certifies risk or oracle strength",
            "The author chooses the risk and oracle strength",
        )
    )

    errors = _policy_errors(manifest)
    assert any("self-certifies" in error for error in errors), errors


def test_review_policy_rejects_author_controlled_high_risk_floor(tmp_path):
    manifest = _policy_copy(tmp_path)
    owner = manifest.parent / "prompts" / "skills" / "codex-debate.md"
    owner.write_text(
        owner.read_text().replace(
            "**High-risk is evidence-derived, not author-declared.**",
            "**High-risk is whatever the author declares.**",
        )
    )

    errors = _policy_errors(manifest)
    assert any("High-risk is evidence-derived" in error for error in errors), errors


def test_review_policy_rejects_stale_mandatory_sol_rule(tmp_path):
    manifest = _policy_copy(tmp_path)
    full_cycle = manifest.parent / "prompts" / "roles" / "full-cycle.md"
    full_cycle.write_text(
        full_cycle.read_text()
        + "\nCodex review MANDATORY for complex tasks regardless of the policy gate.\n"
    )

    errors = _policy_errors(manifest)
    assert any("stale review policy wording" in error for error in errors), errors


def test_review_policy_rejects_duplicate_owner_clause(tmp_path):
    manifest = _policy_copy(tmp_path)
    consumer = manifest.parent / "prompts" / "modules" / "orchestration.md"
    consumer.write_text(
        consumer.read_text() + "\n## Review decision gate — canonical policy\n"
    )

    errors = _policy_errors(manifest)
    assert any("duplicates canonical review policy" in error for error in errors), errors


def test_review_policy_rejects_dropping_the_optional_review_contract(tmp_path):
    """#349: якорь снятого правила заменён якорем нового — проверка осталась утверждающей."""
    manifest = _policy_copy(tmp_path)
    owner = manifest.parent / "prompts" / "skills" / "codex-debate.md"
    owner.write_text(
        owner.read_text().replace("Codex недоступен → ревью НЕ делается", "Ревью обязательно")
    )

    errors = _policy_errors(manifest)
    assert any("Codex недоступен" in error for error in errors), errors


def test_review_policy_rejects_returning_the_opus_substitute_route(tmp_path):
    """Маршрут «поднять Opus вместо Codex» не должен вернуться ни в один промпт (#346)."""
    manifest = _policy_copy(tmp_path)
    role = manifest.parent / "prompts" / "roles" / "full-cycle.md"
    role.write_text(role.read_text() + "\nCodex молчит → targeted Opus cross-family review.\n")

    errors = _policy_errors(manifest)
    assert any("stale review policy wording" in error for error in errors), errors


def test_example_block_may_show_numbers_but_must_name_their_source(tmp_path):
    """Содержимое примера не утверждение — но пример на выдуманных числах учит их выдумывать."""
    prompts = tmp_path / "prompts"
    (prompts / "roles").mkdir(parents=True)
    sourced = "Пример:\n\n```\n# Замер #345\nцена вызова: $0.135\n```\n"
    invented = "Пример:\n\n```\nцена вызова: $0.135\n```\n"

    (prompts / "roles" / "a.md").write_text(sourced, encoding="utf-8")
    assert check._prompt_metric_errors(prompts) == []

    (prompts / "roles" / "a.md").write_text(invented, encoding="utf-8")
    errors = check._prompt_metric_errors(prompts)
    assert any("without naming their source" in error for error in errors), errors


def test_unterminated_example_block_does_not_swallow_the_rest_of_the_file(tmp_path):
    """Открытый и незакрытый забор — самый дешёвый способ обойти проверку."""
    prompts = tmp_path / "prompts"
    (prompts / "roles").mkdir(parents=True)
    (prompts / "roles" / "a.md").write_text(
        "Пример:\n\n```\nцена вызова: $0.135\n", encoding="utf-8"
    )

    errors = check._prompt_metric_errors(prompts)
    assert any("without naming their source" in error for error in errors), errors


def test_placeholder_template_is_not_a_measured_claim(tmp_path):
    """Негативный контроль: шаблон с `100% coverage` — плейсхолдер, а не замер."""
    prompts = tmp_path / "prompts"
    (prompts / "modules").mkdir(parents=True)
    (prompts / "modules" / "a.md").write_text(
        "Шаблон:\n\n```\n- What does NOT matter: {e.g. enterprise patterns, 100% coverage}\n```\n",
        encoding="utf-8",
    )

    assert check._prompt_metric_errors(prompts) == []
