"""Guard: прод-зависимости не обновляются молча.

История (#139): на машине юзера глобальный `~/.config/uv/uv.toml` держит
`exclude-newer = "7 days"` — СКОЛЬЗЯЩИЙ барьер. Любой `uv run` пере-резолвил зависимости под
уползающее окно, переписывал `uv.lock` на ~800 строк и подтягивал свежие версии. Так в
окружение приехал starlette 1.3.1 (в локе — 1.1.0) и уронил `test_routes_surface`, хотя код
никто не трогал. Грязный `uv.lock` при этом блокировал мержи всей очереди.

Эти тесты ловят обе половины: барьер должен быть фиксированным, а установленное окружение —
совпадать с локом.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "uv.lock"


def _lock_version(package: str) -> str | None:
    """Версия пакета, как её пинит uv.lock."""
    text = LOCK.read_text()
    match = re.search(
        rf'^\[\[package\]\]\nname = "{re.escape(package)}"\nversion = "([^"]+)"',
        text,
        re.MULTILINE,
    )
    return match.group(1) if match else None


def test_exclude_newer_is_fixed_not_sliding():
    """Барьер в проекте — конкретная дата, а не окно вида "7 days"."""
    config = tomllib.loads(PYPROJECT.read_text())
    barrier = config.get("tool", {}).get("uv", {}).get("exclude-newer")
    assert barrier, (
        "в [tool.uv] нет exclude-newer — проект унаследует глобальный скользящий барьер "
        "и зависимости начнут обновляться сами по расписанию"
    )
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?", barrier), (
        f"exclude-newer = {barrier!r} — это не фиксированная дата. Скользящие значения "
        '("7 days", "P7D") впускают новые версии молча'
    )


def test_lock_records_the_same_barrier():
    """Барьер обязан быть и в локе тоже.

    Именно снятие `[options]` из `uv.lock` (коммит 88a3a84) и открыло дорогу дрейфу: uv видит
    проектный барьер как "addition of global exclude newer", считает лок устаревшим и
    пере-резолвит всё дерево при обычном `uv run`.
    """
    config = tomllib.loads(PYPROJECT.read_text())
    barrier = config["tool"]["uv"]["exclude-newer"]
    match = re.search(r'^\[options\]\nexclude-newer = "([^"]+)"', LOCK.read_text(), re.MULTILINE)
    assert match, (
        "в uv.lock нет блока [options] exclude-newer — при следующем `uv lock` пакеты "
        "обновятся молча (замер: ~40 пакетов, uvicorn 0.48 → 0.52.1)"
    )
    assert match.group(1) == barrier, (
        f"барьеры разошлись: pyproject={barrier}, uv.lock={match.group(1)}. "
        "Меняй дату в обоих файлах одним коммитом вместе с прогоном тестов"
    )


def test_installed_env_matches_lock():
    """Установленные версии совпадают с локом.

    Расхождение = окружение пере-резолвилось мимо `uv.lock`. Именно так starlette 1.3.1
    подменил залоченный 1.1.0 и сломал guard маршрутов на ровном месте.
    """
    mismatched = []
    for package, module in (("starlette", "starlette"), ("fastapi", "fastapi")):
        pinned = _lock_version(package)
        if pinned is None:
            continue
        installed = __import__(module).__version__
        if installed != pinned:
            mismatched.append(f"{package}: установлен {installed}, в локе {pinned}")
    assert not mismatched, (
        "окружение разошлось с uv.lock:\n  " + "\n  ".join(mismatched) + "\n"
        "Почини: `uv sync`. Если расхождение возвращается — проверь, что блок "
        "`[options] exclude-newer` жив И в `pyproject.toml`, И в `uv.lock`: без него uv "
        "пере-резолвит зависимости под глобальный скользящий барьер."
    )
