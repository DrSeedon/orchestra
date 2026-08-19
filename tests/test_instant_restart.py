"""#230 путь A: рестарт мгновенный, дескрипторы не зависят от вежливости сервера.

Замороженные оракулы фазы 2. Пороги времени взяты из замера
(`docs/tasks/230/research-ownership.md` F1: 1014 мс с ожиданием против 0.1 мс без него),
а не с потолка: они различают ДВА СОСТОЯНИЯ, а не измеряют производительность.
"""
import asyncio
import json
import os
import time
from types import SimpleNamespace

import pytest


def _pipes():
    """Пара пайпов в ту же сторону, что делает parent-owned спавн: (cli_out, cli_in)."""
    cli_out_r, cli_out_w = os.pipe()
    cli_in_r, cli_in_w = os.pipe()
    return cli_out_r, cli_out_w, cli_in_r, cli_in_w


async def _adopted_backend(queued: int):
    """Живой адоптированный CodexBackend с `queued` неразобранными событиями в очереди."""
    from app.backend_codex import CodexBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipes()
    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
    await backend.adopt(cli_in_w, cli_out_r, "thread-230", "turn-230")
    for i in range(queued):
        os.write(cli_out_w, (json.dumps({"method": "m", "params": {"i": i}}) + "\n").encode())
    if queued:
        for _ in range(400):
            if backend._notifications.qsize() >= queued:
                break
            await asyncio.sleep(0.005)
    return backend, cli_out_w, cli_in_r


async def _teardown(backend, *our_fds):
    """Гасим владельца явно: закрывать чужие дескрипторы — чужой упавший тест (урок #230)."""
    backend._disconnecting = True
    await backend.teardown_adopted()
    for fd in our_fds:
        try:
            os.close(fd)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_t1_quiesce_of_a_busy_backend_does_not_wait():
    """T1: подготовка занятой сессии не ждёт таймера, который ничего не защищает.

    Замер F1: 1014 мс при непустой очереди и 0.1 мс при пустой, причём цена не зависит от
    объёма (5 и 50 событий стоят одинаково) — то есть это ожидание, а не работа. Порог 200 мс
    отличает «ожидание есть» от «ожидания нет» с запасом в 5 раз вниз и в 2000 раз вверх,
    поэтому он не подрабатывает перф-ассертом и не флакает на загруженной машине.
    """
    backend, cli_out_w, cli_in_r = await _adopted_backend(queued=5)
    try:
        assert not backend._notifications.empty(), "предусловие: в очереди есть события"
        started = time.monotonic()
        assert await backend.quiesce_for_handover() is True
        waited = time.monotonic() - started
        assert waited < 0.2, (
            f"подготовка заняла {waited*1000:.0f} мс — это ожидание таймера, а не работа: "
            "остаток очереди переносится через _quiesced_events/_quiesced_prefix в любом случае"
        )
    finally:
        await _teardown(backend, cli_out_w, cli_in_r)


@pytest.mark.asyncio
async def test_t1_nothing_is_lost_when_the_wait_is_gone():
    """T1: снятие ожидания не должно стоить ни одного события, и порядок обязан уцелеть.

    ОХРАНЯЮЩИЙ, не оракул тикета: сегодня он ЗЕЛЁНЫЙ, потому что перенос уже работает. Он
    здесь затем, чтобы правка T1 не превратилась в «выбросить остаток вместо переноса» —
    это и есть самый правдоподобный неверный способ сделать тест выше зелёным.
    """
    backend, cli_out_w, cli_in_r = await _adopted_backend(queued=3)
    try:
        assert await backend.quiesce_for_handover() is True
        carried = [json.loads(line) for line in backend._quiesced_prefix.splitlines()]
        assert [event["params"]["i"] for event in carried] == [0, 1, 2], (
            "перенесены должны быть ВСЕ события и в исходном порядке")
    finally:
        await _teardown(backend, cli_out_w, cli_in_r)


@pytest.mark.asyncio
async def test_t1_fleet_of_ten_prepares_without_accumulating_waits(monkeypatch):
    """T1: цикл по флоту последовательный, поэтому ожидание умножается на число агентов.

    Приёмка требует «не больше 2 с при любом числе агентов». Десять занятых сессий сегодня
    дают ~10 с; порог 1 с ловит именно накопление, а не скорость машины.
    """
    from app.manager import SessionManager

    monkeypatch.setattr("app.fdstore.store_fds", lambda name, fds: None)
    monkeypatch.setattr("app.db.save_handover_state", lambda *a, **k: None)

    made = [await _adopted_backend(queued=2) for _ in range(10)]
    sessions = [
        SimpleNamespace(id=f"fleet-{i}", name=f"fleet-{i}", backend_type="codex",
                        _backend=backend)
        for i, (backend, _w, _r) in enumerate(made)
    ]
    try:
        started = time.monotonic()
        result = await SessionManager().prepare_restart_handover(sessions)
        waited = time.monotonic() - started
        assert result["ok"] is True, result
        assert waited < 1.0, (
            f"десять сессий готовились {waited:.1f} с — ожидание умножается на флот; "
            "приёмка требует укладываться при ЛЮБОМ числе агентов")
    finally:
        for backend, cli_out_w, cli_in_r in made:
            await _teardown(backend, cli_out_w, cli_in_r)


@pytest.mark.asyncio
async def test_t2_descriptors_reach_the_store_at_spawn(monkeypatch):
    """T2: дескрипторы попадают к systemd при спавне, а не в момент выключения.

    Сегодня `store_fds` зовётся ровно из одного места — с пути выключения. Значит при
    `kill -9`/OOM CLI переживёт сервер, а подхватить его будет нечем: дескрипторы умрут
    вместе с процессом, который их держал.
    """
    from app import manager as manager_module

    stored: dict[str, list[int]] = {}
    monkeypatch.setattr("app.fdstore.store_fds",
                        lambda name, fds: stored.__setitem__(name, list(fds)))
    if True:
        session = SimpleNamespace(
            id="spawn-230", name="spawn-230", backend_type="codex",
            _backend=SimpleNamespace(fd_in=11, fd_out=12),
        )
        assert manager_module.publish_backend_fds(session) is True, (
            "спавн обязан отдать пайпы systemd, иначе независимость агента условна")
        assert stored == {"agent.spawn-230.stdin": [11], "agent.spawn-230.stdout": [12]}, (
            f"имя→дескриптор целиком, а не набор имён: перекрещенная пара физически ломает "
            f"агента. Получено: {stored}")


def test_t2_names_are_removed_when_the_session_ends(monkeypatch):
    """T2: штатное завершение снимает имена, иначе store упирается в потолок 256."""
    from app import manager as manager_module

    removed: list[str] = []
    monkeypatch.setattr("app.fdstore.remove_fds", removed.append)
    if True:
        session = SimpleNamespace(id="gone-230", name="gone-230", backend_type="codex",
                                  _backend=SimpleNamespace(fd_in=11, fd_out=12))
        manager_module.retire_backend_fds(session)
        assert sorted(removed) == ["agent.gone-230.stdin", "agent.gone-230.stdout"], (
            f"обе стороны обязаны быть сняты, получено: {removed}")


def test_t2_a_full_store_leaves_nothing_half_published(monkeypatch):
    """T2: отказ на второй стороне обязан снять первую, а не оставить половину пары.

    Первая версия этого оракула проверяла только `is False` — и была ЗЕЛЁНОЙ на заглушке,
    которая не делает ничего и возвращает `False`. Поймано до реализации; теперь тест
    требует, чтобы попытка БЫЛА (обе стороны предъявлены store) и чтобы половина,
    оказавшаяся внутри, была снята. Половина пары хуже, чем ничего: она выглядит как
    защищённый агент, а подхватить его нельзя — нужен именно stdin И stdout.
    """
    from app import manager as manager_module

    attempted: list[str] = []
    removed: list[str] = []

    def _second_side_is_full(name, fds):
        attempted.append(name)
        if name.endswith(".stdout"):
            raise OSError("systemd fd store is full")

    monkeypatch.setattr("app.fdstore.store_fds", _second_side_is_full)
    monkeypatch.setattr("app.fdstore.remove_fds", removed.append)
    if True:
        session = SimpleNamespace(id="full-230", name="full-230", backend_type="codex",
                                  _backend=SimpleNamespace(fd_in=11, fd_out=12))
        assert manager_module.publish_backend_fds(session) is False, (
            "переполненный store обязан дать отрицательный ответ, а не проглотить отказ")
        assert attempted == ["agent.full-230.stdin", "agent.full-230.stdout"], (
            f"обе стороны обязаны быть предъявлены store, попытки: {attempted}")
        assert removed == ["agent.full-230.stdin"], (
            f"успевшая лечь сторона обязана быть снята, снято: {removed}")


@pytest.mark.asyncio
async def test_t4_grok_adopts_pipes_and_keeps_reading():
    """T4: Grok принимает унаследованные пайпы и продолжает читать поток.

    Сегодня `GrokBackend` наследует транспорт, но своего `adopt` не имеет, а `_read_stdout`
    читает `self._proc.stdout` вместо `self._out` — то есть адоптированный читатель не
    запускается вовсе, и переживший рестарт агент стримил бы в никуда.
    """
    from app.backend_grok import GrokBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipes()
    backend = GrokBackend(model="grok-4.6", cwd="/tmp")
    try:
        adopt = getattr(backend, "adopt", None)
        assert adopt is not None, "у Grok нет своего adopt — передавать его нечем"
        await adopt(cli_in_w, cli_out_r, "session-230", "turn-230")
        os.write(cli_out_w, (json.dumps(
            {"method": "session/update", "params": {"seq": 1}}) + "\n").encode())
        for _ in range(400):
            if not backend._notifications.empty():
                break
            await asyncio.sleep(0.005)
        assert not backend._notifications.empty(), (
            "принятый Grok обязан читать поток: иначе ход после рестарта не завершится никогда")
    finally:
        backend._disconnecting = True
        teardown = getattr(backend, "teardown_adopted", None)
        if teardown is not None:
            await teardown()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_t4_adopted_grok_tears_down_instead_of_returning_early():
    """T4: `disconnect` принятого Grok не имеет права выйти рано, оставив ридер и пайпы.

    `GrokBackend.disconnect` при `_proc is None` возвращается сразу и не зовёт
    `teardown_adopted` — у адоптированного бэкенда `_proc` как раз `None`, поэтому ридер,
    транспорты и дескрипторы остались бы жить рядом с новым CLI.
    """
    from app.backend_grok import GrokBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipes()
    backend = GrokBackend(model="grok-4.6", cwd="/tmp")
    try:
        adopt = getattr(backend, "adopt", None)
        assert adopt is not None, "у Grok нет своего adopt — передавать его нечем"
        await adopt(cli_in_w, cli_out_r, "session-230", "turn-230")
        assert backend._reader_task is not None, "предусловие: читатель поднят"
        await backend.disconnect()
        assert backend._reader_task is None, (
            "disconnect принятого Grok обязан снести читателя, а не вернуться рано")
    finally:
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


def test_t5_blocking_follows_capability_not_a_literal(monkeypatch):
    """T5: рестарт ждёт того, кого нельзя передать, а не того, кто не назван «codex».

    Сегодня условие — литерал `backend_type != "codex"`. После T4 Grok умеет передаваться, но
    ждать его продолжат, пока кто-нибудь не вспомнит про эту строку. Забудут ровно тогда,
    когда ожидание уже не нужно, а стоит оно до 900 с.

    Оба плеча обязательны: ошибка в сторону «не блокирует» возвращает обрывы, в сторону
    «блокирует всегда» делает рестарт недостижимым.
    """
    from app.routes import system

    async def _adopt(*a, **k):
        return None

    adoptable = SimpleNamespace(
        id="grok-230", name="grok-230", backend_type="grok", is_busy=True,
        _backend=SimpleNamespace(adopt=_adopt),
    )
    not_adoptable = SimpleNamespace(
        id="claude-230", name="claude-230", backend_type="claude", is_busy=True,
        _backend=SimpleNamespace(),
    )
    # ТОЛЬКО monkeypatch: прямое присваивание с `del` в finally УДАЛЯЛО настоящую функцию
    # из модуля, и соседние файлы падали с AttributeError, а в одиночку тест был зелёным.
    monkeypatch.setattr(system, "_drain_sessions", lambda: [adoptable, not_adoptable])
    blocking = [s.id for s in system._blocking_runtimes()]
    assert "claude-230" in blocking, (
        "рантайм без adopt обязан блокировать рестарт: его ход оборвать нельзя")
    assert "grok-230" not in blocking, (
        "рантайм С adopt блокировать не должен — иначе ожидание живёт после того, "
        "как перестало быть нужным")


@pytest.mark.asyncio
async def test_guard_spawn_path_actually_publishes_the_pipes(monkeypatch):
    """Охранник, добавленный ПОСЛЕ заморозки #230 — не оракул тикета.

    Оракулы T2 зовут `publish_backend_fds` напрямую, поэтому реализация «функция есть, но её
    никто не зовёт» проходит их все. Здесь проверяется ПУТЬ: поднялся бэкенд — пайпы у
    systemd. Мутация «убрать вызов из `_ensure_backend`» обязана красить именно этот тест.
    """
    from app.session import AgentSession

    stored: dict[str, list[int]] = {}
    monkeypatch.setattr("app.fdstore.store_fds",
                        lambda name, fds: stored.__setitem__(name, list(fds)))

    class _Backend:
        fd_in, fd_out = 21, 22
        has_owned_processes = True

        async def connect(self):
            return None

    session = AgentSession(id="wired-230", name="wired-230", scope="s", cwd="/tmp")
    monkeypatch.setattr(session, "_make_backend", lambda **kw: _Backend())
    await session._ensure_backend(activate=False)

    assert stored == {"agent.wired-230.stdin": [21], "agent.wired-230.stdout": [22]}, (
        f"путь спавна обязан сам отдать пайпы systemd, получено: {stored}")


@pytest.mark.asyncio
async def test_guard_orphan_sweep_spares_a_live_agent_and_takes_a_real_orphan(monkeypatch):
    """Охранник, добавленный ПОСЛЕ заморозки #230 — не оракул тикета. Риск 2 плана.

    После T2 дескрипторы лежат в store ПОСТОЯННО, значит уборщик встречает их на каждом
    старте. Ошибка здесь убивает работающего агента, поэтому оба плеча обязательны: живого
    не трогаем, настоящего сироту убираем. Одно плечо доказывало бы ровно половину.
    """
    from app.manager import SessionManager

    closed: list[int] = []
    killed: list = []
    monkeypatch.setattr("app.manager._inherited_named_fds",
                        lambda: [("live-230", 31), ("orphan-230", 32)])
    monkeypatch.setattr("app.manager.orphan_pids", lambda: {})
    monkeypatch.setattr("app.manager.close_orphan_fd", closed.append)
    monkeypatch.setattr("app.manager.terminate_orphan_process", killed.append)

    manager = SessionManager()
    manager.sessions["live-230"] = SimpleNamespace(id="live-230", name="live-230")

    swept = await manager.sweep_orphan_fds()

    assert closed == [32], (
        f"живой агент обязан остаться нетронутым, а сирота — убран; закрыто: {closed}")
    assert swept == 1


@pytest.mark.asyncio
async def test_guard_adopted_grok_reports_the_turn_it_carries(monkeypatch):
    """Охранник, добавленный ПОСЛЕ заморозки #230 — не оракул тикета.

    `_hand_over_backend` снимает `getattr(backend, "active_turn_id", "")`. Без свойства это
    молча даёт пустую строку: передача проходит «успешно», а следующее поколение не знает,
    какому ходу принадлежат принятые байты. Проверяется через ту же дверь, в которую стучит
    менеджер, — `getattr`, а не приватное поле.
    """
    from app.backend_grok import GrokBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipes()
    backend = GrokBackend(model="grok-4.6", cwd="/tmp")
    try:
        await backend.adopt(cli_in_w, cli_out_r, "session-230", "turn-carried-230")
        assert getattr(backend, "active_turn_id", "") == "turn-carried-230", (
            "менеджер снимает active_turn_id через getattr — без свойства ход теряет "
            "свой идентификатор молча")
    finally:
        backend._disconnecting = True
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_guard_adoption_republishes_the_descriptors(monkeypatch):
    """Охранник, добавленный ПОСЛЕ заморозки #230 — не оракул тикета.

    Найдено ЖИВЫМ СТЕНДОМ, а не тестом: после рестарта агент усыновляется через
    `adopt_backend`, который не проходит через `_ensure_backend`, поэтому дескрипторы не
    публиковались заново — `NFileDescriptorStore=0` при живом усыновлённом агенте. Защита
    работала бы ровно один раз, до первого рестарта, и это ровно тот случай, ради которого
    T2 и делался.
    """
    from app.session import AgentSession

    stored: dict[str, list[int]] = {}
    monkeypatch.setattr("app.fdstore.store_fds",
                        lambda name, fds: stored.__setitem__(name, list(fds)))

    class _Backend:
        fd_in, fd_out = 41, 42

        async def adopt(self, *a, **k):
            return None

    session = AgentSession(id="readopt-230", name="readopt-230", scope="s", cwd="/tmp")
    monkeypatch.setattr(session, "_make_backend", lambda **kw: _Backend())
    monkeypatch.setattr(session, "_activate_backend_tasks", lambda: None)
    await session.adopt_backend(41, 42, active_turn_id="turn-1")

    assert stored == {"agent.readopt-230.stdin": [41], "agent.readopt-230.stdout": [42]}, (
        f"усыновление обязано вернуть дескрипторы в store, иначе следующий kill -9 "
        f"потеряет агента; получено: {stored}")


@pytest.mark.asyncio
async def test_t6_grok_spawns_with_parent_owned_pipes(monkeypatch):
    """T6: Grok обязан создавать СВОИ пайпы, а не просить их у asyncio.

    Проба #230 T3 (`docs/tasks/230/kill9-probe.md`): CLI пережил `kill -9`, но усыновление
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


@pytest.mark.asyncio
async def test_t7_adopted_grok_keeps_listening_until_the_turn_ends():
    """T7: у принятого Grok ход обязан продолжаться, а не заканчиваться на первом событии.

    Проба #230 T3, прогон 2: усыновление прошло, но через 4 с — `listen task exited without
    exception (silent death), status=IDLE`, и обновление на границе хода штатно отпустило
    живой CLI. Причина: `events()` выходит, как только `_active_prompts <= 0 and
    _queue_depth <= 0` (`backend_grok.py`), а у принятого бэкенда счётчик нулевой — объект
    новый, промпт слал предыдущий процесс.

    Проверяется наблюдаемое: после первого НЕтерминального события итератор обязан ждать
    следующего, а не завершиться.
    """
    from app.backend_grok import GrokBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipes()
    backend = GrokBackend(model="grok-4.6", cwd="/tmp")
    try:
        await backend.adopt(cli_in_w, cli_out_r, "session-230", "turn-230")
        events = backend.events()

        os.write(cli_out_w, (json.dumps({
            "method": "session/update",
            "params": {"sessionId": "session-230", "update": {"sessionUpdate": "agent_message_chunk",
                                                              "content": {"type": "text", "text": "..."}}},
        }) + "\n").encode())
        first = await asyncio.wait_for(events.__anext__(), timeout=5)
        assert first is not None

        # Ход НЕ закончен: терминального события не приходило. Итератор обязан ждать.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(events.__anext__(), timeout=1.5)
    finally:
        backend._disconnecting = True
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_t8_grok_reports_its_turn_id_on_the_real_send_path():
    """T8: живой ход Grok обязан иметь идентификатор — иначе передавать нечего.

    Найдено при доведении приёмки 2. `_hand_over_backend` снимает
    `getattr(backend, "active_turn_id", "")`, а `adopt_backend` по пустому значению ставит
    IDLE вместо RUNNING — то есть ход считается законченным и усыновлённый CLI отпускается
    на границе хода. У Grok `_active_turn_id` ставился ТОЛЬКО внутри `adopt()`, поэтому на
    живом ходу он всегда `None`, и передача Grok не работала бы даже при штатном рестарте.

    Мой прежний охранник этого не поймал, потому что скармливал значение прямо в `adopt()` —
    проверял примитив, а не путь прода. Здесь ход начинается через `send()`.
    """
    from app.backend_grok import GrokBackend

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipes()
    backend = GrokBackend(model="grok-4.6", cwd="/tmp")
    try:
        await backend.adopt_pipes(cli_in_w, cli_out_r, limit=1024 * 1024)
        backend._session_id = "session-t8"

        assert backend.active_turn_id in (None, ""), "до хода идентификатора быть не должно"

        await backend.send("привет")
        assert backend.active_turn_id, (
            "после начала хода идентификатор обязан быть непустым: по нему менеджер решает, "
            "передавать ли ход, а adopt_backend — ставить RUNNING или IDLE")
        started = backend.active_turn_id

        # Конец хода — идентификатора снова быть не должно, иначе следующий рестарт объявит
        # RUNNING на сессии, где ход давно закончен, и она зависнет навсегда.
        backend._finish_prompt(None, "end_turn")
        assert not backend.active_turn_id, (
            f"после конца хода идентификатор обязан сниматься, остался {started!r}")
    finally:
        backend._disconnecting = True
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_acceptance2_adopted_grok_turn_runs_to_its_terminal_event(monkeypatch):
    """Приёмка 2, совместно: ход, начатый ДО смерти поколения, доигрывает ПОСЛЕ неё.

    Тикеты по одному ничего не доказывают — каждое звено рапортовало успех, пока не сделано
    следующее (T2 положили дескрипторы → T6 положили пригодные → T7 есть кому читать →
    T8 у хода есть идентификатор). Здесь цепь проверяется целиком и по наблюдаемому концу:
    сессия обязана дойти до терминального события и выйти из RUNNING.

    Поколение gen1 моделируется дубликатами дескрипторов — ровно тем, что systemd отдаёт
    новому процессу; ребёнок при этом остаётся жив, как при `kill -9`.
    """
    from app.backend_grok import GrokBackend
    from app.session import AgentSession, AgentStatus

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipes()

    gen1 = GrokBackend(model="grok-4.6", cwd="/tmp")
    await gen1.adopt_pipes(cli_in_w, cli_out_r, limit=1024 * 1024)
    gen1._session_id = "session-a2"
    await gen1.send("длинная работа")
    turn_id = gen1.active_turn_id
    assert turn_id, "разрешающее плечо: ход обязан быть начат ДО передачи"

    # systemd держит ДУБЛИКАТЫ; смерть поколения закрывает только его собственные копии.
    dup_in, dup_out = os.dup(gen1.fd_in), os.dup(gen1.fd_out)
    gen1._disconnecting = True
    await gen1.teardown_adopted()

    session = AgentSession(id="a2", name="a2", scope="s", cwd="/tmp")
    session.backend_type = "grok"
    gen2 = GrokBackend(model="grok-4.6", cwd="/tmp")
    monkeypatch.setattr(session, "_make_backend", lambda **kw: gen2)
    monkeypatch.setattr("app.manager.publish_backend_fds", lambda s: True)

    await session.adopt_backend(dup_in, dup_out, active_turn_id=turn_id)
    assert session.status == AgentStatus.RUNNING, (
        "ход был в полёте — усыновление обязано это признать, иначе CLI отпустят "
        "на ближайшей границе хода")

    # СНАЧАЛА нетерминальный кадр — так и выглядит живой ход. Без него тест не различает
    # исправную реализацию и ту, где слушатель умирает на первом событии: если первое же
    # сообщение терминальное, ход «доигрывает» даже у сломанного слушателя (проверено
    # мутацией — она оставалась зелёной).
    os.write(cli_out_w, (json.dumps({
        "method": "session/update",
        "params": {"sessionId": "session-a2",
                   "update": {"sessionUpdate": "agent_message_chunk",
                              "content": {"type": "text", "text": "работаю"}}},
    }) + "\n").encode())
    await asyncio.sleep(0.4)
    assert session.status == AgentStatus.RUNNING, (
        "нетерминальный кадр не заканчивает ход — сессия обязана остаться RUNNING")

    # Терминальное событие приходит УЖЕ новому поколению, из пережившего CLI.
    os.write(cli_out_w, (json.dumps({
        "method": "_x.ai/session/prompt_complete",
        "params": {"sessionId": "session-a2", "stopReason": "end_turn"},
    }) + "\n").encode())

    for _ in range(100):
        if session.status != AgentStatus.RUNNING:
            break
        await asyncio.sleep(0.05)

    assert session.status != AgentStatus.RUNNING, (
        "ход не доиграл: сессия осталась RUNNING, то есть терминальное событие пережившего "
        "CLI до неё не дошло")

    # Настоящая сессия поднимает фоновые задачи (слушатель, heartbeat, гибернация). Не
    # погасить их — оставить работу за собой: она всплывёт предупреждением или падением
    # ВНУТРИ более позднего теста, и виноватым будет выглядеть сосед.
    await session.abort_unpublished()
    for fd in (cli_out_w, cli_in_r):
        try:
            os.close(fd)
        except OSError:
            pass
