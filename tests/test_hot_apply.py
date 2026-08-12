"""#220 — применение правок без разрушительного рестарта.

Тесты названы по тикетам плана (docs/tasks/220/plan.md). Написаны ДО реализации и
коммитятся красными: падают на отсутствующем поведении, а не на импорте.

Бэкенд берётся из `tests.test_session._MockBackend`, а НЕ из `make_backend_mock`:
у последнего `events()` ждёт вечно, и тест на регрессии зависал бы вместо падения.
"""

import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_session import _MockBackend


@pytest.fixture(autouse=True)
def _restore_drain_gate():
    """Гейт дренажа — состояние ЖИВОГО синглтона `manager`, а не фикстуры.

    Прод рассчитывает, что после `begin_drain()` процесс умрёт, поэтому сам гейт
    обратно не открывается. В тестах `os.kill` подменён — без этой уборки
    `manager.draining` утекает в следующие файлы, и там всё падает на
    `DrainingRefused` (поймано pre-mortem: 2 упавших теста при прогоне
    test_system_restart.py перед test_hot_apply.py).
    """
    yield
    from app.deps import manager
    manager.end_drain()


@pytest.fixture
def mock_db(monkeypatch):
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)


def _worker(**kw):
    from app.session import AgentSession
    s = AgentSession(
        id="t220", name="w1", scope="/s", cwd="/tmp", role="worker",
        pipeline="default", **kw,
    )
    s.session_id = "sid-220"
    return s


async def _run_one_turn(session, backend, message="do the thing"):
    """Прогнать ровно один ход и вернуть то, что доехало до бэкенда."""
    with patch.object(session, "_make_backend", return_value=backend):
        task = asyncio.create_task(session.send(message))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if backend.sent:
                break
        backend.finish()
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            await session.stop()
    assert backend.sent, "бэкенд не получил сообщения — тест не дошёл до проверяемого места"
    return backend.sent[0]


class _FakeSession:
    """Двойник сессии для дренажа — НЕ `MagicMock`.

    У `MagicMock` любой неизвестный атрибут существует и истинен, поэтому предикат
    занятости (`is_busy` = ход ИЛИ компактификация) на нём всегда True, и дренаж
    «не сходится» по вине двойника, а не кода. Поймано ровно так: после добавления
    `_compacting` в предикат тест завис на дедлайне.
    """

    def __init__(self, name="w", status=None, compacting=False):
        from app.session import AgentStatus
        self.id = f"sid-{name}"
        self.name = name
        self.status = status or AgentStatus.RUNNING
        self._compacting = compacting

    @property
    def is_busy(self):
        from app.session import AgentStatus
        return self.status == AgentStatus.RUNNING or self._compacting


# ── T1: промпт пересобирается из файлов на переинжекте ──

@pytest.mark.asyncio
async def test_t1_reinjected_prompt_rebuilds_role_text_from_disk(mock_db, monkeypatch):
    """Правка роли в pipelines/ обязана доехать до ЖИВОГО агента без рестарта.

    Сегодня ROLE_SYSTEM_PROMPT зовётся только на spawn/_load_from_db
    (docs/tasks/220/research.md, F1), поэтому переинжект отдаёт строку, собранную
    при старте сервера.
    """
    import app.manager as manager
    monkeypatch.setattr(manager, "ROLE_SYSTEM_PROMPT", lambda *a, **k: "NEW-BASE-FROM-DISK")

    s = _worker(prompt_overlay="\n\nOVERLAY-KEEP")
    s._current_prompt = "OLD-BASE-FROM-STARTUP\n\nOVERLAY-KEEP"
    s._prompt_injected = False

    sent = await _run_one_turn(s, _MockBackend())

    assert "NEW-BASE-FROM-DISK" in sent, "роль перечитана с диска"
    assert "OVERLAY-KEEP" in sent, "overlay сохранён при пересборке"


@pytest.mark.asyncio
async def test_t1_guard_custom_full_prompt_is_not_overwritten_by_rebuild(mock_db, monkeypatch):
    """СТОРОЖ, а не приёмка: зелёный сегодня и обязан остаться зелёным после T1.

    prompt_overlay is None = полная замена промпта через update_worker_prompt.

    Границы компонентов у неё нет (manager.py:1486-1491), поэтому пересборка обязана
    её НЕ трогать — иначе горячее применение молча снесёт заданную оператором роль.
    """
    import app.manager as manager
    monkeypatch.setattr(manager, "ROLE_SYSTEM_PROMPT", lambda *a, **k: "NEW-BASE-FROM-DISK")

    s = _worker(prompt_overlay=None)
    s._current_prompt = "CUSTOM-OPERATOR-PROMPT"
    s._prompt_injected = False

    sent = await _run_one_turn(s, _MockBackend())

    assert "CUSTOM-OPERATOR-PROMPT" in sent
    assert "NEW-BASE-FROM-DISK" not in sent, "кастомный промпт не перезаписан шаблоном"


@pytest.mark.asyncio
async def test_t1_broken_role_file_falls_back_to_the_startup_prompt(mock_db, monkeypatch):
    """Битый `pipelines/**` не имеет права убить следующий ход У ВСЕХ агентов.

    Pre-mortem: до T1 живая сессия НЕ звала `ROLE_SYSTEM_PROMPT` после старта, а он
    падает громко (`ValueError` на нерезолвящейся роли, `manager.py:314`). T1 ставит
    этот вызов на горячий путь переинжекта — то есть опечатка ровно в тех файлах,
    редактировать которые фича и поощряет, ломала бы всех сразу. Откат к промпту со
    старта, но с записью в журнал агента.
    """
    import app.manager as manager

    def _explode(*a, **kw):
        raise ValueError("role 'worker' not resolvable in pipeline 'typo'")

    monkeypatch.setattr(manager, "ROLE_SYSTEM_PROMPT", _explode)

    s = _worker(prompt_overlay="\n\nOVERLAY-KEEP")
    s._current_prompt = "OLD-BASE-FROM-STARTUP\n\nOVERLAY-KEEP"
    s._prompt_injected = False
    logged = []
    monkeypatch.setattr(s, "_log", lambda kind, text, **kw: logged.append((kind, text)))

    sent = await _run_one_turn(s, _MockBackend())

    assert "OLD-BASE-FROM-STARTUP" in sent, "ход не сорвался, промпт со старта"
    assert any(k == "error" and "prompt rebuild failed" in t for k, t in logged), \
        f"провал пересборки назван вслух в журнале агента: {logged}"


# ── T2: admission gate на время дренажа ──
#
# Контракт после ревью Codex (round 1, blocking #1): `enqueue_fact` — очередь ФАКТОВ,
# а не сообщений; `_attach_pending_facts` (session.py:731) прямо пишет «исходные
# сообщения НЕ пересылались» и приписывает факт к какому-то будущему сообщению, сам
# хода не начиная. Поэтому «положил в очередь = не потеряно» — ложь. Отказ громкий:
# отправитель получает исключение и повторяет сам; факт кладётся только там, где
# отправителя нет (внутренние стартеры хода).


def _gate(manager):
    begin = getattr(manager, "begin_drain", None)
    assert begin is not None, "T2: у SessionManager нет admission-гейта дренажа"
    return begin


@pytest.mark.asyncio
async def test_t2_new_turn_is_refused_loudly_while_draining(mock_db, monkeypatch):
    """В режиме дренажа новый ход не начинается, а отправитель узнаёт об этом.

    Тихая постановка в очередь запрещена: durable-очереди СООБЩЕНИЙ в проекте нет,
    а `enqueue_fact` её не заменяет (см. комментарий выше).
    """
    from app.session import AgentStatus
    import app.session as session_mod
    from app.deps import manager

    refused = getattr(session_mod, "DrainingRefused", None)
    assert refused is not None, "T2: нет типа отказа DrainingRefused"

    s = _worker()
    s.status = AgentStatus.IDLE
    backend = _MockBackend()

    _gate(manager)()
    try:
        with patch.object(s, "_make_backend", return_value=backend):
            with pytest.raises(refused):
                await asyncio.wait_for(s.send("work that must not start now"), timeout=5)
    finally:
        manager.end_drain()

    assert s.status is AgentStatus.IDLE, "ход не начат"
    assert backend.sent == [], "в бэкенд ничего не ушло"


@pytest.mark.asyncio
async def test_t2_gate_closes_atomically_against_turn_start(mock_db, monkeypatch):
    """Гейт обязан проверяться ВПЛОТНУЮ к присвоению RUNNING, без await между ними.

    Дыра, которую тест закрывает: `send()` держит `_lifecycle_lock` от session.py:840
    до присвоения `status = RUNNING` на 954, но между ними есть await
    (`_apply_pending_identity_restart`, `_apply_manifest_effort`). Ранняя проверка
    гейта + await = ход стартует ПОСЛЕ того, как дренаж снял снимок RUNNING-сессий,
    и попадает ровно под нож.
    """
    from app.session import AgentStatus
    import app.session as session_mod
    from app.deps import manager

    refused = getattr(session_mod, "DrainingRefused", None)
    assert refused is not None, "T2: нет типа отказа DrainingRefused"

    s = _worker()
    s.status = AgentStatus.IDLE
    backend = _MockBackend()

    async def _close_gate_mid_flight():
        manager.begin_drain()
        return False

    _gate(manager)
    monkeypatch.setattr(s, "_apply_manifest_effort", _close_gate_mid_flight)
    try:
        with patch.object(s, "_make_backend", return_value=backend):
            with pytest.raises(refused):
                await asyncio.wait_for(s.send("started before the gate closed"), timeout=5)
    finally:
        manager.end_drain()

    assert s.status is AgentStatus.IDLE, "ход, начатый в гонке с дренажом, не стартовал"
    assert backend.sent == [], "в бэкенд ничего не ушло"


@pytest.mark.parametrize("starter", [
    "_flush_pending", "_auto_continue", "_rate_limit_retry", "_retry_after_server_error",
])
@pytest.mark.asyncio
async def test_t2_internal_starter_queues_a_fact_instead_of_starting(
    mock_db, monkeypatch, starter,
):
    """Внутренние стартеры хода начинают его САМИ, без внешнего отправителя.

    `_flush_pending` (session.py:1561) достаёт из `_pending_messages`; `_auto_continue`
    (:2215), `_rate_limit_retry` (:2179) и `_retry_after_server_error` (:2190) — это
    автоматические продолжения. Все четверо ловят широкий `except Exception` и гасят
    сессию в IDLE с одним warning, поэтому голый `DrainingRefused` в них = тихая потеря
    продолжения (Codex round 2, blocking #1). Отказывать тут некому → факт для агента.

    Два следствия: (1) без гейта дренаж не сходится — конец хода порождает следующий;
    (2) `enqueue_fact` уместен ровно здесь и больше нигде.
    """
    from app.session import AgentStatus
    import app.session as session_mod
    from app.deps import manager

    enqueued = []
    monkeypatch.setattr(
        session_mod, "enqueue_fact",
        lambda sid, key, text: (enqueued.append((sid, key, text)), True)[1],
        raising=False,
    )
    # asyncio.sleep НЕ подменяем: подмена в модуле `asyncio` глобальна и утекла бы в
    # чужие тесты. Секунда из `_auto_continue` дешевле такого риска.
    s = _worker()
    s.status = AgentStatus.IDLE
    s._pending_messages = ["queued before the drain"]
    backend = _MockBackend()

    _gate(manager)()
    try:
        with patch.object(s, "_make_backend", return_value=backend):
            # у каждого стартера свои аргументы; задержки нулевые, чтобы тест
            # не подрабатывал измерением времени
            args = {
                "_flush_pending": (),
                "_auto_continue": (),
                "_rate_limit_retry": (0,),
                "_retry_after_server_error": (0, s._turn_gen),
            }[starter]
            await asyncio.wait_for(getattr(s, starter)(*args), timeout=10)
    finally:
        manager.end_drain()

    assert s.status is AgentStatus.IDLE, "ход не начат"
    assert backend.sent == [], "в бэкенд ничего не ушло"
    assert enqueued and enqueued[0][0] == s.id, \
        f"{starter}: агенту оставлен факт о недоставленном, а не тишина"


# ── T3: рестарт ждёт живые ходы и имеет безусловный дедлайн ──

@pytest.mark.asyncio
async def test_t3_restart_drains_before_signalling(monkeypatch):
    """`/api/restart` обязан дождаться живых ходов, а не убить их через 0.5 с."""
    from app.routes import system
    from app.session import AgentStatus

    running = _FakeSession("running", AgentStatus.RUNNING)
    idle = _FakeSession("idle", AgentStatus.IDLE)
    monkeypatch.setattr(system, "_drain_sessions", lambda: [running, idle], raising=False)
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 30, raising=False)
    kill = MagicMock()
    monkeypatch.setattr(system.os, "kill", kill)

    task = asyncio.create_task(system._restart_service_after_response())
    # сегодня рестарт спит 0.5 с и стреляет; ждём заведомо дольше
    await asyncio.sleep(1.5)
    assert not kill.called, "пока идёт ход, сигнала быть не должно"

    running.status = AgentStatus.IDLE
    await asyncio.wait_for(task, timeout=5)
    kill.assert_called_once_with(os.getpid(), signal.SIGINT)


@pytest.mark.asyncio
async def test_t3_drain_deadline_is_unconditional_and_reports_cut_turns(monkeypatch):
    """Ход может не кончиться никогда (research.md F7: цепочки agent→agent).

    Поэтому дедлайн безусловный, а число разорванных ходов называется вслух.
    """
    from app.routes import system
    from app.session import AgentStatus

    stuck = _FakeSession("stuck", AgentStatus.RUNNING)
    monkeypatch.setattr(system, "_drain_sessions", lambda: [stuck], raising=False)
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.2, raising=False)
    kill = MagicMock()
    monkeypatch.setattr(system.os, "kill", kill)

    result = await asyncio.wait_for(
        system._restart_service_after_response(), timeout=5,
    )

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
    assert isinstance(result, dict) and result.get("cut_turns") == 1, \
        "рестарт сообщает, сколько ходов разорвал"


@pytest.mark.asyncio
async def test_t3_drain_outcome_is_persisted_before_the_signal(monkeypatch):
    """После SIGINT процесса нет — значит отчитаться ПОСЛЕ него физически нельзя.

    Дыра, которую тест закрывает (Codex round 1, blocking #3): `restart_server()`
    отвечает `{"ok": True, "scheduled": True}` (system.py:1713) и уезжает, а результат
    дренажа возвращается из фоновой `_restart_service_after_response()`, которую никто
    не читает. Единственный канал, переживающий рестарт, — запись на диск ДО сигнала.
    """
    from app.routes import system
    from app.session import AgentStatus

    order = []
    stuck = _FakeSession("stuck", AgentStatus.RUNNING)
    monkeypatch.setattr(system, "_drain_sessions", lambda: [stuck], raising=False)
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.2, raising=False)
    monkeypatch.setattr(system.os, "kill", lambda *a: order.append("kill"))

    record = getattr(system, "_record_restart_outcome", None)
    assert record is not None, "T3: результат дренажа некуда записать до сигнала"
    monkeypatch.setattr(
        system, "_record_restart_outcome",
        lambda outcome: order.append(("record", outcome.get("cut_turns"))),
    )

    await asyncio.wait_for(system._restart_service_after_response(), timeout=5)

    assert order == [("record", 1), "kill"], \
        f"итог дренажа записан до SIGINT, а не после: {order}"


@pytest.mark.asyncio
async def test_t3_broken_recorder_does_not_cancel_the_signal(monkeypatch):
    """Сбой ПОБОЧНОГО учёта не отменяет рестарт.

    Дедлайн назван безусловным, значит исключение из `_record_restart_outcome()` не
    имеет права съесть `os.kill` (Codex round 2, suggestion). Это тот же класс, что
    #215: сбой учёта уничтожал оплаченный результат.
    """
    from app.routes import system
    from app.session import AgentStatus

    kill = MagicMock()
    monkeypatch.setattr(system, "_drain_sessions",
                        lambda: [_FakeSession("stuck")], raising=False)
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 0.2, raising=False)
    monkeypatch.setattr(system.os, "kill", kill)

    record = getattr(system, "_record_restart_outcome", None)
    assert record is not None, "T3: результат дренажа некуда записать до сигнала"

    def _boom(outcome):
        raise RuntimeError("disk is on fire")

    monkeypatch.setattr(system, "_record_restart_outcome", _boom)

    await asyncio.wait_for(system._restart_service_after_response(), timeout=5)

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)


# ── T4: обе точки рестарта ходят через дренаж ──

@pytest.mark.asyncio
async def test_t4_tg_restart_goes_through_drain_not_systemctl(monkeypatch):
    """TG `/restart` сегодня зовёт `sudo systemctl restart orchestra` напрямую
    (`app/tg_bridge.py:3421`) — мимо `/api/restart` и мимо будущего дренажа.

    Мост живёт в ТОМ ЖЕ процессе (`app/main.py:44`), поэтому маршрут — прямой вызов
    того же серверного workflow, без HTTP-петли на себя.
    """
    import subprocess as sp
    import app.tg_bridge as tg
    from app.routes import system

    popen = MagicMock()
    monkeypatch.setattr(sp, "Popen", popen)
    # AsyncMock, а не MagicMock: `restart_server` — `async def` (system.py:1709), и
    # хендлер, зовущий её БЕЗ await, в проде не запустил бы ничего, а обычный MagicMock
    # всё равно отметился бы как `.called` — тест был бы ложнозелёным
    # (Codex round 2, blocking #2).
    drained = AsyncMock(return_value={"waited_s": 0.0, "cut_turns": 0})
    monkeypatch.setattr(system, "restart_server", drained, raising=False)

    msg = MagicMock()
    msg.chat.id = tg.config.get("group_id")
    msg.text = "/restart"
    msg.reply = _AsyncNoop()
    msg.chat.get_member = _AsyncReturn(MagicMock(status="administrator"))

    await asyncio.wait_for(tg.handle_restart(msg), timeout=5)

    assert not popen.called, \
        f"TG всё ещё дёргает systemctl напрямую: {popen.call_args_list}"
    drained.assert_awaited_once_with()


class _AsyncNoop:
    def __init__(self):
        self.calls = []

    async def __call__(self, *a, **kw):
        self.calls.append((a, kw))


class _AsyncReturn:
    def __init__(self, value):
        self.value = value

    async def __call__(self, *a, **kw):
        return self.value
