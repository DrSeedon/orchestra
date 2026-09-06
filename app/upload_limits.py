"""Shared limits for files uploaded to Telegram.

Потолок задаёт ЛОКАЛЬНЫЙ сервер Bot API (`telegram-bot-api --local`), а не облачный:
он снимает штатные 50 МБ на отправку и 20 МБ на скачивание и позволяет 2000 МБ.
Прежние 50 МБ были нашей собственной планкой в 40 раз ниже возможностей и резали
обе стороны — и приём от владельца, и отправку ему (решение владельца 06.09.2026).
"""

MAX_UPLOAD_MB = 2000
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
PHOTO_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})
