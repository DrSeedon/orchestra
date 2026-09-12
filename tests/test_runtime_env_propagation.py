"""#V-559: подпроцессы MCP обязаны видеть ТУ ЖЕ базу и то же хранилище задач.

Краснеет, если из проброса убрать `ORCHESTRA_*`: подпроцесс тогда открывает
дефолтную `data/orchestra.db`, которая непуста и осталась на `user_version=0`,
и умирает на стороже схемы — именно так 12.09.2026 сломался `codex_review`
во всех проектах, и выглядело это как отказ ревью, а не как чужая база.
"""
import importlib
import os

import pytest


@pytest.mark.parametrize("name", [
    "ORCHESTRA_DB_PATH",
    "ORCHESTRA_TASK_REPOSITORY",
])
def test_state_selecting_env_reaches_mcp_subprocess(monkeypatch, tmp_path, name):
    monkeypatch.setenv(name, str(tmp_path / "selected"))
    import app.runtime_env as runtime_env
    importlib.reload(runtime_env)
    try:
        assert runtime_env.MCP_BASE_ENV.get(name) == str(tmp_path / "selected"), (
            f"{name} не доехал до подпроцесса: он откроет чужое состояние"
        )
    finally:
        importlib.reload(runtime_env)


def test_absent_variable_is_not_invented(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_DB_PATH", raising=False)
    import app.runtime_env as runtime_env
    importlib.reload(runtime_env)
    try:
        assert "ORCHESTRA_DB_PATH" not in runtime_env.MCP_BASE_ENV
    finally:
        monkeypatch.undo()
        importlib.reload(runtime_env)
