"""У просматриваемого файла в списке отправки есть кнопка «Открыть».

28.08.2026: агент прислал `kiosk-flow-real.html` вместе с картинкой, и у HTML была только
кнопка скачивания — интерактивную карту приходилось сохранять на диск и открывать руками.
"""

import pathlib
import re

import pytest

APP_JS = pathlib.Path("app/static/js/app.js")


def _pattern() -> re.Pattern:
    source = APP_JS.read_text(encoding="utf-8")
    raw = re.search(r"const _SEND_FILE_OPENABLE = /(.+?)/i;", source)
    assert raw, "паттерн просматриваемых файлов должен существовать"
    return re.compile(raw.group(1).replace("\\\\", "\\"), re.I)


@pytest.mark.parametrize("path", [
    "/a/kiosk-flow-real.html", "/a/report.pdf", "/a/notes.md",
    "/a/data.json", "/a/rows.csv", "/a/run.log", "/a/conf.yaml",
])
def test_viewable_files_get_the_open_button(path):
    assert _pattern().search(path), f"{path} браузер показывает — кнопка «Открыть» обязана быть"


@pytest.mark.parametrize("path", [
    "/a/shot.png", "/a/photo.jpeg", "/a/clip.webp",   # у картинок уже есть лайтбокс
    "/a/arc.zip", "/a/voice.wav", "/a/bin.exe",       # браузер их всё равно скачает
])
def test_non_viewable_files_do_not_get_a_fake_button(path):
    assert not _pattern().search(path), (
        f"{path} браузер не покажет — кнопка обманывала бы пользователя"
    )


def test_open_does_not_pass_the_download_flag():
    """`download=1` заставляет браузер СОХРАНЯТЬ — с ним кнопка «Открыть» бесполезна."""
    source = APP_JS.read_text(encoding="utf-8")
    body = source[source.index("function _openSendFile"):source.index("function _downloadSendFile")]

    assert "_sendFileRawUrl(path)" in body
    assert "true" not in body.split("_sendFileRawUrl(path")[1][:20]


def test_download_button_is_kept_next_to_open():
    """Открытие не заменяет скачивание: файл всё ещё нужно уметь сохранить."""
    source = APP_JS.read_text(encoding="utf-8")
    block = source[source.index("_SEND_FILE_OPENABLE.test(path)"):]

    assert "🔗 Открыть" in block[:400]
    assert "📥 Download" in block[:600]
