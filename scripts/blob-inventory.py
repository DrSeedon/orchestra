"""#78 — что лежит в блоб-хранилище и что с ним не сходится. НИЧЕГО НЕ УДАЛЯЕТ.

Политики удаления по возрасту нет намеренно: `agent history is research data, never
delete it` (`app/db.py:1192`). Блоб уходит только вместе со своей сессией. Этот скрипт —
глаза для человека, а не автоматика: он показывает ОБЕ стороны расхождения, потому что
односторонняя проверка слепа ровно там, где теряются данные.

    uv run python scripts/blob-inventory.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.blobs import BLOB_ROOT, inventory  # noqa: E402


def main() -> int:
    try:
        data = inventory()
    except Exception as error:
        # Скрипт живёт в репозитории, а база — у сервиса. В чужом чекауте это нормально:
        # сказать прямо, а не вывалить traceback.
        print(f"не смог прочитать журнал: {type(error).__name__}: {error}")
        print("запускать там, где лежит рабочая data/orchestra.db (обычно /home/kesha/orchestra)")
        return 1
    mb = data["bytes"] / 1024 / 1024
    print(f"хранилище: {BLOB_ROOT}")
    print(f"сессий: {data['sessions']}, блобов: {data['blobs']}, объём: {mb:.1f} МБ\n")

    if data["orphan_blobs"]:
        print(f"МУСОР — файл есть, строки журнала нет ({len(data['orphan_blobs'])}):")
        for session_id, sha in data["orphan_blobs"][:20]:
            print(f"  {session_id}/{sha[:12]}…")
        print("  (обычно это сессия, удалённая мимо delete_session)\n")
    else:
        print("мусора нет: каждому файлу соответствует строка журнала\n")

    if data["missing_blobs"]:
        print(f"ДЫРЫ — строка ссылается на пропавший файл ({len(data['missing_blobs'])}):")
        for session_id, sha in data["missing_blobs"][:20]:
            print(f"  {session_id}/{sha[:12]}…")
        print("  (история потеряла картинку — это важнее мусора)\n")
    else:
        print("дыр нет: каждая ссылка ведёт в существующий файл\n")

    print("Скрипт ничего не удаляет. Решение — человеческое, по списку выше.")
    return 0


sys.exit(main())
