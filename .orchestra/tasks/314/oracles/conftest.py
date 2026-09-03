"""Изоляция БД для оракулов #314.

Оракулы лежат под `docs/`, а не под `tests/`, поэтому `tests/conftest.py` на них НЕ
распространяется — и вместе с ним не распространяется autouse-гард
`_isolate_production_db`. Обнаружено при реализации: `record_runway_decision` из оракула T6
писал в `data/orchestra.db` рабочего дерева, и строки копились между прогонами (46 штук),
из-за чего `assert len(rows) == 1` падал по причине, не имеющей отношения к предмету теста.

Боевая БД (`/home/kesha/orchestra/data/orchestra.db`) при этом не пострадала: она лежит в
ГЛАВНОМ чекауте, а `_DEFAULT_DB_PATH` резолвится от файла модуля, то есть внутри worktree.
Но полагаться на это нельзя — у оракулов, запущенных из главного чекаута, повезло бы меньше.
"""

import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path):
    """Своя пустая БД на КАЖДЫЙ тест: иначе счётные ассерты ловят чужие строки."""
    from app import db

    isolated = tmp_path / "orchestra.db"
    production = db._DEFAULT_DB_PATH.resolve()
    real_connect = sqlite3.connect

    def guarded(target, *args, **kwargs):
        if str(target) not in ("", ":memory:") and str(target) == str(production):
            raise AssertionError(
                f"оракул попытался открыть БД вне изоляции: {target}"
            )
        return real_connect(target, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "DB_PATH", isolated)
        patch.setenv("ORCHESTRA_DB_PATH", str(isolated))
        patch.setattr(sqlite3, "connect", guarded)
        yield
