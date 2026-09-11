"""Shared limits for files uploaded to Telegram.

Потолок ДОКУМЕНТА задаёт ЛОКАЛЬНЫЙ сервер Bot API (`telegram-bot-api --local`),
а не облачный: он снимает штатные 50 МБ на отправку и 20 МБ на скачивание и
позволяет 2000 МБ. Прежние 50 МБ были нашей собственной планкой в 40 раз ниже
возможностей и резали обе стороны — и приём от владельца, и отправку ему
(решение владельца 06.09.2026). Замер 11.09.2026 (#V-544): документ 209 715 200
байт ушёл через наш `localhost:8081` за 18.8 с, HTTP 200 — то есть 200 МБ
проходят; выше не проверялось.

Потолок ФОТО держит сам Telegram, и локальный сервер его НЕ поднимает: свыше
10 485 760 байт приходит `Bad Request: file of size N bytes is too big for a
photo`. В альбоме этот отказ валит ВСЮ группу, поэтому тяжёлую картинку мы
отправляем документом, а не фотографией.
"""

from pathlib import Path

MAX_UPLOAD_MB = 2000
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})


def send_as_photo(name: str, size_bytes: int, as_document: bool) -> bool:
    """Отправлять ли это вложение фотографией: решает и расширение, и размер."""
    if as_document or size_bytes > MAX_PHOTO_BYTES:
        return False
    return Path(name).suffix.lower() in PHOTO_EXTENSIONS
