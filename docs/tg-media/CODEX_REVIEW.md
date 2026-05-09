## Tests
Тесты не применимо (план).

## Summary
План покрывает базовые одиночные photo/document/video/audio/sticker/voice/video_note, но не переносит несколько критичных деталей из kesha reference. В текущем `app/tg_bridge.py` простое добавление media handlers может вообще не сработать из-за уже зарегистрированного общего group-handler. Самый рискованный участок — сохранение пользовательских файлов в публично смонтированный `data/uploads/` с оригинальными именами и отдельным `file_unique_id` cache, который конфликтует с текущим md5 upload-flow. Также план переоценивает возможность "Claude reads file" для Orchestra: текущий pipeline отправляет только текст, а базовый prompt прямо запрещает читать binary files.

## Замечания
blocking: Существующий `@dp.message(F.chat.type.in_({"group", "supergroup"}))` матчится на любые group/supergroup сообщения, включая медиа, а aiogram останавливает propagation на первом совпавшем handler. Если media handlers добавить ниже, они будут недостижимы. Фикс: сузить текущий handler до `F.text & F.chat.type.in_(...)`, либо вынести общий resolve topic/session в функцию и зарегистрировать media handlers раньше catch-all.

blocking: В плане нет media group/album handling, хотя kesha использует `@media_group_handler` и регистрирует `F.media_group_id` до `F.photo`. Без этого альбом из нескольких photo/video/document/audio уйдет несколькими независимыми сообщениями, caption может продублироваться или потеряться, порядок вложений будет нестабилен. Фикс: добавить отдельный album handler, собрать все tags в один prompt и взять caption один раз, как в reference.

blocking: Формулировка "Claude reads the file via Read tool — supports images natively" конфликтует с текущим Orchestra contract: `AgentSession.send()` передает только текст, а `app/prompts/base.md` говорит `Never Read binary files`. В результате `[photo: /path]` не гарантирует анализа изображения и может даже инструктировать агента не делать нужное действие. Фикс: явно изменить system prompt/agent contract для image paths или реализовать другой путь доставки медиа, а не считать текстовый path нативным multimodal input.

blocking: `data/uploads/` уже смонтирован наружу через `/uploads`, поэтому TG documents/video/audio из приватной группы станут публично доступными по угадываемому имени файла. План еще и предлагает сохранять original filename, что открывает риски утечки имен, collision, странных расширений и path traversal, если не сделать sanitization. Фикс: хранить TG media в отдельной private директории либо генерировать opaque hash names, всегда применять `Path(name).name`, allowlist/normalize extensions, ограничить MIME/size и не монтировать произвольные документы как static.

blocking: Cache strategy не согласована с существующим md5 upload-flow. Paste upload дедуплицирует по md5 содержимого, а план кеширует по `file_unique_id` и сохраняет `data/uploads/{filename}`; при одинаковых filenames возможны overwrite/collision, а "reuse md5 dedup" из Edge cases фактически не реализован. Фикс: после download считать md5 и сохранять как `{md5}{ext}`, а `.media_cache.json` пусть мапит `file_unique_id -> md5 path`; запись cache делать атомарно.

blocking: TG Bot API limit описан слишком поверхностно. Нужно не просто "File > 20MB -> skip", а до `get_file/download_file` проверять `file_size` там, где он есть, и отдельно обрабатывать отсутствующий `file_path`, `TelegramBadRequest`, network timeout и download errors. Фикс: вернуть пользователю понятный tag вроде `[document: файл слишком большой (...)]`, не писать битый cache entry и не пытаться скачать файл, который Bot API не отдаст.

blocking: Deepgram error handling в плане недостаточен. 401/403 bad key, 429 rate limit, 413 payload too large, timeout, non-JSON body, пустой transcript и неожиданный shape `results.channels[0].alternatives` должны различаться в логах и не кешироваться как успешная транскрипция. Фикс: проверять HTTP status до JSON parse, логировать короткий raw body, cache only non-empty transcript, fallback to path-only только для recoverable ошибок.

suggestion: План теряет Telegram entity URLs в captions. Kesha использует `extract_caption_with_urls`, иначе caption с inline-ссылкой приходит агенту без URL или с неполным текстом. Фикс: добавить аналогичный helper для `msg.caption_entities` и использовать его во всех media handlers.

suggestion: Зависимости и config не описаны достаточно точно для Orchestra. В `pyproject.toml` нет прямого `aiohttp`, а `.env.example` не содержит `DEEPGRAM_API_KEY`; полагаться на transitive aiogram dependency не стоит. Фикс: либо использовать уже заявленный `httpx`, либо добавить прямую зависимость, плюс обновить `.env.example` и имя env var в коде.

suggestion: Нет плана cleanup/quota для TG media. `data/uploads/` сейчас имеет только 10MB per-file limit в web upload endpoint, но не имеет общей квоты/TTL, а TG bridge может накопить video/audio/documents быстро. Фикс: добавить periodic cleanup с total size cap, не удалять файлы, на которые еще ссылается cache, и чистить stale cache entries после удаления.

## Вердикт
План нельзя принимать как есть: сначала нужно закрыть routing, album handling, private storage/cache и реальный contract доставки медиа агенту.
