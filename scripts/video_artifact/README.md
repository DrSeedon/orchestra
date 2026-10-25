# Озвучка HTML, Manim и обычного текста

Канонический сборщик — `scripts/video_artifact/make.py`; общий синтез и прямой CLI —
`scripts/video_artifact/elevenlabs_tts.py`. HTML принимает длительности через
`window.voice?.(STEPS)`, Manim — через существующий `VIDEO_ARTIFACT_VOICE` в
`manim_voice.py`. Оба используют фактическую длину декодированных WAV.

По умолчанию для RU **и** EN: `eleven_flash_v2_5`, сохранённый голос владельца
**Sergey - Rich, Engaging and Captivating**, ID `XuEV9VY3VUASYgJVNBh0`.
Это выбор владельца от 25.10.2026, не результат прослушивания в этой задаче.
Для английского голос автоматически не меняется. `--voice ID` имеет приоритет
над `ELEVENLABS_VOICE_ID`, затем используется Sergey.

Root проверил в аккаунте поддержку TTS и `model_rates.character_cost_multiplier=0.5`,
`cost_discount_multiplier=1.0`. `token_cost_factor` не является ценой символа.
У Sergey подтверждены Flash fine-tuning, `sharing.rate=1.0` и
`financial_rewards_enabled=false`. Смена голоса требует отдельной проверки ставки:
у некоторых библиотечных голосов есть надбавка. Эти сведения об аккаунте получены
от Root; worker не читал секреты и не обращался к реальному API.

Установленные зависимости проекта (`uv sync --frozen`) и `ffmpeg` обязательны;
локальные TTS-модели для ElevenLabs не нужны. Секрет — только
`ELEVENLABS_API_KEY` в экспортированном environment или корневом `.env` проекта.
Загрузка `.env` ленивая, `override=False`, без поиска в домашнем каталоге/родителях.
Не передавай ключ аргументом CLI, не копируй его в сцену, кеш или отчёт.

```bash
uv run --frozen python scripts/video_artifact/make.py scene.html --out artifacts/demo
uv run --frozen python scripts/video_artifact/make.py scene.py --out artifacts/demo --lang en
uv run --frozen python scripts/video_artifact/elevenlabs_tts.py --text 'Проверка озвучки.' --out artifacts/speech.wav
uv run --frozen python scripts/video_artifact/elevenlabs_tts.py --file narration.txt --lang en --out artifacts/narration.wav
```

Это команды использования, **не выполненная live-проверка**. Прямой CLI пишет
PCM WAV (48 kHz, mono, signed 16-bit), даже при английском тексте сохраняет Sergey.
Параметры: `--rate 0.7..1.2`, `--stability 0..1`, `--similarity 0..1`;
у video CLI последние два называются `--tts-stability` и `--tts-similarity`.
Произвольный выбор дорогой модели не предоставляется.

Запрос использует `mp3_44100_128`, доступный Starter. Это **MP3**, а не PCM:
ffmpeg декодирует его в 48 kHz mono WAV и обрезает тишину на краях речевого сегмента.
PCM/WAV 44.1 kHz от API требуют Pro; MP3 192 kbps требует Creator.
[Контракт convert](https://elevenlabs.io/docs/api-reference/text-to-speech/convert).

В `say` для ElevenLabs допустим обычный RU/EN текст, числа и латиница.
Не нужны `+`-стресс-маркеры, RUAccent, Tera normalizer или `stress_ru.json`;
старые русские внутрисловные `+` и combining acute очищаются перед отправкой.
Пунктуационные паузы делает модель. Явные `[0.4]` (0.05–10 секунд)
реализованы локальными нулевыми PCM-сэмплами между сегментами и не отправляются API.
Их длина буквальная, `--rate` её не меняет. Существующие LEAD/GAP масштабируются
темпом, `hold` остаётся буквальным временем. Для беззвучного шага: `say: ""`, `hold > 0`.
Максимум — 40000 символов на речевой сегмент, отказ до отправки.

Кеш по умолчанию `<out>/.tts-cache` для видео, `<out parent>/.tts-cache` для прямого
CLI; у прямого CLI можно задать общий `--cache DIR`. Ключ включает модель, voice ID,
настройки, язык, текст, формат и версию обработки — **не API key**.
Повторяющиеся сегменты озвучиваются один раз, смена только паузы переиспользует речь.
Кеш защищён файловыми блокировками и атомарной записью. Старый локальный кеш остаётся.
Смена каталога кеша или его удаление может привести к новой платной генерации.

Перед POST сохраняется `<hash>.request.json`. При timeout/transport error/5xx,
неожиданном redirect или некорректном успешном ответе повторной отправки нет,
в том числе после нового запуска. Проверь результат/историю у провайдера через Root;
не удаляй marker автоматически. Если готовый результат можно восстановить — восстанови
его. Удаление marker после проверки и повторный запуск — отдельное сознательное решение
оператора; возможное повторное списание нельзя исключить по одному таймауту.
Принятый `<hash>.mp3` сохраняется **до** декодирования: сбой ffmpeg исправляется локально,
без нового POST. Ошибки auth/quota/voice access видны явно; тело ответа и ключ не печатаются.
Нет retry, смены модели/голоса или другого платного провайдера.

`--preview-step`/`--preview-range` работают без TTS, ключа и загрузки `.env`;
рендерер HTML/Manim всё ещё должен быть установлен. `--check-only` использует готовый
`<имя>.timing.json` и отказывает при несовпадении текста сцены, не генерируя речь повторно.
Платный Deepgram QA — прежняя отдельная опция существующего pipeline;
`--no-check` исключает этот запрос. `--stills` и `--timing-only` генерируют озвучку.

Локальные движки сохранены для явного выбора:
`--tts-engine tera --voice m1`, `--tts-engine vosk --speaker 1`,
`--tts-engine kokoro --lang en --voice af_heart`. Их окружения, модели и правила
стресс-разметки сохранены. Для ElevenLabs `--stress-only` отказывает с пояснением.

Справка: [Flash, 1 кредит за 2 символа](https://elevenlabs.io/blog/meet-flash),
[языки моделей](https://elevenlabs.io/docs/overview/models),
[надбавки библиотечных голосов](https://elevenlabs.io/docs/help-center/product/voices/voice-library/what-are-custom-rates-and-credit-multipliers).
Общие документы могут отставать от тарифа аккаунта: проверенные Root значения `model_rates`
приоритетнее исторических публикаций. Сэмпл голоса в этой задаче не создавался.
