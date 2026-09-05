"""#220 — применение правок без разрушительного рестарта.

Тесты названы по тикетам плана (.orchestra/tasks/220/plan.md). Написаны ДО реализации и
коммитятся красными: падают на отсутствующем поведении, а не на импорте.

Бэкенд берётся из `tests.test_session._MockBackend`, а НЕ из `make_backend_mock`:
у последнего `events()` ждёт вечно, и тест на регрессии зависал бы вместо падения.
"""

import asyncio
import contextlib
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_session import _MockBackend
from app.events import MessageProvenance


USER_PROVENANCE = MessageProvenance(origin="user", senders=("user",))


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
        task = asyncio.create_task(session.send(message, provenance=USER_PROVENANCE))
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
    """Правка роли в .orchestra/pipelines/ обязана доехать до ЖИВОГО агента без рестарта.

    Сегодня ROLE_SYSTEM_PROMPT зовётся только на spawn/_load_from_db
    (.orchestra/tasks/220/research.md, F1), поэтому переинжект отдаёт строку, собранную
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
    """Битый `.orchestra/pipelines/**` не имеет права убить следующий ход У ВСЕХ агентов.

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
                await asyncio.wait_for(
                    s.send("work that must not start now", provenance=USER_PROVENANCE),
                    timeout=5,
                )
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
                await asyncio.wait_for(
                    s.send("started before the gate closed", provenance=USER_PROVENANCE),
                    timeout=5,
                )
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
                "_auto_continue": (s._turn_gen,),
                "_rate_limit_retry": (0, s._turn_gen),
                "_retry_after_server_error": (0, s._turn_gen),
            }[starter]
            await asyncio.wait_for(getattr(s, starter)(*args), timeout=10)
    finally:
        manager.end_drain()

    assert s.status is AgentStatus.IDLE, "ход не начат"
    assert backend.sent == [], "в бэкенд ничего не ушло"
    assert enqueued and enqueued[0][0] == s.id, \
        f"{starter}: агенту оставлен факт о недоставленном, а не тишина"


# ── T3: рестарт сразу прерывает живые ходы ──

@pytest.mark.asyncio
async def test_t3_restart_signals_without_waiting_for_live_turns(monkeypatch):
    """`/api/restart` interrupts live turns instead of granting them a grace period."""
    from app.routes import system
    from app.session import AgentStatus

    running = _FakeSession("running", AgentStatus.RUNNING)
    idle = _FakeSession("idle", AgentStatus.IDLE)
    # This test forbids waiting for turns, not slow filesystem telemetry.
    # Persistence-before-signal has its own test below.
    monkeypatch.setattr(system, "_record_restart_outcome", MagicMock())
    monkeypatch.setattr(system, "_drain_sessions", lambda: [running, idle], raising=False)
    kill = MagicMock()
    monkeypatch.setattr(system.os, "kill", kill)

    result = await asyncio.wait_for(
        system._restart_service_after_response(), timeout=0.5,
    )

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
    assert result["cut_names"] == ["running"]


@pytest.mark.asyncio
async def test_t3_restart_cuts_blocking_turns_without_grace(monkeypatch):
    """Live turns cannot postpone a restart, even when they never finish.

    The interrupted session is named for startup recovery, but no wait is permitted first.
    """
    from app.routes import system
    from app.session import AgentStatus

    stuck = _FakeSession("stuck", AgentStatus.RUNNING)
    monkeypatch.setattr(system, "_drain_sessions", lambda: [stuck], raising=False)
    kill = MagicMock()
    monkeypatch.setattr(system.os, "kill", kill)

    result = await asyncio.wait_for(
        system._restart_service_after_response(), timeout=0.5,
    )

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
    assert result["ok"] is True and result["cut_names"] == ["stuck"]
    assert result["cut_turns"] == 1
    assert result["restore_after_restart"] == ["sid-stuck"], \
        "прерванный ход обязан быть явно передан пути восстановления"


@pytest.mark.asyncio
async def test_t3_restart_never_attempts_live_turn_handover(monkeypatch):
    """Every live turn is cut; adopt capability is irrelevant to restart latency."""
    from app import main as app_main
    from app.routes import system

    would_refuse = {
        "ok": False,
        "reason": "agent-one refused the handover",
        "refused_ids": ["sid-agent-one"],
        "refused_names": ["agent-one"],
    }
    running = _FakeSession("agent-one")
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr(system, "_drain_sessions", lambda: [running])
    prepare = AsyncMock(return_value=would_refuse)
    monkeypatch.setattr(system.manager, "prepare_restart_handover", prepare)
    kill = MagicMock()
    monkeypatch.setattr(system.os, "kill", kill)

    result = await asyncio.wait_for(system._restart_service_after_response(), timeout=0.5)

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
    prepare.assert_not_awaited()
    assert result["ok"] is True
    assert result["cut_names"] == ["agent-one"]
    assert result["restore_after_restart"] == ["sid-agent-one"]


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
    # #237 T3: сессия должна быть СВОБОДНА, иначе рестарт теперь отменяется и до записи с
    # сигналом дело не доходит вовсе. Проверяемое свойство — порядок «запись → сигнал» —
    # прежнее; изменился только путь, на котором сигнал вообще случается.
    idle = _FakeSession("idle", AgentStatus.IDLE)
    monkeypatch.setattr(system, "_drain_sessions", lambda: [idle], raising=False)
    monkeypatch.setattr(system.os, "kill", lambda *a: order.append("kill"))

    record = getattr(system, "_record_restart_outcome", None)
    assert record is not None, "T3: результат дренажа некуда записать до сигнала"
    monkeypatch.setattr(
        system, "_record_restart_outcome",
        lambda outcome: order.append(("record", outcome.get("cut_turns"))),
    )

    await asyncio.wait_for(system._restart_service_after_response(), timeout=5)

    assert order == [("record", 0), "kill"], \
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
    # #237 T3: свободная сессия, потому что живой неподдержанный ход теперь отменяет рестарт,
    # и «сбой учёта не отменяет сигнал» стало бы непроверяемым — сигнала не было бы и так.
    monkeypatch.setattr(system, "_drain_sessions",
                        lambda: [_FakeSession("idle", AgentStatus.IDLE)], raising=False)
    monkeypatch.setattr(system.os, "kill", kill)

    record = getattr(system, "_record_restart_outcome", None)
    assert record is not None, "T3: результат дренажа некуда записать до сигнала"

    def _boom(outcome):
        raise RuntimeError("disk is on fire")

    monkeypatch.setattr(system, "_record_restart_outcome", _boom)

    await asyncio.wait_for(system._restart_service_after_response(), timeout=5)

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)


@pytest.mark.asyncio
async def test_guard_failed_restart_never_leaves_the_agent_gate_closed(monkeypatch):
    """Охранник, добавленный ПОСЛЕ заморозки #237 — не оракул тикета.

    Замечен полным прогоном, а не ревью: #237 T3 закрывает приём ходов уже в preflight, и
    падение до планирования фоновой задачи оставляло `draining=True` навсегда. В проде это
    «каждый ход отвергнут с retry later» до следующего рестарта — ровно тот класс залипшего
    гейта, который в #220 стоил 503 на всём сьюте.
    """
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    async def boom():
        raise RuntimeError("preflight exploded")

    monkeypatch.setattr(app_main, "drain_mutating_requests", boom)

    with pytest.raises(RuntimeError, match="preflight exploded"):
        await system.restart_server()

    assert manager.draining is False, "провалившийся рестарт обязан вернуть приём ходов"
    assert app_main.mutating_admission_verdict(
        "POST", "/api/sessions/worker/send")["allowed"] is True


@pytest.mark.asyncio
async def test_guard_watchdog_gives_a_prepared_fleet_its_readers_back(monkeypatch):
    """Охранник, добавленный ПОСЛЕ заморозки #237 — не оракул тикета.

    Найдено pre-mortem'ом: сторож переоткрывал гейты, но не откатывал уже переданный флот.
    Рестарт, не случившийся после успешной подготовки, оставлял бы агентов КВИЕСЦИРОВАННЫМИ —
    то есть живыми, но глухими навсегда, — а их дескрипторы копились бы в systemd до
    исчерпания store. Сторож обязан вернуть читателя, а не только приём запросов.
    """
    from app.routes import system

    rollback = AsyncMock()
    monkeypatch.setattr(system.manager, "rollback_restart_handover", rollback,
                        raising=False)
    monkeypatch.setattr(system, "_watchdog_budget_s", lambda: 0.01)
    monkeypatch.setattr(system, "_restart_attempt", 7)

    await asyncio.wait_for(system._reopen_admission_if_still_alive(7), timeout=2)

    rollback.assert_awaited_once_with()


def test_guard_watchdog_outlasts_mutating_drain_and_response_flush():
    """Охранник, добавленный ПОСЛЕ заморозки #237 — не оракул тикета.

    Worker turns no longer contribute any wait budget. The watchdog still has to outlast the
    response flush and an already-admitted mutating request, the two waits restart retains.
    """
    from app import main as app_main
    from app.routes import system

    entitled = (system._RESPONSE_FLUSH_PAUSE_S
                + app_main.MUTATING_DRAIN_BUDGET_S)
    assert system._watchdog_budget_s() > entitled, (
        f"сторож ({system._watchdog_budget_s()}s) обязан переживать ВСЁ, что рестарт вправе "
        f"ждать после взведения ({entitled}s): паузу на ответ и повторный дренаж HTTP. "
        f"Worker turns do not extend this budget")


@pytest.mark.asyncio
async def test_guard_aborted_attempt_disarms_its_watchdog_but_a_signalling_one_does_not():
    """Охранник, добавленный ПОСЛЕ раунда 2 ревью #237 — не оракул тикета.

    Ревьюер превратил `_disarm_watchdog_if_aborted` целиком в no-op и получил `65 passed`:
    отмену сторожа не проверял никто. Оба направления обязаны быть здесь, потому что
    ошибиться можно в обе стороны и обе дорого:

    * не снять после отказа → сторож доживает до следующей попытки и стреляет в её
      транзакцию (это и есть B2);
    * снять после успешного сигнала → исчезает единственный случай, ради которого сторож
      существует: сигнал ушёл, а процесс не умер, и гейты остались закрытыми навсегда.
    """
    from app.routes import system

    async def _pending():
        await asyncio.sleep(3600)  # ДОЛЖЕН реально висеть: отмена завершённой задачи — no-op,
        #                            и тест зеленел бы, ничего не проверив

    async def _finished(outcome):
        return outcome

    for label, attempt_result, must_cancel in (
        ("отказ рестарта", {"ok": False, "reason": "blocked"}, True),
        ("сигнал ушёл", {"waited_s": 1.0, "cut_turns": 0}, False),
    ):
        watchdog = asyncio.create_task(_pending())
        done = asyncio.create_task(_finished(attempt_result))
        await done
        system._disarm_watchdog_if_aborted(done, watchdog)
        # `.cancel()` только ЗАПРАШИВАЕТ отмену: без такта цикла задача остаётся
        # в состоянии `cancelling`, и `cancelled()` вернёт False на исправном коде.
        for _ in range(10):
            if watchdog.cancelled():
                break
            await asyncio.sleep(0)
        assert watchdog.cancelled() is must_cancel, (
            f"{label}: сторож {'обязан быть снят' if must_cancel else 'обязан остаться'}")
        watchdog.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog

    # третье направление: попытка упала исключением — гейты уже открыты её обработчиком
    watchdog = asyncio.create_task(_pending())

    async def _raises():
        raise RuntimeError("restart path failed")

    failed = asyncio.create_task(_raises())
    with contextlib.suppress(RuntimeError):
        await failed
    system._disarm_watchdog_if_aborted(failed, watchdog)
    for _ in range(10):
        if watchdog.cancelled():
            break
        await asyncio.sleep(0)
    assert watchdog.cancelled() is True, "упавшая попытка обязана снять своего сторожа"
    with contextlib.suppress(asyncio.CancelledError):
        await watchdog


@pytest.mark.asyncio
async def test_guard_watchdog_of_a_superseded_attempt_stands_down(monkeypatch):
    """Охранник, добавленный ПОСЛЕ заморозки #237 — не оракул тикета.

    Ревью #237 (B2): сторож жил дольше своей попытки и не был с ней связан. Сработав во
    время СЛЕДУЮЩЕГО рестарта, он снял бы дескрипторы из systemd store и открыл оба гейта
    посреди чужой транзакции — а та всё равно дошла бы до сигнала.
    """
    from app.routes import system

    rollback = AsyncMock()
    monkeypatch.setattr(system.manager, "rollback_restart_handover", rollback,
                        raising=False)
    monkeypatch.setattr(system, "_watchdog_budget_s", lambda: 0.01)
    monkeypatch.setattr(system, "_restart_attempt", 8)  # попытка 7 уже не текущая

    await asyncio.wait_for(system._reopen_admission_if_still_alive(7), timeout=2)

    assert rollback.await_count == 0, \
        "сторож устаревшей попытки не имеет права трогать чужую транзакцию"


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
