"""#219 T1 — барьер веера: N детей, ОДНО пробуждение родителя.

Эти тесты написаны ДО реализации и КРАСНЫ по замыслу (#210: оракул принадлежит
дорогой стороне, исполнитель не пишет себе приёмку).

Что барьер обязан делать и чего обязан НЕ делать — `.orchestra/tasks/219/plan.md`, T1.
Цена вопроса замерена трижды независимо: пробуждение родителя ≈$0.87 (#219),
$0.900241 и $0.756113 (#223) — 99 % токенов уходит на перечитывание контекста.
"""
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "fan.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    import app.db as _db
    _db.init_db()
    return _db


@pytest.fixture
def fan(db):
    import app.fan_barrier as fb
    fb.open_fan(
        fan_id="f1",
        parent_name="parent",
        scope="/repo",
        children=["c1", "c2", "c3"],
        deadline_seconds=3600,
    )
    return fb


# --- AC-1: снимается по ПОЛОЖИТЕЛЬНЫМ токенам, а не по тишине ----------------

def test_barrier_holds_until_every_child_has_a_terminal_token(fan):
    assert fan.should_buffer("c1") is True
    assert fan.record_terminal("c1", "done") is False, "снялся на первом ребёнке"
    assert fan.record_terminal("c2", "done") is False, "снялся на втором из трёх"
    assert fan.record_terminal("c3", "done") is True, "не снялся, когда все трое отчитались"


def test_silence_is_not_a_terminal_token(fan):
    """Грабля #189: «никто не активен» одинаково верно при «все закончили» и
    при «никто не начинал». Барьер обязан требовать положительный признак."""
    fan.record_terminal("c1", "done")
    assert fan.is_released("f1") is False
    # c2 и c3 просто молчат — ни одной записи о них
    assert fan.is_released("f1") is False, "барьер снялся по отсутствию активности"


def test_failed_and_killed_children_release_the_barrier(fan):
    """AC-2: упавший/убитый ребёнок порождает ТОКЕН, а не тишину, иначе веер
    висит до дедлайна при уже известном исходе."""
    fan.record_terminal("c1", "done")
    fan.record_terminal("c2", "failed")
    assert fan.record_terminal("c3", "killed") is True
    manifest = fan.manifest("f1")
    assert manifest["complete"] is True
    assert {m["child"]: m["state"] for m in manifest["members"]} == {
        "c1": "done", "c2": "failed", "c3": "killed",
    }


def test_kill_lifecycle_produces_the_killed_token(fan):
    """AC-2, источник токена. Гейт на `fire_auto_report` его породить НЕ может:
    `app/session_turns.py:266` возвращается раньше `on_idle` для
    `_manually_interrupted`. Значит производитель — kill/stop-путь."""
    fan.record_terminal("c1", "done")
    fan.record_terminal("c2", "done")
    assert fan.on_child_killed("c3") is True, "kill не породил терминальный токен"
    assert fan.manifest("f1")["complete"] is True


def test_double_terminal_token_is_idempotent(fan):
    """Цикл умеет переигрывать вход (#158): гасить надо после факта, и повтор
    не должен ни терять освобождение, ни выдавать его дважды."""
    fan.record_terminal("c1", "done")
    fan.record_terminal("c2", "done")
    assert fan.record_terminal("c3", "done") is True
    assert fan.record_terminal("c3", "done") is False, "второе освобождение на дубле"
    assert fan.manifest("f1")["complete"] is True


# --- AC-3: дедлайн, частичность ЯВНАЯ ---------------------------------------

def test_deadline_releases_with_explicit_partial_flag(db):
    import app.fan_barrier as fb
    fb.open_fan(fan_id="f2", parent_name="p", scope="/r",
                children=["a", "b"], deadline_seconds=-1)  # уже истёк
    fb.record_terminal("a", "done")
    released = fb.release_expired()
    assert "f2" in released
    m = fb.manifest("f2")
    assert m["complete"] is False, "частичный веер помечен как полный"
    assert m["partial_reason"] == "deadline"
    states = {x["child"]: x["state"] for x in m["members"]}
    assert states["a"] == "done"
    assert states["b"] == "timeout", "не отчитавшийся ребёнок обязан получить timeout"


# --- AC-4: исключения будят немедленно, машинным полем ----------------------

@pytest.mark.parametrize("kind", ["out_of_scope", "false_premise", "blocked"])
def test_exception_classes_bypass_the_barrier(fan, kind):
    assert fan.should_buffer("c1", message_kind=kind) is False, (
        f"класс {kind} обязан будить немедленно"
    )


@pytest.mark.parametrize("kind", ["done", "progress", "", None])
def test_ordinary_messages_are_buffered(fan, kind):
    assert fan.should_buffer("c1", message_kind=kind) is True, (
        f"обычное сообщение {kind!r} разбудило родителя мимо барьера"
    )


def test_unknown_message_kind_fails_closed_to_buffering(fan):
    """Неизвестное значение не должно открывать проход: ошибка ребёнка в поле
    деградирует в ожидание (безопасно), а не в лишнее пробуждение."""
    assert fan.should_buffer("c1", message_kind="whatever") is True


# --- Границы: кто НЕ подпадает под барьер -----------------------------------

def test_child_outside_any_fan_is_never_buffered(fan):
    assert fan.should_buffer("stranger") is False


def test_released_fan_stops_buffering(fan):
    for c in ("c1", "c2", "c3"):
        fan.record_terminal(c, "done")
    assert fan.should_buffer("c1") is False, "барьер продолжает держать после снятия"


def test_single_child_fan_degenerates_to_current_behaviour(db):
    """AC-7: веер из одного ребёнка = сегодняшнее поведение, одно пробуждение.
    Замер #223 показал это на живом прогоне: при одном ребёнке барьер не может
    опустить цену ниже одного приёмочного пробуждения."""
    import app.fan_barrier as fb
    fb.open_fan(fan_id="f3", parent_name="p", scope="/r",
                children=["solo"], deadline_seconds=3600)
    assert fb.record_terminal("solo", "done") is True


# --- Манифест: пути, а не тела ----------------------------------------------

def test_manifest_carries_paths_not_report_bodies(fan):
    """AC-5: при `cache_read` 99 % всё, что попало в контекст родителя,
    оплачивается заново на КАЖДОМ последующем ходу."""
    body = "x" * 5000
    fan.record_terminal("c1", "done", report_path="/w/c1/OUT.md", summary=body)
    fan.record_terminal("c2", "done", report_path="/w/c2/OUT.md")
    fan.record_terminal("c3", "done", report_path="/w/c3/OUT.md")
    text = fan.manifest_text("f1")
    assert "/w/c1/OUT.md" in text
    assert body not in text, "тело отчёта уехало в контекст родителя"
    assert len(text) < 2000, f"манифест раздут до {len(text)} символов"
