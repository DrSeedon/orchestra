"""#78 — тела картинок живут файлами, журнал хранит ссылку.

Замер: 52 самые тяжёлые строки `logs` держали 43.6% всех байт журнала, и все они —
результаты `Read` с картинкой в base64. Ссылаться на исходный файл нельзя: рабочие копии
воркеров штатно сносятся после мержа, и файл был жив только у 32 из 50 строк. Поэтому в
хранилище кладутся БАЙТЫ, декодированные из самой строки, — тогда судьба рабочей копии
ни на что не влияет.

Уборка: блоб живёт ровно столько, сколько его строка. Политики удаления по возрасту НЕТ —
`agent history is research data, never delete it` (`db.py:1192`) сильнее экономии диска.
"""
import base64
import hashlib
import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BLOB_ROOT = Path(__file__).resolve().parent.parent / "data" / "blobs"

# Форма из живой БД: python-repr словаря, БЕЗ префикса `data:image`. Искать по форме
# «data:image» бесполезно — такой строки в этой базе нет ни одной (замер #78).
_SOURCE = re.compile(
    r"\{'type': 'base64', 'data': '([A-Za-z0-9+/=\s]+)'"
    r"(?:, 'media_type': '([^']+)')?\}"
)
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def session_dir(session_id: str) -> Path:
    return BLOB_ROOT / session_id


def blob_path(session_id: str, sha: str, media_type: str = "") -> Path:
    return session_dir(session_id) / f"{sha}.{_EXT.get(media_type, 'bin')}"


def store_images(session_id: str, content: str) -> str:
    """Вынести тела картинок в файлы, вернуть строку со ссылками.

    Сбой хранилища НЕ теряет данные: возвращается исходное содержимое, и это осознанный
    приоритет — картинка важнее экономии, а путь записи журнала ломать нельзя.
    """
    if "'type': 'base64'" not in content:
        return content

    def swap(match: re.Match) -> str:
        payload, media_type = match.group(1), match.group(2) or ""
        try:
            raw = base64.b64decode(payload, validate=False)
            sha = hashlib.sha256(raw).hexdigest()
            path = blob_path(session_id, sha, media_type)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(raw)
                tmp.replace(path)
        except Exception as error:
            logger.warning("blob store failed for session %s: %s: %s",
                           session_id, type(error).__name__, error)
            return match.group(0)
        media = f", 'media_type': '{media_type}'" if media_type else ""
        return (f"{{'type': 'blob', 'blob': '{sha}', 'bytes': {len(raw)}{media}}}")

    return _SOURCE.sub(swap, content)


def remove_session_blobs(session_id: str) -> int:
    """Блоб не переживает свою строку: сессию удалили — её блобы уходят тем же действием."""
    directory = session_dir(session_id)
    if not directory.is_dir():
        return 0
    count = len(list(directory.glob("*")))
    shutil.rmtree(directory, ignore_errors=True)
    return count


def inventory() -> dict:
    """Что лежит в хранилище и что с ним не сходится — ОБЕ стороны расхождения.

    Односторонняя проверка слепа ровно в ту сторону, где теряются данные: блоб без строки
    это мусор, а строка без блоба — дыра в истории.
    """
    from app.db import _conn

    on_disk: dict[str, list[str]] = {}
    total_bytes = 0
    if BLOB_ROOT.is_dir():
        for session_path in BLOB_ROOT.iterdir():
            if not session_path.is_dir():
                continue
            names = []
            for blob in session_path.glob("*"):
                names.append(blob.stem)
                total_bytes += blob.stat().st_size
            on_disk[session_path.name] = names

    referenced: dict[str, set[str]] = {}
    with _conn() as c:
        rows = c.execute(
            "SELECT session_id, content FROM logs WHERE content LIKE '%''type'': ''blob''%'"
        ).fetchall()
    for row in rows:
        for sha in re.findall(r"'blob': '([0-9a-f]{64})'", row["content"]):
            referenced.setdefault(row["session_id"], set()).add(sha)

    orphan_blobs = [(sid, sha) for sid, shas in on_disk.items()
                    for sha in shas if sha not in referenced.get(sid, set())]
    missing_blobs = [(sid, sha) for sid, shas in referenced.items()
                     for sha in shas if sha not in set(on_disk.get(sid, []))]
    return {
        "sessions": len(on_disk),
        "blobs": sum(len(v) for v in on_disk.values()),
        "bytes": total_bytes,
        "orphan_blobs": orphan_blobs,      # файл есть, строки нет — мусор
        "missing_blobs": missing_blobs,    # строка есть, файла нет — дыра
    }
