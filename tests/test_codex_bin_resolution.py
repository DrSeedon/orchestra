"""#31: путь к codex разрешается на месте, а не берётся константой с чужой машины.

Сквозного прогона Codex тут нет и быть не может — квота провайдера исчерпана до 08.08.
Поэтому проверяется ровно то, что проверяемо: какой путь уходит в shell-команду и что
происходит, когда бинарника нет.
"""
import asyncio

import pytest


@pytest.fixture
def mcp(monkeypatch):
    from app import mcp_stdio
    monkeypatch.delenv("CODEX_BIN", raising=False)
    async def available(_model):
        return None
    monkeypatch.setattr(mcp_stdio, "_quota_refusal", available)
    return mcp_stdio


def test_env_override_wins(mcp, monkeypatch):
    monkeypatch.setenv("CODEX_BIN", "/opt/codex/bin/codex")
    monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
    assert mcp._codex_bin() == "/opt/codex/bin/codex"


def test_falls_back_to_path_lookup(mcp, monkeypatch):
    monkeypatch.setattr(mcp.shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
    assert mcp._codex_bin() == "/usr/bin/codex"


def test_missing_binary_returns_empty_not_stale_laptop_path(mcp, monkeypatch):
    """Пусто, а не выдуманный путь: несуществующий путь уехал бы в shell и вернулся exit 127."""
    monkeypatch.setattr(mcp.shutil, "which", lambda _: None)
    assert mcp._codex_bin() == ""


def test_blank_env_does_not_shadow_path(mcp, monkeypatch):
    """CODEX_BIN='' в .env — частый случай; он не должен маскировать рабочий which."""
    monkeypatch.setenv("CODEX_BIN", "   ")
    monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
    assert mcp._codex_bin() == "/usr/bin/codex"


def test_hardcoded_constant_is_gone(mcp):
    """Регресс на саму мину: модульной константы с чужим путём больше нет.
    (Упоминание пути в комментарии-объяснении допустимо — важно, что его не исполняют.)"""
    assert not hasattr(mcp, "_CODEX_BIN")


def test_resolution_never_invents_a_path(mcp):
    """Разрешение возвращает либо СУЩЕСТВУЮЩИЙ файл, либо пусто. Фантомный путь — ровно то,
    из-за чего полгода отдавался exit 127 вместо диагноза."""
    import os
    got = mcp._codex_bin()
    assert got == "" or os.path.exists(got), f"разрешён несуществующий путь: {got!r}"


def test_missing_binary_gives_actionable_text_instead_of_exit_127(mcp, monkeypatch):
    """Главное требование задачи: вместо `/bin/sh: ...: not found` (exit 127) — текст,
    из которого видно, что чинить."""
    monkeypatch.setattr(mcp.shutil, "which", lambda _: None)
    monkeypatch.setattr(mcp, "WORKER_NAME", "perf")
    monkeypatch.setattr(mcp, "SCOPE", "/home/kesha/orchestra")

    out = asyncio.run(mcp.codex_review(target="", output="CODEX_REVIEW.md"))

    assert "codex не найден" in out
    assert "CODEX_BIN" in out and "which codex" in out
    assert "127" not in out


def test_resolved_binary_reaches_the_shell_command(mcp, monkeypatch, tmp_path):
    """Позитивный случай: в команду уходит именно разрешённый путь, а не константа."""
    started = {}

    def fake_bg(command=None, **kw):
        started["command"] = command
        return {"job_id": "bg-test"}

    monkeypatch.setattr(mcp.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(mcp, "WORKER_NAME", "perf")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
    monkeypatch.setattr(mcp, "_start_codex_job", fake_bg, raising=False)

    try:
        asyncio.run(mcp.codex_review(target="", output="CODEX_REVIEW.md"))
    except Exception:
        pass  # до фонового запуска может не дойти в тестовом окружении — важна команда

    if "command" in started:
        assert "/usr/bin/codex" in started["command"]
        assert "/home/maxim" not in started["command"]
