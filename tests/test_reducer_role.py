"""#231 T4/T5 — роль `reducer`: права отняты ОТСУТСТВИЕМ тулов, а не текстом промпта.

Красные по замыслу до реализации. Вторая редакция: первую отвергло ревью плана
(`codex-review-plan.md`, blocking 4 и 5) — проверка «режим достижим по роли» проходила при
мёртвом хелпере, а список запретов был неполон.

Почему именно отсутствием тулов. Запрет в промпте не принуждается, и это замерено трижды за
одни сутки: #228 — `can_use_tool` не вызвался ни разу на `Bash(run_in_background=true)`;
#198 — `token_budget` превышен в 8 раз при прямой инструкции; #227 — прямой запрет модели не
сработал 1 из 1. Запрет ставится туда, где он физически исполняется:
`_tool_names_for_access_mode` (`app/mcp_stdio.py:270`) → `mcp.remove_tool` (`:283`).

Почему НЕ через `disallowed_tools` Claude: у Codex-бэкенда механизма запрета тулов нет вовсе
(грепом по `app/backend_codex.py` — ноль совпадений), и на Codex-редьюсере такой запрет молча
исчез бы. Фильтрация на стороне MCP-сервера работает на обоих бэкендах.
"""
import pytest


FORBIDDEN = {
    "spawn_worker", "merge_worker", "kill_worker", "stop_worker",
    "switch_worker_branch", "check_conflict", "update_worker_prompt",
    "change_worker_model", "compact_worker", "acquire_test_lock",
    "release_test_lock", "task_create", "task_update",
    "payment_receive", "payment_status", "resolve_merge_operation",
}
REQUIRED = {"send_message", "update_progress", "list_agents", "search_memory"}


def _mcp():
    import importlib
    try:
        return importlib.import_module("app.mcp_stdio")
    except ModuleNotFoundError as exc:
        pytest.fail(f"app.mcp_stdio не импортируется: {exc}")


def test_t4_reducer_mode_removes_lifecycle_tools():
    """Универсум намеренно содержит НЕИЗВЕСТНЫЙ мутатор (находка раунда 2, blocking 4).

    Реализация вида `names - FORBIDDEN` проходит проверку по рукотворному списку и
    пропускает любой тул, добавленный в проект завтра. Единственный контракт, который
    это ловит, — положительный вайтлист: что не разрешено явно, того у редьюсера нет.
    """
    m = _mcp()
    everything = FORBIDDEN | REQUIRED | {"tool_added_next_week"}
    try:
        visible = m._tool_names_for_access_mode(everything, "reducer")
    except ValueError as exc:
        pytest.fail(f"режима доступа 'reducer' не существует: {exc}")

    assert "tool_added_next_week" not in visible, (
        "неизвестный тул достался редьюсеру — набор строится вычитанием списка запретов, "
        "а обязан строиться положительным вайтлистом"
    )
    leaked = visible & FORBIDDEN
    assert not leaked, (
        f"редьюсеру оставлены тулы жизненного цикла: {sorted(leaked)} — "
        "запрет держится на промпте, а он не принуждается"
    )
    missing = REQUIRED - visible
    assert not missing, (
        f"у редьюсера отняли то, без чего он не работает: {sorted(missing)}"
    )


def test_t4_spawn_path_sets_reducer_mode():
    """Прод-путь, а не хелпер (#219): режим выставляет `_make_mcp_config` в `app/manager.py`,
    где сегодня жёстко стоит `"ORCHESTRA_ACCESS_MODE": "full"`. Отдельная функция-переходник,
    которую никто не зовёт, оставила бы набор тулов прежним и была бы зелёной."""
    import app.manager as mgr

    def _env(cfg):
        found = {}
        stack = [cfg]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if "ORCHESTRA_ACCESS_MODE" in cur:
                    found = cur
                    break
                stack.extend(cur.values())
        return found

    red = _env(mgr._make_mcp_config("r1", "/repo", role="reducer"))
    assert red.get("ORCHESTRA_ACCESS_MODE") == "reducer", (
        f"спавн редьюсера отдаёт режим {red.get('ORCHESTRA_ACCESS_MODE')!r} — "
        "фильтрация тулов не включится, запрет останется только в тексте"
    )
    assert red.get("ORCHESTRA_ROLE") == "reducer"

    plain = _env(mgr._make_mcp_config("w1", "/repo", role="worker"))
    assert plain.get("ORCHESTRA_ACCESS_MODE") == "full", (
        "обычный воркер потерял тулы — правка задела чужую роль"
    )


def test_t5_reducer_prompt_delivers_anchors():
    """DELIVERY-проверка: текст читает модель, а не тест.

    ВАЖНО, что этот тест НЕ несёт: полноту сводки. Ревью плана (blocking 8) справедливо
    показало, что «редьюсер забыл правило» означает «редьюсер сократил», то есть потерю
    отчётов. Полнота поэтому обеспечивается кодом и проверяется в
    `tests/test_fan_enable.py::test_t6_parent_payload_survives_a_silent_reducer`.
    Здесь — только доставка формулировок до модели.

    Якоря — ЦЕЛЬНЫЕ фразы (грабля #210: клаузы, выведенные из уже переформатированного файла,
    слепы к переносу строки внутри проверяемой фразы). И обязательна вторая половина: роль
    БЕЗ этого шага якорей содержать не должна, иначе тест зелен на любом промпте.
    """
    import app.pipeline as P

    anchors = ["отдаёт всё", "не выбирает главное", "не мержит"]
    try:
        out = P.build_system_prompt("default", "reducer")
    except Exception as exc:  # роли ещё нет — это и есть красный
        pytest.fail(f"роль reducer не собирается: {type(exc).__name__}: {exc}")

    missing = [a for a in anchors if a not in out]
    assert not missing, f"в промпте редьюсера нет якорей: {missing}"

    worker_out = P.build_system_prompt("default", "worker")
    leaked = [a for a in anchors if a in worker_out]
    assert not leaked, (
        f"якоря редьюсера протекли в роль worker: {leaked} — "
        "проверка перестала различать роли"
    )
