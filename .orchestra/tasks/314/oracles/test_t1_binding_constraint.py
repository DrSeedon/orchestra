"""T1 (#314): `QuotaDecision` называет ПРИЧИНУ, не меняя решения.

Замороженный RED-оракул гейта плана. Сегодня причина отказа лежит только в свободной строке
`reason`, поэтому панель не может отличить «отказал процент» от «закрыл дефицит» иначе как
разбором текста. Тикет добавляет дискриминатор `binding_constraint` и блок `runway`.

Оракул НЕ содержит чисел 34 / 34 / 9: они предмет вердикта ревьюера и живут в политике.
Проверяется только то, что причина названа машиночитаемо и доезжает до потребителя.
"""

from datetime import datetime, timedelta, timezone

from app.quota_gate import (
    CLAUDE_WORKER_WEEKLY_LIMIT_PCT,
    evaluate_worker_admission,
    quota_bucket_for_model,
    worker_readiness_envelope,
)

MODEL = "claude-opus-5[1m]"
NOW = 1_760_000_000.0


def _observation(utilization: float) -> tuple[dict, dict]:
    """Наблюдение провайдера ровно той формы, что приходит из `provider_usage`."""
    bucket = quota_bucket_for_model(MODEL)
    resets_at = (
        datetime.fromtimestamp(NOW, timezone.utc) + timedelta(days=3)
    ).isoformat()
    providers = {
        bucket: {
            "label": "Claude",
            "windows": [
                {
                    "id": "seven_day",
                    "window_minutes": 10080,
                    "utilization": utilization,
                    "resets_at": resets_at,
                }
            ],
        }
    }
    return providers, {bucket: NOW}


def _decision(utilization: float):
    providers, observed = _observation(utilization)
    return evaluate_worker_admission(MODEL, providers, observed, now=NOW)


def test_static_denial_names_percent():
    """Отказ по проценту обязан назвать себя `static_pct`, а не только текстом."""
    decision = _decision(CLAUDE_WORKER_WEEKLY_LIMIT_PCT + 1.0)
    assert decision.state == "blocked", "предпосылка теста: процент должен отказать"
    assert getattr(decision, "binding_constraint", None) == "static_pct"


def test_allowed_decision_names_no_constraint():
    """Пока ничто не связывает — `none`, а не пустая строка и не отсутствие поля.

    Отличать «ограничения нет» от «поля нет» обязана панель, поэтому значение явное.
    """
    decision = _decision(CLAUDE_WORKER_WEEKLY_LIMIT_PCT - 20.0)
    assert decision.allowed is True, "предпосылка теста: процент должен пустить"
    assert getattr(decision, "binding_constraint", None) == "none"


def test_decision_carries_runway_block():
    """Поле `runway` существует как отдельный блок, а не размазано по `reason`."""
    decision = _decision(CLAUDE_WORKER_WEEKLY_LIMIT_PCT - 20.0)
    assert hasattr(decision, "runway"), "у решения нет блока runway"


def test_envelope_carries_binding_constraint():
    """Причина доезжает до потребителя (панель читает envelope, не dataclass)."""
    envelope = worker_readiness_envelope(_decision(CLAUDE_WORKER_WEEKLY_LIMIT_PCT + 1.0))
    assert envelope.get("binding_constraint") == "static_pct"


def test_envelope_stays_backward_compatible():
    """Новые поля аддитивны: старый клиент не должен увидеть смену контракта.

    `wire_version` бампать нельзя — иначе pre-v1 клиенты (`worker_readiness_envelope`
    держит для них отдельную ветку) получат неожиданный контракт из-за косметики.
    """
    envelope = worker_readiness_envelope(_decision(CLAUDE_WORKER_WEEKLY_LIMIT_PCT + 1.0))
    assert envelope["wire_version"] == 2
    for field in ("policy", "state", "decision_state", "reason", "model", "provider"):
        assert field in envelope, f"поле {field} пропало из envelope"
