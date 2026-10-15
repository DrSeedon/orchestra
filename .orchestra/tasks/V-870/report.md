# V-870 — duration для chunked WebM

## Воспроизведение

Фикстура `tests/fixtures/dashboard_voice_chunked.webm` записана Chromium 148.0.7778.96 через `MediaRecorder` с `audio/webm;codecs=opus` и `start(1000)`: четыре MediaRecorder чанка по 4,162, 8,278, 8,278 и 3,417 байт (всего 24,135). Это реальный WebM-контейнер/поток MediaRecorder, записанный с включённым Chromium fake-device input для воспроизводимости. До исправления ffprobe завершался с кодом 0, но возвращал `N/A`; `_audio_duration_seconds` поднимал `ValueError: invalid audio duration`, и `/api/transcribe` отвечал 400. Сам ffmpeg декодировал этот файл и показывал 3.43 секунды.

## Исправление и проверка

`_audio_duration_seconds` сохраняет быстрый ffprobe-путь. Если форматная длительность отсутствует или не является конечным положительным числом, fallback декодирует аудио через ffmpeg с `-progress pipe:1`, берёт финальный `out_time_us`, ограничивает процесс тем же таймаутом в 10 секунд и проверяет положительную длительность. Далее действуют прежние пределы типа, размера и пяти минут; транскрипция идёт по существующему пути.

Зафиксированный до исправления тест `test_transcribe_route_accepts_chromium_chunked_webm` краснел на `float('N/A')` → `ValueError: invalid audio duration`. После исправления: тест WebM **1 passed**; `uv run --frozen python -m pytest tests/test_voice_input.py -q`: **7 passed in 5.98 s**. Тест отправляет реальную fixture в `/api/transcribe` с подменённым Deepgram, проверяет ответ 200, сохранность байтов и параметры агента/scope.

Правка находится в Python `app/routes/tg.py`; для живого процесса потребуется рестарт Orchestra. Рестарт не выполнялся.
