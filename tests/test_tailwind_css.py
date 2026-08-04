"""Собранный Tailwind CSS обязан соответствовать текущим исходникам.

Play-CDN Tailwind генерировал правила по факту появления узлов в DOM и поэтому не мог
«отстать» от разметки. Статическая сборка может: добавил класс в шаблон или в JS, забыл
`bash scripts/build-tailwind.sh` — и вёрстка молча поехала у юзера, а не у тебя (#64).

Проверяем не «похож ли класс на утилиту» (угадывать грамматику Tailwind — плодить ложные
срабатывания на проектных классах вроде `pb-block`), а прогоняем ТОТ ЖЕ сборщик и сверяем
результат с закоммиченным файлом.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "app/static/css/vendor/tailwind.css"
TAILWIND = "tailwindcss@3.4.17"


def test_built_css_exists_and_is_not_a_stub():
    assert CSS.exists(), f"{CSS} нет — запусти bash scripts/build-tailwind.sh"
    assert CSS.stat().st_size > 5_000, "CSS подозрительно мал: сборка прошла впустую?"


def test_play_cdn_compiler_is_gone():
    """Возврат 407 КБ компилятора в браузер — регрессия #64, а не «починка стилей»."""
    assert not (ROOT / "app/static/css/vendor/tailwind.js").exists()
    dashboard = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    assert "vendor/tailwind.css" in dashboard
    assert "tailwind.config =" not in dashboard, "конфиг живёт в tailwind.config.js"


@pytest.mark.skipif(shutil.which("npx") is None, reason="npx недоступен — сборку не проверить")
def test_committed_css_matches_current_sources(tmp_path):
    """Пересборка из текущих исходников должна дать байт-в-байт закоммиченный файл."""
    out = tmp_path / "tailwind.css"
    proc = subprocess.run(
        ["npx", "--yes", TAILWIND, "-c", "tailwind.config.js",
         "-i", "app/static/css/tailwind.src.css", "-o", str(out), "--minify"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert out.read_text(encoding="utf-8") == CSS.read_text(encoding="utf-8"), (
        "собранный CSS разошёлся с закоммиченным — в исходниках появились или пропали "
        "классы. Почини запуском: bash scripts/build-tailwind.sh"
    )
