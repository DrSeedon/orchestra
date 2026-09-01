"""Аудит 01.09: обёртка вправе добавить КОД, но не вправе подменить ПРИЧИНУ.

Три места в `app/mcp_stdio.py` печатали то, что вернул последний слой, а не то, что
произошло: терминальный отказ доставки как приёмку, подтверждённый FAILED мержа как
«статус не удалось подтвердить», и инструкцию на повтор без предупреждения о чужом
репозитории.
"""

import pytest

DELIVERY_ID = "11111111-2222-3333-4444-555555555555"
OPERATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _quota_refused_receipt() -> dict:
    """Ровно то, что отдаёт GET /api/message-deliveries/<id> на отказе до отправки.

    Форма снята с `app.message_deliveries._resource` + `_failure(QuotaGateError)`.
    """
    return {
        "ok": True,
        "acceptance": "ALREADY_ACCEPTED",
        "delivery_id": DELIVERY_ID,
        "delivery_state": "FAILED_BEFORE_SUBMIT",
        "payload_hash": "a" * 64,
        "accept_seq": 1,
        "status_url": f"/api/message-deliveries/{DELIVERY_ID}",
        "provider_ref": None,
        "error": {
            "code": "DELIVERY_NOT_SUBMITTED",
            "message": (
                "Provider submission did not begin: QuotaGateError: "
                "codex.primary is above the admission line"
            ),
            "retryable": True,
            "outcome_unknown": False,
        },
        "next_action": {},
    }


@pytest.mark.asyncio
async def test_failed_before_submit_is_never_reported_as_accepted(monkeypatch):
    """Сообщение не дошло до провайдера — читаться это обязано как отказ.

    POST истёк по таймауту, сверочный GET нашёл строку в FAILED_BEFORE_SUBMIT
    (штатный исход QuotaGateError). Печатать её как «Message accepted» — молчаливая
    потеря задания: отправитель идёт дальше, повтора не будет никогда.
    """
    import app.mcp_stdio as mcp

    receipt = _quota_refused_receipt()

    async def timeout_then_failed(method, path, **kwargs):
        if method == "POST":
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                outcome_unknown=True,
                details={"request_not_sent": False, "method": "POST", "path": path},
            )
        assert path == f"/api/message-deliveries/{DELIVERY_ID}"
        return receipt

    monkeypatch.setattr(mcp, "_api", timeout_then_failed)

    output = await mcp.send_message(
        to="sol-worker", message="забери задачу #123", delivery_id=DELIVERY_ID,
    )

    assert "accepted" not in output.lower()
    assert "FAILED_BEFORE_SUBMIT" in output
    assert "DELIVERY_NOT_SUBMITTED" in output
    assert "codex.primary is above the admission line" in output
    assert DELIVERY_ID in output


def _target_changed_receipt() -> dict:
    """Тот же FAILED_BEFORE_SUBMIT, но по НЕПОВТОРИМОЙ причине.

    Форма снята с `app.message_deliveries._failure(TargetTaskChangedError)`.
    """
    receipt = _quota_refused_receipt()
    receipt["error"] = {
        "code": "TARGET_TASK_CHANGED",
        "message": "target task generation changed before delivery",
        "retryable": False,
        "outcome_unknown": False,
    }
    return receipt


@pytest.mark.asyncio
async def test_target_task_changed_is_not_sent_into_a_retry_loop(monkeypatch):
    """У одного состояния две причины, и повторять можно только одну.

    `routes/sessions.py` принимает повтор с тем же delivery_id против ЗАМОРОЖЕННОГО
    `target_generation`, а `manager.send_message_delivery` сверяет его с живой сессией:
    у TARGET_TASK_CHANGED причина по построению не исчезает, поэтому «повтори тем же
    id» — вечный цикл. Доставить может только новое сообщение с новым id.
    """
    import app.mcp_stdio as mcp

    receipt = _target_changed_receipt()

    async def timeout_then_changed(method, path, **kwargs):
        if method == "POST":
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                outcome_unknown=True,
                details={"request_not_sent": False, "method": "POST", "path": path},
            )
        return receipt

    monkeypatch.setattr(mcp, "_api", timeout_then_changed)

    output = await mcp.send_message(
        to="sol-worker", message="забери задачу #123", delivery_id=DELIVERY_ID,
    )

    assert "accepted" not in output.lower()
    assert "TARGET_TASK_CHANGED" in output
    assert "same delivery_id" not in output
    assert "new delivery_id" in output

    # Повторимая причина того же состояния совет не меняет: квота уходит, и текст
    # обязан остаться прежним — иначе ветвление по коду сломало бы штатный повтор.
    quota = _quota_refused_receipt()

    async def timeout_then_quota(method, path, **kwargs):
        if method == "POST":
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                outcome_unknown=True,
                details={"request_not_sent": False, "method": "POST", "path": path},
            )
        return quota

    monkeypatch.setattr(mcp, "_api", timeout_then_quota)

    retryable = await mcp.send_message(
        to="sol-worker", message="забери задачу #123", delivery_id=DELIVERY_ID,
    )

    assert f'delivery_id="{DELIVERY_ID}"' in retryable
    assert "new delivery_id" not in retryable


@pytest.mark.asyncio
async def test_spawn_does_not_report_undelivered_task_as_accepted(monkeypatch):
    """Тот же дефект на соседнем вызове: спавн печатал «Task accepted» на отказе.

    POST доставки истёк по таймауту, сверочный GET нашёл строку в
    FAILED_BEFORE_SUBMIT — воркер создан и стоит БЕЗ задания. «Task accepted»
    здесь дороже, чем в сообщении: спавнящий уходит, а задача не начата никогда.
    """
    import app.mcp_stdio as mcp

    monkeypatch.setattr(mcp, "SCOPE", "/repo")
    monkeypatch.setattr(mcp, "WORKER_NAME", "orchestrator")

    async def spawned_then_not_submitted(method, path, **kwargs):
        if path == "/api/sessions":
            return {
                "worktree_path": "/orchestra/worktrees/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
                "branch": "task-1/child",
            }
        if method == "POST":
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                status=None,
                outcome_unknown=True,
                details={"request_not_sent": False, "method": "POST", "path": path},
            )
        return {
            "ok": True,
            "delivery_id": DELIVERY_ID,
            "delivery_state": "FAILED_BEFORE_SUBMIT",
            "payload_hash": "b" * 64,
            "status_url": f"/api/initial-deliveries/{DELIVERY_ID}",
            "provider_ref": None,
            "error": {
                "code": "DELIVERY_NOT_SUBMITTED",
                "message": "Provider submission did not begin: QuotaGateError",
                "retryable": True,
                "outcome_unknown": False,
            },
        }

    monkeypatch.setattr(mcp, "_api", spawned_then_not_submitted)

    output = await mcp.spawn_worker(
        name="child",
        task="собери ресёрч",
        repo_path="/repo",
        model="opus",
        delivery_id=DELIVERY_ID,
    )

    assert "Task accepted" not in output
    assert "NOT delivered" in output
    assert "retry_initial_delivery" in output
    assert "FAILED_BEFORE_SUBMIT" in output


@pytest.mark.asyncio
async def test_recovered_failed_merge_keeps_its_confirmed_cause(monkeypatch):
    """Сверка ПОСЛЕ сбоя транспорта нашла запись — значит статус подтверждён.

    Настоящий FAILED несёт реальную причину (грязное рабочее дерево). Отбрасывать
    его по состоянию — значит вернуть UNKNOWN и текст транспорта вместо ответа,
    который уже на руках. Псевдо-FAILED от 404 (OPERATION_NOT_FOUND) при этом
    обязан по-прежнему давать UNKNOWN — ради него guard и заводился.
    """
    import app.mcp_stdio as mcp
    import app.merge_operations as operations

    dirty = (
        "target working tree is dirty (2 file(s): app/mcp_stdio.py, tests/) "
        "— commit or discard first"
    )
    failed = operations.normalize_merge_result(
        OPERATION_ID,
        {
            "ok": True,
            "state": "merged",
            "commit_point": "not_reached",
            "target_branch": "main",
            "target_before": "a" * 40,
            "target_after": "a" * 40,
            "worker_branch": "task-1/worker",
            "worker_head": "b" * 40,
            "conflicts": [],
            "commits_merged": 0,
            "error": dirty,
        },
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )
    assert failed["operation_state"] == "FAILED"

    def _stalled_post(path):
        return mcp.ApiToolError(
            code="transport_timeout",
            message="ReadTimeout",
            outcome_unknown=True,
            details={"request_not_sent": False, "method": "POST", "path": path},
        )

    async def stalled_post_then_failed_get(method, path, **kwargs):
        if method == "POST":
            raise _stalled_post(path)
        # Живой GET на FAILED-записи отдаёт непустой top-level error, поэтому `_api`
        # поднимает ApiToolError с доменным результатом в `.result`.
        raise mcp.ApiToolError(
            code=failed["error"]["code"],
            message=failed["error"]["message"],
            status=200,
            details={"method": method, "path": path},
            result=failed,
        )

    monkeypatch.setattr(mcp, "_api", stalled_post_then_failed_get)

    confirmed = await mcp.merge_worker(name="worker", operation_id=OPERATION_ID)
    payload = confirmed.structuredContent["result"]
    text = confirmed.content[0].text

    assert payload["operation_state"] == "FAILED"
    assert dirty in payload["error"]["message"]
    assert dirty in text
    assert "could not be confirmed" not in text

    missing = operations.operation_not_found_result(OPERATION_ID)

    async def stalled_post_then_missing_get(method, path, **kwargs):
        if method == "POST":
            raise _stalled_post(path)
        raise mcp.ApiToolError(
            code="OPERATION_NOT_FOUND",
            message=missing["error"]["message"],
            status=404,
            details={"method": method, "path": path},
            result=missing,
        )

    monkeypatch.setattr(mcp, "_api", stalled_post_then_missing_get)

    unknown = await mcp.merge_worker(name="worker", operation_id=OPERATION_ID)

    assert unknown.structuredContent["result"]["operation_state"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_spawn_retry_guidance_keeps_cross_repo_warning(monkeypatch):
    """Повтор доставки обязан нести ТОТ ЖЕ текст задания, что ушёл в первый раз.

    Иначе воркер чужого репозитория получает задание без предупреждения о
    расхождении — ровно тот отказ, ради которого предупреждение и заводилось.
    """
    import app.mcp_stdio as mcp

    monkeypatch.setattr(mcp, "SCOPE", "/projects/alpha")
    monkeypatch.setattr(mcp, "WORKER_NAME", "orchestrator")
    session = {
        "worktree_path": "/orchestra/worktrees/beta/child",
        "repo_path": "/projects/beta",
        "git_common_dir": "/projects/beta/.git",
        "branch": "task-1/child",
    }

    async def created(method, path, **kwargs):
        assert (method, path) == ("POST", "/api/sessions")
        return session

    async def refused(name, task, delivery_id, scope):
        raise mcp.ApiToolError(
            code="connect_error",
            message="connection refused",
            details={"request_not_sent": True, "method": "POST"},
        )

    monkeypatch.setattr(mcp, "_api", created)
    monkeypatch.setattr(mcp, "_post_initial_delivery", refused)

    with pytest.raises(mcp.ApiToolError) as caught:
        await mcp.spawn_worker(
            name="child",
            task="собери ресёрч по портфелю",
            repo_path="/projects/beta",
            model="opus",
            delivery_id=DELIVERY_ID,
        )

    next_action = caught.value.result["next_action"]
    assert next_action["code"] == "RETRY_SAME_DELIVERY"
    retried_task = next_action["arguments"]["task"]
    assert "собери ресёрч по портфелю" in retried_task
    assert "ДРУГОЙ РЕПОЗИТОРИЙ" in retried_task


HEAD_DELIVERY_ID = "99999999-8888-7777-6666-555555555555"


def _queue_blocked_receipt() -> dict:
    """Приёмка за неразобранной головой очереди.

    Форма снята с `app.message_deliveries._resource` + `_queue_block`: состояние
    остаётся QUEUED, а весь диагноз лежит в `next_action`.
    """
    return {
        "ok": True,
        "acceptance": "ACCEPTED",
        "delivery_id": DELIVERY_ID,
        "delivery_state": "QUEUED",
        "payload_hash": "c" * 64,
        "accept_seq": 7,
        "status_url": f"/api/message-deliveries/{DELIVERY_ID}",
        "provider_ref": None,
        "error": None,
        "next_action": {
            "code": "TARGET_QUEUE_BLOCKED",
            "tool": "message_delivery_status",
            "arguments": {"delivery_id": HEAD_DELIVERY_ID},
            "blocked_since": "2026-08-31T09:14:00+00:00",
            "retryable": False,
            "message": (
                "Message accepted but NOT delivered: the target queue has been blocked "
                f"since 2026-08-31T09:14:00+00:00 by delivery {HEAD_DELIVERY_ID} "
                "(DELIVERY_UNKNOWN), and nothing queued after it moves until that one is "
                "reconciled. Do not resend this message — an operator clears the barrier "
                f"with POST /api/message-deliveries/{HEAD_DELIVERY_ID}/resolve."
            ),
        },
    }


@pytest.mark.asyncio
async def test_queue_blocked_acceptance_is_not_printed_as_delivery(monkeypatch):
    """Принято ≠ доставлено: за барьером DELIVERY_UNKNOWN очередь стоит.

    `message_deliveries._queue_block` уже кладёт диагноз в `next_action`, но receipt
    печатался по одному лишь `state`, и отправитель читал бодрый «Message accepted …
    state=QUEUED» — ровно то, из-за чего воркер простоял глухим 25 часов.
    """
    import app.mcp_stdio as mcp

    receipt = _queue_blocked_receipt()

    async def accepted_behind_barrier(method, path, **kwargs):
        assert (method, path) == ("POST", "/api/sessions/sol-worker/send")
        return receipt

    monkeypatch.setattr(mcp, "_api", accepted_behind_barrier)

    output = await mcp.send_message(
        to="sol-worker", message="забери задачу #123", delivery_id=DELIVERY_ID,
    )

    assert "Message accepted to" not in output, (
        "приёмку за заблокированной головой напечатали как доставку"
    )
    assert "NOT delivered" in output
    assert HEAD_DELIVERY_ID in output, "не назван тот delivery_id, что держит очередь"
    assert "2026-08-31T09:14:00+00:00" in output, "не сказано, с каких пор очередь стоит"
    assert "resolve" in output, "не назван единственный законный выход — разбор головы"
    # Условие блокировки остаётся у message_deliveries: текст обязан приехать из
    # next_action, а не быть выведен здесь заново.
    assert receipt["next_action"]["message"] in output


def _resolved_barrier_receipt() -> dict:
    """Голова очереди, у которой человек снял барьер, не выяснив исход.

    Форма снята с `app.message_deliveries.resolve_message_delivery`.
    """
    return {
        "ok": True,
        "acceptance": "ALREADY_ACCEPTED",
        "delivery_id": DELIVERY_ID,
        "delivery_state": "DELIVERY_UNKNOWN_ORPHANED",
        "payload_hash": "d" * 64,
        "accept_seq": 3,
        "status_url": f"/api/message-deliveries/{DELIVERY_ID}",
        "provider_ref": None,
        "error": {
            "code": "DELIVERY_OUTCOME_UNKNOWN",
            "message": "Provider outcome is unknown: ReadTimeout",
            "retryable": False,
            "outcome_unknown": True,
        },
        "next_action": {},
    }


@pytest.mark.asyncio
async def test_cleared_barrier_is_not_reported_as_delivered(monkeypatch):
    """Снятие барьера не доставляет сообщение — исход провайдера остался неизвестным.

    `DELIVERY_UNKNOWN` печатался честно только по ТОЧНОМУ совпадению строки, поэтому
    снятое рестартом состояние проваливалось в «Message accepted … state=
    DELIVERY_UNKNOWN_ORPHANED»: отправитель, перепроверивший тот же delivery_id,
    читал приёмку как доставку.
    """
    import app.mcp_stdio as mcp

    receipt = _resolved_barrier_receipt()

    async def timeout_then_resolved(method, path, **kwargs):
        if method == "POST":
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                outcome_unknown=True,
                details={"request_not_sent": False, "method": "POST", "path": path},
            )
        assert path == f"/api/message-deliveries/{DELIVERY_ID}"
        return receipt

    monkeypatch.setattr(mcp, "_api", timeout_then_resolved)

    output = await mcp.send_message(
        to="sol-worker", message="забери задачу #123", delivery_id=DELIVERY_ID,
    )

    assert "accepted" not in output.lower(), "разобранный барьер напечатан как приёмка"
    assert "unknown" in output.lower()
    assert "DELIVERY_UNKNOWN_ORPHANED" in output
    assert "restart" in output.lower(), "не сказано, ЧЕМ снят барьер"


@pytest.mark.asyncio
async def test_spawn_does_not_report_unknown_delivery_as_accepted(monkeypatch):
    """Тот же разрыв на спавне: неизвестный исход печатался как «Task accepted».

    Сверка после сбоя транспорта возвращает запись в ЛЮБОМ состоянии, и `DELIVERY_UNKNOWN`
    у неё значит «неизвестно, дошло ли задание». Спавнящий, прочитав приёмку, уходит и
    больше не проверяет — воркер остаётся без задачи молча.
    """
    import app.mcp_stdio as mcp

    monkeypatch.setattr(mcp, "SCOPE", "/repo")
    monkeypatch.setattr(mcp, "WORKER_NAME", "orchestrator")

    async def spawned_then_unknown(method, path, **kwargs):
        if path == "/api/sessions":
            return {
                "worktree_path": "/orchestra/worktrees/child",
                "repo_path": "/repo",
                "git_common_dir": "/repo/.git",
                "branch": "task-1/child",
            }
        if method == "POST":
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                status=None,
                outcome_unknown=True,
                details={"request_not_sent": False, "method": "POST", "path": path},
            )
        return {
            "ok": True,
            "delivery_id": DELIVERY_ID,
            "delivery_state": "DELIVERY_UNKNOWN",
            "payload_hash": "e" * 64,
            "status_url": f"/api/initial-deliveries/{DELIVERY_ID}",
            "provider_ref": None,
            "error": {
                "code": "DELIVERY_OUTCOME_UNKNOWN",
                "message": "Provider outcome is unknown: ReadTimeout",
                "retryable": False,
                "outcome_unknown": True,
            },
        }

    monkeypatch.setattr(mcp, "_api", spawned_then_unknown)

    output = await mcp.spawn_worker(
        name="child",
        task="собери ресёрч",
        repo_path="/repo",
        model="opus",
        delivery_id=DELIVERY_ID,
    )

    assert "Task accepted" not in output, "неизвестный исход напечатан как приёмка"
    assert "UNKNOWN" in output
    assert DELIVERY_ID in output
