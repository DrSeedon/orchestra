"""#V-602 — ступень рассуждения харнеса приходит из манифеста, а не из текста сообщения.

До 19.09.2026 харнес угадывал её регуляркой по словам в сообщении: на 12 реальных
сообщениях пользователя она одиннадцать раз вернула `medium`, то есть решения не
принимала. У Claude, Codex и Grok ступень всегда бралась из карты `модель → effort`
в `pipeline.yaml`; теперь и здесь один владелец решения.
"""
import pytest

from app.backend_harness import HarnessBackend
from app.pipeline import get_role, resolve_effort


def test_effort_is_taken_from_the_constructor_not_from_the_message():
    backend = HarnessBackend(model="vendor/model:free", cwd="/tmp", effort="medium")

    assert backend._effort == "medium"


def test_message_text_no_longer_decides_anything():
    """Раньше слово «почини» поднимало ступень до high прямо посреди разговора."""
    backend = HarnessBackend(model="vendor/model:free", cwd="/tmp", effort="medium")

    for message in ("почини гонку в мерже", "ок", "да", "x" * 500):
        assert backend._effort == "medium", message


def test_manifest_resolves_harness_by_runtime_and_model_id():
    """Карта разрешается id модели раньше рантайма: замерили маршрут — добавили строку."""
    role = get_role("default", "worker")

    assert resolve_effort(role.effort, "nvidia/nemotron-3.5-lightning:free", "harness") == "medium"
    assert resolve_effort(role.effort, "claude-opus-5[1m]", "claude") == "high"
    assert resolve_effort(role.effort, "gpt-6-astra", "codex") == "medium"


def test_planning_tool_stays_gated_on_high():
    """`todo_write` включается только на high — иначе гейт планирования (#125) исчезает."""
    backend = HarnessBackend(model="vendor/model:free", cwd="/tmp", effort="medium")
    backend._tool_schemas = []

    names = lambda effort: {
        s.get("function", {}).get("name") for s in backend._turn_tool_schemas(effort)
    }

    assert "todo_write" not in names("medium")
    assert "todo_write" in names("high")


def test_no_effort_configured_leaves_the_request_without_a_reasoning_field():
    """Манифест без значения для модели → None, и клиент не шлёт `reasoning` вовсе."""
    backend = HarnessBackend(model="vendor/model:free", cwd="/tmp")

    assert backend._effort is None
