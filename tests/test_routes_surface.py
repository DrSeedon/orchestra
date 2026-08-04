"""Guard: изменения HTTP-поверхности должны быть осознанными, а не побочными.

Обход РЕКУРСИВНЫЙ. Starlette 1.3 перестал расплющивать маршруты в ``app.routes``:
``include_router`` кладёт туда объекты-обёртки, у которых нет ``.methods``. Плоский обход на
такой версии видит 4 маршрута вместо 93, снапшот сходится сам с собой и guard молча умирает —
худший вид зелёного теста. Поэтому спускаемся во вложенные ``.routes`` и требуем, чтобы
маршруты нашлись.
"""

import json
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "route_surface_snapshot.json"

# `/api/blobs/{session_id}/{sha}` в снапшоте есть, но ЗАПИСЬ блобов выключена (#78
# заморожен, клиентской половины нет — фронт не знает типа `blob`). Роут инертен: ссылок
# на блобы в журнале не появляется. Комментарий живёт здесь, а не рядом со строкой в
# снапшоте, потому что тот файл — JSON и комментариев не держит.

# Ниже этого числа поверхность физически быть не может: столько маршрутов даёт один только
# FastAPI под автодоки. Порог ловит обход, который "успешно" не нашёл ничего.
_MIN_PLAUSIBLE_ROUTES = 20


def _collect(routes, seen=None):
    """Собрать (path, methods) со всех уровней вложенности."""
    if seen is None:
        seen = set()
    found = []
    for route in routes:
        if id(route) in seen:  # защита от циклической вложенности
            continue
        seen.add(id(route))
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods and path:
            found.append((path, tuple(sorted(methods))))
        # ``routes`` — Mount и старые версии; ``original_router`` — обёртка _IncludedRouter
        # из starlette 1.3+. Проверяем оба: имя атрибута менялось между версиями.
        for attr in ("routes", "original_router"):
            nested = getattr(route, attr, None)
            if nested is None:
                continue
            nested_routes = getattr(nested, "routes", nested)
            if nested_routes is not None and not isinstance(nested_routes, (str, bytes)):
                found.extend(_collect(nested_routes, seen))
    return found


def route_surface():
    from app.main import app
    return sorted(set(_collect(app.routes)))


def test_route_surface_is_discoverable():
    """Обход должен НАХОДИТЬ маршруты — иначе снапшот-тест бесполезен."""
    surface = route_surface()
    assert len(surface) >= _MIN_PLAUSIBLE_ROUTES, (
        f"обход нашёл всего {len(surface)} маршрутов — почти наверняка сломался сам обход, "
        "а не поверхность. Проверь, как текущая версия starlette хранит вложенные роутеры"
    )


def test_route_surface_snapshot():
    surface = route_surface()
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(surface, indent=1, ensure_ascii=False))
    expected = [(path, tuple(methods)) for path, methods in json.loads(SNAPSHOT.read_text())]
    added = sorted(set(surface) - set(expected))
    removed = sorted(set(expected) - set(surface))
    assert surface == expected, (
        "HTTP-поверхность разошлась со снапшотом.\n"
        f"  добавлено: {added or '—'}\n"
        f"  удалено:   {removed or '—'}\n"
        "Если изменение намеренное — обнови tests/route_surface_snapshot.json тем же коммитом."
    )
