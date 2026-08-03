"""Скрипты дашборда живут в одной глобальной области — имена не должны сталкиваться.

Реальный случай: `usage.js` объявил `_fetchHistory(until)`, а `app.js` уже держал
`_fetchHistory(name, scope)` и грузится ПОЗЖЕ. Объявление app.js перекрыло чужое, и
панель истории usage молча показывала «Снимков ещё нет»: её собственная функция никогда
не вызывалась. Тесты обеих задач были зелёными — они грузят usage.js без app.js.
"""
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEMPLATE = ROOT / "app/templates/dashboard.html"
STATIC_JS = ROOT / "app/static/js"

_TOP_LEVEL = (
    re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.M),
    re.compile(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", re.M),
)


def _page_scripts() -> list[str]:
    """Порядок скриптов берём из шаблона, а не из списка в тесте: добавят файл — проверим и его."""
    names = re.findall(r"static_url\('(js/[^']+\.js)'\)", TEMPLATE.read_text())
    return [name.split("/", 1)[1] for name in names]


def test_no_global_name_is_declared_in_two_scripts():
    scripts = _page_scripts()
    assert len(scripts) >= 3, f"скрипты страницы не распознаны: {scripts}"

    owners = defaultdict(set)
    for name in scripts:
        source = (STATIC_JS / name).read_text()
        for pattern in _TOP_LEVEL:
            for match in pattern.finditer(source):
                owners[match.group(1)].add(name)

    collisions = {name: sorted(files) for name, files in owners.items() if len(files) > 1}
    assert not collisions, (
        "объявления перекрывают друг друга (побеждает файл, который грузится позже): "
        f"{collisions}"
    )
