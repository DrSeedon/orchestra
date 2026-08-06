"""#167 дефект 1: ошибка обязана назвать себя.

Проверяем ПОВЕДЕНИЕ (какая строка уйдёт в журнал и в TG), а не форму вызова —
иначе тест сломается от следующего рефакторинга, ничего не поймав.
"""

import asyncio

import httpx
import pytest

from app.errtext import err_text


# Семейство, которое стрингуется в пустоту. Именно оно 06.08 дало юзеру в TG
# сообщение «❌ connect failed:», оборванное на двоеточии.
EMPTY_STR_EXCEPTIONS = [
    TimeoutError(),
    asyncio.TimeoutError(),
    asyncio.CancelledError(),
    httpx.ReadTimeout(""),
    httpx.ConnectTimeout(""),
    httpx.PoolTimeout(""),
    ConnectionResetError(),
    BrokenPipeError(),
]


@pytest.mark.parametrize("exc", EMPTY_STR_EXCEPTIONS, ids=lambda e: type(e).__name__)
def test_empty_exception_still_names_itself(exc):
    """Пустой str(exc) → печатается класс, и БЕЗ висячего двоеточия."""
    text = err_text(exc)

    assert text == type(exc).__name__
    assert text.strip(), "сообщение об ошибке не может быть пустым"
    assert not text.endswith(":"), "висячее двоеточие выглядит как обрезанная передача"


def test_details_are_kept_when_present():
    assert err_text(ValueError("boom")) == "ValueError: boom"


def test_whitespace_only_message_is_not_a_message():
    """`_bug_error` (одна из четырёх снесённых копий) печатал здесь 'ValueError: '."""
    assert err_text(ValueError("   ")) == "ValueError"


def test_class_is_never_printed_twice():
    """merge_operations печатал 'TimeoutError: TimeoutError' — класс шёл и в префикс,
    и фолбэком в `_text`."""
    text = err_text(TimeoutError())

    assert text.count("TimeoutError") == 1


def test_user_facing_line_from_the_incident():
    """Дословная строка, ушедшая юзеру в TG 06.08 14:58:54, больше не воспроизводится."""
    before = f"connect failed: {TimeoutError()}"
    after = f"connect failed: {err_text(TimeoutError())}"

    assert before == "connect failed: "  # что было
    assert after == "connect failed: TimeoutError"  # что стало


def test_single_owner_no_duplicate_helpers():
    """Копии правила снесены. Пятая копия хуже, чем было: следующий агент найдёт
    две и не поймёт, какая главная."""
    import app.mcp_stdio
    import app.routes.system

    assert not hasattr(app.mcp_stdio, "_exception_text")
    assert not hasattr(app.routes.system, "_bug_error")
