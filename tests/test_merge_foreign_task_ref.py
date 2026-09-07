"""#comfy 06.09: чужой номер задачи в сообщении коммита не должен валить мерж.

Репозиторий может нести собственную нумерацию (переехал с другой площадки). Тогда
`#110:` в сообщении — факт истории, а не ошибка вызывающего. Такой ref обязан остаться
в `canonical_refs` (тема squash-коммита сверяется с этим списком), но не привязываться.
"""

import pytest

from app import tm


@pytest.fixture()
def scope(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db", raising=False)
    from app.db import init_db
    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
    return "/scope"


def test_unknown_ref_is_skipped_not_fatal(scope):
    task = tm.create_task_for_scope(scope, title="настоящая")
    known = str(task["par_number"])

    res = tm.resolve_scoped_task_identities(scope, [known, "110"], skip_unknown=True)

    assert res["unresolved_refs"] == ["110"], "чужой номер обязан быть назван"
    assert "110" in res["canonical_refs"], "ref остаётся: по нему сверяется тема коммита"
    assert [t["par_number"] for t in res["tasks"]] == [task["par_number"]], \
        "привязывается только существующая задача"


def test_unknown_ref_first_in_list_is_also_skipped(scope):
    """Все коммиты ветки могут нести ТОЛЬКО чужой номер — тогда он идёт первым."""
    res = tm.resolve_scoped_task_identities(scope, ["110", "113"], skip_unknown=True)
    assert res["unresolved_refs"] == ["110", "113"]
    assert res["tasks"] == []


def test_strict_mode_still_refuses(scope):
    """Привязка задачи воркера остаётся строгой: тут неизвестный ref — настоящая ошибка."""
    with pytest.raises(ValueError, match="not found in session project"):
        tm.resolve_scoped_task_identities(scope, ["110"])
