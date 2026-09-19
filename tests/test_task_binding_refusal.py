"""#V-603 — отказ привязки задачи называет причину и действие, а не внутреннюю механику.

Прежний текст `task #27 binding compare-and-swap failed` не отличал «задача занята» от
«строка изменилась» и не подсказывал выхода, поэтому вызывающий пробовал ещё раз тем же
способом. Неудачный спавн уносит весь текст задания (~1 500 токенов) и потом пересылается
в каждом ходе сессии — цена непонятной ошибки платится многократно.
"""
import sqlite3

import pytest

from app.db import _task_binding_refusal


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
    c.execute("CREATE TABLE tm_tasks (id TEXT PRIMARY KEY, par_number INTEGER, worker_session_id TEXT)")
    return c


def test_busy_task_names_the_holder_and_the_way_out(conn):
    conn.execute("INSERT INTO sessions VALUES ('s1', 'tz-review-1')")
    conn.execute("INSERT INTO tm_tasks VALUES ('t1', 27, 's1')")

    message = _task_binding_refusal(conn, {"id": "t1", "par_number": 27})

    assert "tz-review-1" in message, "не названа причина: кто держит задачу"
    assert "separate task" in message, "не названо действие"
    assert "compare-and-swap" not in message


def test_free_task_reports_a_revision_race_instead_of_a_fake_holder(conn):
    conn.execute("INSERT INTO tm_tasks VALUES ('t2', 31, NULL)")

    message = _task_binding_refusal(conn, {"id": "t2", "par_number": 31})

    assert "revision" in message
    assert "worker" not in message.split("revision")[0], "нельзя обвинять несуществующего держателя"


def test_missing_task_row_does_not_crash_the_refusal(conn):
    """Ошибка в пути ошибки — худший вид: агент получил бы трассу вместо причины."""
    message = _task_binding_refusal(conn, {"id": "gone", "par_number": 99})

    assert "#99" in message
