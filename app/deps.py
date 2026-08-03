"""Shared dependencies for routers — avoids importing from main."""

import hashlib
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


_BUILD_GLOBS = ("js/*.js", "css/style.css")


def build_id() -> str:
    """Версия фронта целиком — та же mtime-механика, что у static_url().

    Нужна, чтобы страница поняла, что бэкенд уехал вперёд, и сказала об этом вслух.
    Считается на КАЖДЫЙ вызов, а не кешируется на импорте: сценарий, ради которого
    она существует, — мерж без рестарта, когда файл на диске сменился, а процесс живой.
    С кешем сигнал промолчал бы ровно в единственном случае, где он нужен. Цена —
    stat нескольких файлов, зовётся раз в 3 с из heartbeat.

    Вендорные библиотеки не берём: они меняются раз в месяцы и вручную, и такая
    правка всё равно приезжает вместе с рестартом.

    Хеш от пар «имя: mtime», а не max(mtime): максимум ловит только «что-то стало
    новее» и слеп к удалению файла и к откату на более старую версию. Разница в две
    строки, а слепое пятно исчезает целиком.
    """
    parts = sorted(f"{p.name}:{p.stat().st_mtime_ns}"
                   for pattern in _BUILD_GLOBS for p in _STATIC_DIR.glob(pattern))
    if not parts:
        return "0"
    return hashlib.blake2s("|".join(parts).encode(), digest_size=8).hexdigest()


templates.env.globals["static_url"] = static_url
templates.env.globals["build_id"] = build_id
