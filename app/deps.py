"""Shared dependencies for routers — avoids importing from main."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.manager import SessionManager

manager = SessionManager()
templates = Jinja2Templates(directory="app/templates")

_STATIC_DIR = Path(__file__).parent / "static"


def static_url(path: str) -> str:
    """Ссылка на статику с версией в query — только так браузер узнаёт о правке.

    Версия = mtime файла: изменился файл → изменился URL → браузер идёт за новым
    и без Ctrl-Shift-R. Не изменился → берёт из кеша вообще без запроса (immutable
    в main.py). Плата за mtime вместо хеша содержимого: git checkout, вернувший тот
    же байт-в-байт файл, всё равно обновит время и стоит одной лишней загрузки.
    Файла нет → отдаём путь как есть: видимый 404 честнее тихой подмены.
    """
    try:
        return f"/static/{path}?v={(_STATIC_DIR / path).stat().st_mtime_ns:x}"
    except OSError:
        return f"/static/{path}"


templates.env.globals["static_url"] = static_url
