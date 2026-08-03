"""Шаблон новый, процесс старый — страница обязана отрендериться, а не упасть в 500.

Jinja перечитывает шаблоны с диска (`auto_reload=True`), а Python живёт в памяти до
рестарта, который делает человек руками. Значит между мержем и рестартом НОВЫЙ шаблон
исполняется СТАРЫМ процессом, где нового глобала ещё нет. Голый `{{ static_url(...) }}`
в такой момент бросает `UndefinedError` → 500 на живом юзере, включая страницу логина.

Проверка воспроизводит окно, а не рассуждает о нём: рендерит шаблоны из репозитория
в окружении БЕЗ глобалов приложения и БЕЗ контекста роута. Незащищённый вызов такой
рендер не переживёт.
"""
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).parent.parent / "app/templates"


def _pages() -> list[str]:
    return sorted(path.name for path in TEMPLATES.glob("*.html"))


@pytest.mark.parametrize("name", _pages())
def test_template_survives_a_process_without_its_globals(name):
    """Худший случай окна: процесс не знает НИ ОДНОГО глобала приложения."""
    # Undefined по умолчанию, как в проде: `{{ var }}` даёт пустоту, а вызов и обращение
    # к атрибуту бросают. StrictUndefined здесь соврал бы — он ловит и то, что живёт.
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)

    try:
        env.get_template(name).render()
    except Exception as error:
        pytest.fail(
            f"{name} не пережил рендер без глобалов: {type(error).__name__}: {error}. "
            "Вызов глобала в шаблоне обязан идти через макрос из _globals.html "
            "с запасным значением — иначе окно между мержем и рестартом даёт 500."
        )


def test_the_check_covers_every_template_on_disk():
    """Страж бесполезен, если новый шаблон в него не попал."""
    assert set(_pages()) == {path.name for path in TEMPLATES.glob("*.html")}
    assert len(_pages()) >= 2, _pages()
