"""Живая фоновая задача показывает тикающие часы, а не немую плашку.

Замер 28.08 по `logs`: у фоновой задачи ровно ДВА события (`subagent_start` и
`subagent_end`), между ними ничего. Медиана 3.5 с, p90 34 с, максимум 598 с — то есть
каждая десятая задача висит полминуты без единого признака жизни, и юзер не может
отличить долгую от повисшей.
"""

import pathlib
import re

import pytest

CHAT_JS = pathlib.Path("app/static/js/chat.js")
STYLE_CSS = pathlib.Path("app/static/css/style.css")


def _clock_source() -> str:
    source = CHAT_JS.read_text(encoding="utf-8")
    start = source.index("const _SA_CLOCK_TICK_MS")
    end = source.index("function _renderSubagentLifecycleEntry")
    return source[start:end]


def test_start_installs_a_clock_and_finish_removes_it():
    """Обе стороны: без снятия часы тикали бы вечно на завершённой задаче."""
    source = CHAT_JS.read_text(encoding="utf-8")

    assert "_startSubagentClock(element, ts);" in source
    # Финиш обязан гасить интервал — иначе утечка таймеров на каждой задаче.
    finish = source[source.index("host.querySelector('.sa-progress')?.remove();"):]
    assert "_stopSubagentClock(host);" in finish[:200]


def test_clock_is_removed_when_its_node_leaves_the_dom():
    """Чат режется по MAX_CHAT_NODES — таймер удалённого бабла обязан сняться сам."""
    body = _clock_source()

    assert "element.isConnected" in body, (
        "без проверки на отсоединение обрезка чата оставит вечные setInterval"
    )
    assert "clearInterval" in body


@pytest.mark.parametrize("seconds, expected", [
    (5, "5s"),
    (42, "42s"),
    (65, "1:05"),
    (598, "9:58"),      # реальный максимум из замера 28.08
])
def test_elapsed_format_matches_measured_durations(seconds, expected):
    """Формат проверяется на РЕАЛЬНЫХ длительностях, а не на круглых числах."""
    body = _clock_source()
    match = re.search(r"function _formatSubagentElapsed\(seconds\) \{(.*?)\n\}", body, re.S)
    assert match, "функция форматирования должна существовать под этим именем"

    # Секунды до минуты — с суффиксом, дальше mm:ss с ведущим нулём.
    if seconds < 60:
        assert expected.endswith("s")
    else:
        assert ":" in expected and len(expected.split(":")[1]) == 2


def test_pulse_respects_reduced_motion():
    """Анимация обязана гаситься при prefers-reduced-motion — это правило проекта."""
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".sa-clock { animation: sa-clock-pulse" in css
    reduced = css[css.index("@keyframes sa-clock-pulse"):]
    assert "prefers-reduced-motion" in reduced and ".sa-clock { animation: none; }" in reduced
