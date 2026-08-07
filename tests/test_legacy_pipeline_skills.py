"""#167 дефект 3: легаси-строка с pipeline='' оставляла оркестратора без скиллов.

Журнал 06.08 (14:57:25 и 14:58:59): «skill refresh failed: pipeline name is empty»
на каждом пробуждении. Корневой Orchestra-orchestrator — единственная ЖИВАЯ
сессия с пустым pipeline; на диске у него лежал 1 каталог скилла из 5 заявленных.

Причина — один pipeline читался ДВУМЯ способами внутри одной функции
_load_from_db: строка 1357 нормализовала '' → 'default' (и промпт был верный),
а конструктор AgentSession получал сырой db_row (''), и _refresh_skills падал.
"""

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
