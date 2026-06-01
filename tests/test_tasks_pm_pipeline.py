"""Тесты реального пайплайна tasks-pm.

Guard ниже скипает весь модуль, если файлы пайплайна недоступны (страховка).
"""
from __future__ import annotations

import pytest

from app.pipeline import (
    PIPELINES_DIR,
    build_system_prompt,
    load_pipeline,
    resolve_role,
    validate_spawn,
)

pytestmark = pytest.mark.skipif(
    not (PIPELINES_DIR / "tasks-pm" / "pipeline.yaml").is_file(),
    reason="пайплайн tasks-pm недоступен на диске",
)

_MARKER = "## Пайплайн — сквозные правила"  # характерная строка из prompts/_pipeline.md
_ROLES = {
    "base-orchestrator", "pm-glava", "pm-fichi", "analyst",
    "coder", "tester", "secretary", "worker",
}
_ORCHESTRATORS = {"base-orchestrator", "pm-glava", "pm-fichi", "analyst", "coder", "tester"}


def test_loads_and_has_eight_roles():
    cfg = load_pipeline("tasks-pm")
    assert set(cfg.roles) == _ROLES
    assert len(cfg.roles) == 8


def test_inheritance_model_skills_mcp():
    """secretary наследует model=opus из defaults (НЕ sonnet); skills/mcp == all у всех."""
    cfg = load_pipeline("tasks-pm")
    assert resolve_role(cfg, "secretary").model == "opus"
    for r in _ROLES:
        rr = resolve_role(cfg, r)
        assert rr.skills == "all", r
        assert rr.mcp_servers == "all", r


def test_base_branch_strategy():
    cfg = load_pipeline("tasks-pm")
    assert resolve_role(cfg, "base-orchestrator").base_branch_strategy == "main"
    assert resolve_role(cfg, "pm-glava").base_branch_strategy == "main"
    for r in ("analyst", "coder", "tester", "pm-fichi"):
        assert resolve_role(cfg, r).base_branch_strategy == "parent", r


def test_is_orchestrator():
    cfg = load_pipeline("tasks-pm")
    for r in _ORCHESTRATORS:
        assert resolve_role(cfg, r).is_orchestrator is True, r
    for r in ("secretary", "worker"):
        assert resolve_role(cfg, r).is_orchestrator is False, r


def test_validate_spawn_fail_closed():
    # pm-glava НЕ может спавнить analyst напрямую (только pm-fichi/secretary)
    with pytest.raises(ValueError):
        validate_spawn("tasks-pm", "pm-glava", "analyst")
    # разрешённые спавны не падают
    validate_spawn("tasks-pm", "pm-glava", "pm-fichi")
    validate_spawn("tasks-pm", "base-orchestrator", "pm-glava")


def test_build_system_prompt_layers():
    coder = build_system_prompt("tasks-pm", "coder")
    assert _MARKER in coder  # слой _pipeline.md (только для оркестраторов)
    base_first = (PIPELINES_DIR / "tasks-pm" / "prompts" / "base.md").read_text().splitlines()[0]
    coder_first = (PIPELINES_DIR / "tasks-pm" / "prompts" / "roles" / "coder.md").read_text().splitlines()[0]
    assert base_first.strip() and coder_first.strip()  # маркеры не пустые, иначе `in` бессмысленен
    assert base_first in coder
    assert coder_first in coder

    secretary = build_system_prompt("tasks-pm", "secretary")
    sec_first = (PIPELINES_DIR / "tasks-pm" / "prompts" / "roles" / "secretary.md").read_text().splitlines()[0]
    assert base_first in secretary
    assert sec_first in secretary
    assert _MARKER not in secretary  # воркер НЕ получает слой _pipeline.md


def test_docs_dir_shapes():
    cfg = load_pipeline("tasks-pm")
    fichi = resolve_role(cfg, "pm-fichi").docs_dir
    assert fichi.path == "{feature}/_pm"
    assert fichi.requires == "feature"
    glava = resolve_role(cfg, "pm-glava").docs_dir
    assert glava.path == "_sprint"
    assert glava.requires is None
