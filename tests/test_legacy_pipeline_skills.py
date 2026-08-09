"""#167 дефект 3: легаси-строка с pipeline='' оставляла оркестратора без скиллов.

Журнал 06.08 (14:57:25 и 14:58:59): «skill refresh failed: pipeline name is empty»
на каждом пробуждении. Корневой Orchestra-orchestrator — единственная ЖИВАЯ
сессия с пустым pipeline; на диске у него лежал 1 каталог скилла из 5 заявленных.

Причина — один pipeline читался ДВУМЯ способами внутри одной функции
_load_from_db: строка 1357 нормализовала '' → 'default' (и промпт был верный),
а конструктор AgentSession получал сырой db_row (''), и _refresh_skills падал.
"""

import subprocess

import pytest

from app.pipeline import DEFAULT_PIPELINE, get_role


def test_default_orchestrator_role_declares_skills():
    """Предпосылка: роли действительно есть что раздавать."""
    role = get_role(DEFAULT_PIPELINE, "orchestrator")

    assert role is not None
    assert role.skills, "у роли orchestrator нет скиллов — тест ниже потерял смысл"


def test_empty_pipeline_resolves_no_role():
    """Корень дефекта: пустое имя пайплайна роль не отдаёт."""
    with pytest.raises(FileNotFoundError, match="pipeline name is empty"):
        get_role("", "orchestrator")


@pytest.mark.asyncio
async def test_legacy_empty_pipeline_still_injects_role_skills(monkeypatch, tmp_path):
    """Сессия, загруженная из легаси-строки, обязана получить скиллы своей роли."""
    from app.session import AgentSession

    injected: list[list[str]] = []
    monkeypatch.setattr(
        "app.session.inject_skills_to_worktree",
        lambda skills, path, home: injected.append(list(skills)) or len(skills),
    )

    session = AgentSession.__new__(AgentSession)
    session.name = "Orchestra-orchestrator"
    session.backend_type = "claude"
    session.role = "orchestrator"
    session.worktree_path = ""          # оркестратор работает без worktree
    session.cwd = str(tmp_path)
    session.pipeline = DEFAULT_PIPELINE  # то, что кладёт исправленный _load_from_db

    await session._refresh_skills()

    role = get_role(DEFAULT_PIPELINE, "orchestrator")
    assert role is not None
    assert injected == [list(role.skills)]


@pytest.mark.asyncio
async def test_empty_pipeline_would_inject_nothing(monkeypatch, tmp_path):
    """Обратная сторона: пока в сессии лежало '', не инъектилось НИЧЕГО.

    Проверка, дающая одинаковый вывод при успехе и провале, — не проверка.
    """
    from app.session import AgentSession

    injected: list[list[str]] = []
    monkeypatch.setattr(
        "app.session.inject_skills_to_worktree",
        lambda skills, path, home: injected.append(list(skills)) or len(skills),
    )

    session = AgentSession.__new__(AgentSession)
    session.name = "Orchestra-orchestrator"
    session.backend_type = "claude"
    session.role = "orchestrator"
    session.worktree_path = ""
    session.cwd = str(tmp_path)
    session.pipeline = ""  # поведение ДО фикса

    await session._refresh_skills()  # проглатывает FileNotFoundError в warning

    assert injected == []


@pytest.mark.asyncio
async def test_tracked_codex_file_enables_visible_prompt_fallback(tmp_path):
    from app.session import AgentSession

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".codex").write_bytes(b"repo-owned\x00codex")
    subprocess.run(["git", "add", ".codex"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "tracked codex file"], cwd=repo, check=True)
    before = (repo / ".codex").read_bytes()
    logs = []
    session = AgentSession(
        id="codex-file", name="codex-file", scope=str(repo), cwd=str(repo),
        model="gpt-5.6-sol", system_prompt="BASE", backend_type="codex",
        worktree_path=str(repo), pipeline="default", role="full-cycle",
    )
    session._log = lambda kind, content, **_kwargs: logs.append((kind, content))

    await session._refresh_skills()
    await session._refresh_skills()

    assert session._codex_skill_index_fallback is True
    fallback_logs = [
        content for _, content in logs if ".codex" in content and "fallback" in content
    ]
    assert len(fallback_logs) == 1
    backend = session._make_backend()
    assert backend.system_prompt.count("## Available skills (progressive loading)") == 1
    assert backend.system_prompt.count("- `codex-debate`") == 1
    assert len(backend.system_prompt) < 16_100
    assert (repo / ".codex").read_bytes() == before
    status = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True,
    ).stdout
    assert status == ""


@pytest.mark.asyncio
async def test_oversized_agents_warning_and_instruction_are_once_per_backend_prompt(
    tmp_path, monkeypatch,
):
    from app.session import AgentSession

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("first\nsecond is omitted\n", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        "project_doc_max_bytes = 6\n", encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    logs = []
    session = AgentSession(
        id="oversized-doc", name="oversized-doc", scope=str(repo), cwd=str(repo),
        model="gpt-5.6-sol", system_prompt="BASE", backend_type="codex",
        worktree_path=str(repo), pipeline="default", role="worker",
    )
    session._log = lambda kind, content, **_kwargs: logs.append((kind, content))

    await session._refresh_codex_project_doc()
    first = session._make_backend().system_prompt
    await session._refresh_codex_project_doc()
    second = session._make_backend().system_prompt

    assert first.count("[Orchestra project-doc warning:") == 1
    assert second.count("[Orchestra project-doc warning:") == 1
    assert "from line 2 through EOF once" in first
    warnings = [content for _, content in logs if "project doc exceeds" in content]
    assert len(warnings) == 1
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "first\nsecond is omitted\n"
