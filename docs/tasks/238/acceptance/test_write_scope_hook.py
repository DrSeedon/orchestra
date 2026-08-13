"""Frozen acceptance oracle for #238 — owned_dirs enforced at Edit/Write, not in prose.

Committed RED at plan time (Phase 2). Пять тестов на три тикета: T1 несёт два
(`test_t1_*` — решение по пути, `test_t1b_*` — состязательные значения периметра),
T3 несёт два (`test_t3_*` — доставка, `test_t3b_*` — совместимость существующих
конструкций контекста). Имя теста начинается с имени тикета.

Почему проверки написаны через getattr, а не через прямой импорт: прямой импорт
несуществующего символа даёт ImportError, то есть СЛОМАННЫЙ тест, а не красный.
Красный обязан падать на отсутствующем ПОВЕДЕНИИ.
"""

import os

import pytest

import app.backend_claude as backend_claude
from app.backend_claude import ClaudeBackend

_FLAG = "CLAUDE_WRITE_SCOPE_HOOK_ENABLED"
_WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _violation():
    fn = getattr(backend_claude, "_write_scope_violation", None)
    assert callable(fn), (
        "#238 T1: app.backend_claude._write_scope_violation отсутствует — "
        "чистая функция решения ещё не написана"
    )
    return fn


def _options(tmp_path, **kwargs):
    return ClaudeBackend(
        model="claude-sonnet-5[1m]",
        cwd=str(tmp_path),
        inherit_claude_md=False,
        **kwargs,
    )._make_client().options


def _write_matchers(options):
    """Матчеры записи, с проверкой КРАТНОСТИ до схлопывания в словарь.

    Без этой проверки реализация с двумя матчерами `Edit` прошла бы оракул,
    хотя план требует ровно один хук на инструмент.
    """
    matchers = (options.hooks or {}).get("PreToolUse", [])
    write = [m for m in matchers if m.matcher in _WRITE_TOOLS]
    names = [m.matcher for m in write]
    assert len(names) == len(set(names)), f"дубли матчеров записи: {names}"
    return {m.matcher: m for m in write}


def test_t1_write_scope_violation_decides_by_path_not_by_prose(tmp_path):
    """T1 — чистая функция решения: что внутри периметра, что вне."""
    decide = _violation()
    cwd = str(tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "docs" / "tasks" / "238").mkdir(parents=True)
    (tmp_path / "docs" / "tasks" / "999").mkdir(parents=True)
    (tmp_path / "docs" / "workers").mkdir(parents=True)
    (tmp_path / "other").mkdir()

    def call(path, *, owned=("app/",), task_id="238", name="me", key="file_path"):
        return decide(
            {key: path},
            cwd=cwd,
            owned_dirs=list(owned),
            task_id=task_id,
            session_name=name,
        )

    # Внутри владения — разрешено, и абсолютным путём, и относительным.
    assert call(f"{cwd}/app/main.py") is None
    assert call("app/main.py") is None

    # Вне владения — запрещено, и функция возвращает путь-нарушитель.
    outside = call(f"{cwd}/other/x.py")
    assert outside is not None and "other/x.py" in outside

    # Пустой owned_dirs — гейта нет вовсе (у нас владение необязательно).
    assert call(f"{cwd}/other/x.py", owned=()) is None

    # Исключения ПРИВЯЗАНЫ К СЕССИИ: своя задача и своя личная память — можно,
    # чужие — нельзя. Без этой привязки правка даёт обратное своей цели.
    assert call(f"{cwd}/docs/tasks/238/report.md") is None
    assert call(f"{cwd}/docs/tasks/999/report.md") is not None
    assert call(f"{cwd}/docs/workers/me.md") is None
    assert call(f"{cwd}/docs/workers/someone-else.md") is not None

    # Пустой task_id не открывает docs/tasks целиком.
    assert call(f"{cwd}/docs/tasks/238/report.md", task_id="") is not None

    # Нормализация: обход через .. закрыт.
    assert call(f"{cwd}/app/../other/x.py") is not None

    # Нормализация: обход через симлинк закрыт.
    (tmp_path / "app" / "escape").symlink_to(tmp_path / "other")
    assert call(f"{cwd}/app/escape/x.py") is not None

    # NotebookEdit несёт путь в другом ключе.
    assert call(f"{cwd}/other/x.ipynb", key="notebook_path") is not None
    assert call(f"{cwd}/app/x.ipynb", key="notebook_path") is None

    # Нет пути в payload — решать нечего, гейт молчит (и ключа нет, и ключ пустой).
    kw = {"cwd": cwd, "owned_dirs": ["app/"], "task_id": "238", "session_name": "me"}
    assert decide({}, **kw) is None
    assert decide({"file_path": ""}, **kw) is None


def test_t1b_identity_values_cannot_widen_the_perimeter(tmp_path):
    """T1 — состязательный случай: значения, которыми периметр пытаются расширить.

    Всё, что тут проверяется, приходит СНАРУЖИ функции: `owned_dirs`, `task_id` и имя
    сессии задаёт оркестратор при спавне, то есть модель. Предохранитель, который можно
    расширить данными от ограничиваемой стороны, предохранителем не является.
    """
    decide = _violation()
    cwd = str(tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "docs" / "tasks" / "238").mkdir(parents=True)
    (tmp_path / "docs" / "workers").mkdir(parents=True)
    (tmp_path / "other").mkdir()
    outside = tmp_path.parent / "sibling.txt"

    def call(path, **over):
        kw = {"cwd": cwd, "owned_dirs": ["app/"], "task_id": "238", "session_name": "me"}
        kw.update(over)
        return decide({"file_path": str(path)}, **kw)

    # task_id с разделителем/`..` не должен превращаться в пропуск за пределы своей задачи.
    for bad in ("../workers", "..", "238/../../docs", "/etc", "."):
        assert call(f"{cwd}/docs/workers/someone-else.md", task_id=bad) is not None, bad
        assert call(f"{cwd}/other/x.py", task_id=bad) is not None, bad

    # Имя сессии — то же самое: одна безопасная компонента, иначе исключения нет.
    for bad in ("../tasks/238/report", "..", "a/b", "", "   "):
        assert call(f"{cwd}/docs/workers/someone-else.md", session_name=bad) is not None, bad

    # Корни владения не могут выводить за пределы worktree.
    for bad_root in ("..", "../", "app/../..", "/"):
        assert call(str(outside), owned_dirs=[bad_root]) is not None, bad_root
        assert call(f"{cwd}/other/x.py", owned_dirs=[bad_root]) is not None, bad_root

    # И «список был непустой, но после санитизации не осталось ничего» — это гейт
    # с нулём корней (запрещено всё, кроме исключений сессии), а НЕ отсутствие гейта.
    assert call(f"{cwd}/other/x.py", owned_dirs=["../"]) is not None
    assert call(f"{cwd}/docs/tasks/238/report.md", owned_dirs=["../"]) is None


@pytest.mark.asyncio
async def test_t2_write_scope_hook_is_default_off_and_denies_when_armed(tmp_path, monkeypatch):
    """T2 — проводка хука и флаг активации: по умолчанию ВЫКЛ."""
    (tmp_path / "app").mkdir()
    (tmp_path / "other").mkdir()
    kwargs = {"owned_dirs": ["app/"], "task_id": "238", "session_name": "me"}

    monkeypatch.delenv(_FLAG, raising=False)
    assert _write_matchers(_options(tmp_path, **kwargs)) == {}, (
        "#238 T2: без CLAUDE_WRITE_SCOPE_HOOK_ENABLED=1 хук записи не ставится"
    )

    monkeypatch.setenv(_FLAG, "0")
    assert _write_matchers(_options(tmp_path, **kwargs)) == {}, "только точное '1' взводит"

    monkeypatch.setenv(_FLAG, "1")
    matchers = _write_matchers(_options(tmp_path, **kwargs))
    assert set(matchers) == set(_WRITE_TOOLS), (
        f"#238 T2: ожидались матчеры {_WRITE_TOOLS}, получено {sorted(matchers)}"
    )

    for tool in _WRITE_TOOLS:
        hooks = matchers[tool].hooks
        assert len(hooks) == 1
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"

        denied = await hooks[0]({"tool_name": tool, "tool_input": {key: f"{tmp_path}/other/x"}})
        decision = denied["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny", tool
        reason = decision["permissionDecisionReason"]
        assert "other/x" in reason and "owned_dirs" in reason, reason

        allowed = await hooks[0]({"tool_name": tool, "tool_input": {key: f"{tmp_path}/app/x"}})
        assert "permissionDecision" not in allowed["hookSpecificOutput"], tool

    # Пустой owned_dirs не взводит гейт даже при поднятом флаге.
    assert _write_matchers(_options(tmp_path, owned_dirs=[], task_id="238", session_name="me")) == {}

    # А «непустой вход, из которого санитизация не оставила ни одного корня» обязан
    # взвести гейт с нулём корней — и проверять это надо ЗДЕСЬ, на установке хука.
    # Проверка той же асимметрии только через чистую функцию дырява: фабрика может
    # санитизировать ["../"] в пустой список и не поставить матчеры вовсе, то есть
    # выключить предохранитель ровно тем значением, от которого он защищает.
    emptied = _write_matchers(
        _options(tmp_path, owned_dirs=["../"], task_id="238", session_name="me")
    )
    assert set(emptied) == set(_WRITE_TOOLS), (
        "#238 T2: owned_dirs=['../'] обязан оставить гейт включённым, а не снять его"
    )
    denied = await emptied["Write"].hooks[0](
        {"tool_name": "Write", "tool_input": {"file_path": f"{tmp_path}/other/x"}}
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_t3_session_owned_dirs_reach_the_backend(tmp_path, monkeypatch):
    """T3 — доставка: значения сессии доезжают до конструктора бэкенда."""
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    from app.session import AgentSession

    captured = {}

    def capture(backend_type, context):
        captured["ctx"] = context
        return object()

    monkeypatch.setattr("app.session.build_backend", capture)

    session = AgentSession(
        id="ws-001", name="me", scope=str(tmp_path), cwd=str(tmp_path),
        model="claude-sonnet-5[1m]", created_at=datetime.now(timezone.utc),
    )
    session.owned_dirs = ["app/"]
    session.task_id = "238"
    session._make_backend()

    ctx = captured["ctx"]
    assert list(getattr(ctx, "owned_dirs", [])) == ["app/"], (
        "#238 T3: BackendBuildContext не несёт owned_dirs — бэкенд не может знать периметр"
    )
    assert getattr(ctx, "task_id", "") == "238"
    assert getattr(ctx, "session_name", "") == "me"

    monkeypatch.setattr("app.pipeline.get_role", lambda *_args: None)
    from app.runtime_registry import build_backend

    backend = build_backend("claude", ctx)
    assert list(getattr(backend, "_owned_dirs", [])) == ["app/"], (
        "#238 T3: _claude_factory не пробрасывает owned_dirs в ClaudeBackend"
    )
    assert getattr(backend, "_task_id", "") == "238"
    assert getattr(backend, "_session_name", "") == "me"


def test_t3b_context_additions_keep_existing_construction_valid():
    """T3 — новые поля обязаны иметь дефолты: 6 мест в tests/ строят контекст без них."""
    from app.runtime_registry import BackendBuildContext

    ctx = BackendBuildContext(
        model="claude-sonnet-5[1m]", provider="anthropic", cwd="/tmp",
        system_prompt="", resume_session_id=None, mcp_servers={},
        is_orchestrator=False, scope="/tmp", pipeline="default", role="worker",
        profile="", effort=None, context_limit=200000,
    )
    assert list(getattr(ctx, "owned_dirs", [])) == []
    assert getattr(ctx, "task_id", None) == ""
    assert getattr(ctx, "session_name", None) == ""
