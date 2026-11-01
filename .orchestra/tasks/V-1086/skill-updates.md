# Integration required in the real video-artifact / explainer-craft skills

Root assigned the canonical skill edits to native worker **feat-video-sound, V-1088**.
Both requested sources are intentionally excluded from this hub copy by the `.codex` transfer guard;
the guard remains intact. This is prepared integration text for V-1088, not a claim that
an existing SKILL.md was read or updated here. The native worker should read the canonical
files and replace the old default/stress requirements while retaining unrelated instructions.

## Shared narration policy text

Озвучка по умолчанию — ElevenLabs `eleven_flash_v2_5` для RU и EN.
Голос по прямому выбору владельца: **Sergey - Rich, Engaging and Captivating**,
`XuEV9VY3VUASYgJVNBh0` (сохранённый My Voices). Root подтвердил поддержку Flash,
model character multiplier 0.5, `cost_discount_multiplier=1.0`,
`sharing.rate=1.0`, `financial_rewards_enabled=false` на 25.10.2026.
Не путать `token_cost_factor` с ценой символа. Голос для EN автоматически не менять.
Переопределение: `--voice ID`, затем `ELEVENLABS_VOICE_ID`, затем Sergey.
При смене голоса заново проверить отсутствие custom-rate надбавки; при смене тарифа
проверить текущие `model_rates`. Нет автоматической дорогой модели или другого платного провайдера.

Секрет только `ELEVENLABS_API_KEY` в environment/штатном корневом `.env`; не печатать,
не вставлять в сцену/код/настройки скилла/артефакты. Preview не нуждается в ключе.
Реальный API вызывается только для согласованной озвучки, не для тестов.
Установить проектные зависимости и ffmpeg; локальные TTS-модели для ElevenLabs не требуются.

Канонические команды из корня репозитория:

```bash
uv run --frozen python scripts/video_artifact/make.py scene.html --out artifacts/demo
uv run --frozen python scripts/video_artifact/make.py scene.py --out artifacts/demo --lang en
uv run --frozen python scripts/video_artifact/elevenlabs_tts.py --text 'Фраза.' --out artifacts/speech.wav
uv run --frozen python scripts/video_artifact/elevenlabs_tts.py --file narration.txt --out artifacts/speech.wav
```

Обычный текст, числа и латиница допустимы для ElevenLabs. Не размечать его Tera/RUAccent
`+`-стресс-маркерами и не требовать `<имя>.stress.txt` перед сборкой. Существующие такие
проверки/`--stress-only` оставить только для явно выбранных локальных Tera/Vosk.
`--tts-engine tera|vosk|kokoro` — явный локальный выбор, не fallback по ошибке ElevenLabs.

Время задаёт **реальный WAV**, не длина текста: сохранить текущий договор STEPS,
HTML `window.voice?.(STEPS)` и Manim `VIDEO_ARTIFACT_VOICE`/`VoiceScene`.
Речь декодируется из Starter-compatible `mp3_44100_128` в 48 kHz mono PCM WAV.
Явные паузы `[0.4]` (0.05–10 s) — локальная буквальная тишина без отправки маркеров API;
`hold` не ускоряется, LEAD/GAP масштабируются `--rate`. Сам ElevenLabs принимает
`--rate 0.7..1.2`; для видео настройки — `--tts-stability` и `--tts-similarity`.

Preview `--preview-step`/`--preview-range` не синтезирует и не грузит `.env`.
`--stills`/`--timing-only` озвучку синтезируют. `--check-only` использует готовый
совпадающий `<имя>.timing.json`, не пересоздаёт голос. Deepgram QA остаётся прежней
отдельной платной проверкой; `--no-check` её отключает.

Не удалять кеш между правками визуала: он зависит от model/voice/settings/language/text,
не от ключа. Прямой CLI умеет `--cache DIR`. После timeout/неопределённой отправки
не повторять POST: `.request.json` требует проверки результата у провайдера через Root.
Сохранённый `.mp3` позволяет повторить только декодирование без списания.
Не удалять uncertain marker автоматически и не подменять генерацию выдуманным сэмплом.

Подробный действующий контракт и ссылки на документацию:
`scripts/video_artifact/README.md`; реализация `elevenlabs_tts.py`.

## Acceptance for Root

- Remove obsolete claims that RU defaults to Tera and EN always goes to Kokoro.
- Remove unconditional stress-mark review requirements for ElevenLabs; retain local-only sections.
- Verify commands use the actual project root, not a stale private worker checkout path.
- Read both real SKILL.md files before editing, so their remaining workflow/QA instructions survive.
- Verify the final skill content references Sergey and Flash exactly, and never contains the API key.
