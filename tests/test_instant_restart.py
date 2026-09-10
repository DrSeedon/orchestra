"""Grok owns its current-generation stdio pipe descriptors."""
import os

import pytest


@pytest.mark.asyncio
async def test_t6_grok_spawns_with_parent_owned_pipes(monkeypatch):
    """T6: Grok обязан создавать СВОИ пайпы, а не просить их у asyncio.

    Проба #230 T3 (`.orchestra/tasks/230/kill9-probe.md`): CLI пережил `kill -9`, но усыновление
    провалилось с `Pipe transport is only for pipes, sockets and character devices` — в store
    лежал дескриптор, который принять нельзя. Причина: Grok спавнится с
    `stdin=PIPE, stdout=PIPE`, и `fd_in`/`fd_out` берутся у asyncio-транспорта.

    Проверяется то, что различает Codex и Grok: в спавн уходят ЧИСЛОВЫЕ дескрипторы
    настоящих пайпов, а не константа PIPE. «Положили в store» и «положили то, что можно
    принять» — разные утверждения, и первое уже один раз отработало вхолостую.
    """
    import asyncio as aio

    from app import backend_grok
    from app.backend_grok import GrokBackend

    seen: dict = {}

    class _SpawnReached(Exception):
        """Единственное исключение, которым этому тесту позволено закончиться.

        Раньше здесь стоял `pytest.raises(Exception)`, и он поглощал ЛЮБОЙ отказ — в том
        числе смерть `connect()` ДО спавна. Именно так тест и покраснел 18.08: у машины
        пропал `~/.grok/auth.json`, `_build_env` упал на `ensure_grok_home`, спавн не
        достигался, а `seen` оставался пустым. Отдельный класс делает такую смерть громкой:
        любое другое исключение вылетает наружу с настоящей причиной.
        """

    # Учётки Grok — живое состояние машины ВНЕ репозитория, и к предмету теста (какие
    # дескрипторы уходят в спавн) отношения не имеют. Тест, читающий их, мерит машину.
    monkeypatch.setattr(backend_grok, "ensure_grok_home", lambda: "/tmp")

    async def _capture(*cmd, **kwargs):
        seen.update(kwargs)
        for side in ("stdin", "stdout"):
            fd = kwargs.get(side)
            if isinstance(fd, int) and fd > 2:
                seen[f"{side}_target"] = os.readlink(f"/proc/self/fd/{fd}")
        raise _SpawnReached("spawn stopped by the oracle")

    monkeypatch.setattr(aio, "create_subprocess_exec", _capture)
    backend = GrokBackend(model="grok-4.6", cwd="/tmp")
    with pytest.raises(_SpawnReached):
        await backend.connect()

    # `asyncio.subprocess.PIPE` это -1, то есть тоже int — сравнение с типом здесь ничего не
    # значит. Различает только реальный номер дескриптора.
    assert seen.get("stdin", -1) > 2 and seen.get("stdout", -1) > 2, (
        f"в спавн обязаны уходить собственные дескрипторы, а не PIPE({aio.subprocess.PIPE}); "
        f"получено: stdin={seen.get('stdin')!r}, stdout={seen.get('stdout')!r}")
    assert seen.get("stdin_target", "").startswith("pipe:"), (
        f"stdin должен быть настоящим пайпом, а не {seen.get('stdin_target')!r}")
    assert seen.get("stdout_target", "").startswith("pipe:"), (
        f"stdout должен быть настоящим пайпом, а не {seen.get('stdout_target')!r}")
