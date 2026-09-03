# Research — Deepgram voice transcription в Orchestra

Дата проверки: 2026-07-18. Фаза: Research + measurement. Секреты и идентификаторы Deepgram намеренно не записаны.

## Вывод

Orchestra уже использует лучший текущий baseline по цене и operational evidence для русских Telegram voice: прямой pre-recorded REST-запрос к `nova-3` с `language=ru`; превосходство по WER не доказано. В этой Orchestra repo и локальной Codex installation Deepgram MCP нет: Orchestra вызывает API из `app/tg_bridge.py`, а Codex использует отдельный skill/CLI. Codex-конфиг функциональнее для произвольных файлов, но его `language=multi` дороже и не является автоматическим улучшением для заведомо русских voice.

Стоимость voice внутри Orchestra **не отслеживается**. Локально пишутся длительность и latency, но не request ID, tag или USD; общий dashboard cost считает только LLM turns. Более того, Orchestra, Codex и VoiceType используют один Deepgram credential, а у запросов нет tags, поэтому Deepgram billing API показывает только общий проект, не источник.

По сохранённым аудиофайлам Orchestra: май — 113.675 мин ≈ **$0.489**, июнь — 58.500 мин ≈ **$0.252**, 1–18 июля — 17.852 мин ≈ **$0.077**. Текущий июльский темп — около **$0.13/месяц**. Весь общий Deepgram-проект заметно больше: $4.65 в мае, $8.07 в июне и $3.72 за 1–18 июля; это главным образом не Orchestra voice.

## Вопрос и критерий решения

- **Контекст:** Telegram voice/video notes в Orchestra и локальная транскрипция файлов через Codex.
- **Изменение под проверкой:** копировать ли Codex-конфиг или менять модель (`nova-2`, Whisper, multilingual).
- **Baseline:** текущий Orchestra `nova-3 + language=ru` через `/v1/listen`.
- **Измеримые исходы:** точный transport/параметры, наличие cost-метрики, минуты и billing USD, опубликованная цена за минуту, наблюдаемая надёжность/latency.
- **Ограничение:** качество распознавания (WER) не измерялось — нет human ground truth для сохранённых voice. Поэтому рекомендация модели опирается на поддержку языка, цену, текущую работоспособность и официальное назначение моделей, а не на выдуманное сравнение точности.

## Гипотезы и falsifiers

1. **H1: Orchestra уже учитывает Deepgram cost, потому что dashboard показывает USD.** Falsifier: `cost_usd` приходит только из LLM `ResultMessage`, а в voice path отсутствуют cost/request/tag writes. **REFUTED** [L4][L5].
2. **H2: в проверенной Codex installation есть более оптимизированный Deepgram MCP.** Falsifier: в локальных Codex MCP definitions нет Deepgram, а транскрипция реализована skill-скриптом. **REFUTED локально** [L6][L7][L8].
3. **H3: Nova-2 или Whisper дешевле/лучше для Orchestra voice.** Falsifier: русский monolingual поддерживается Nova-3, текущая pre-recorded цена Nova-3 ниже Whisper Large и legacy Nova-2 streaming, текущий path успешно работает. **REFUTED по цене/совместимости; UNCERTAIN по WER** [S1][S2][S3][M1].
4. **Альтернатива: `language=multi` улучшит русско-английский code-switching.** Это возможно, но стоит на 20.9% дороже (`$0.0052` против `$0.0043`/мин) и требует A/B на репрезентативных voice. **UNCERTAIN** [S1][S4].

## 1. Текущая конфигурация Orchestra

| Параметр | Фактическое значение | Доказательство |
|---|---|---|
| Интеграция | Прямой HTTP `POST https://api.deepgram.com/v1/listen`, не MCP | [L1] |
| Модель | `nova-3` | [L1] |
| Язык | `ru` (monolingual) | [L1] |
| Форматирование | `smart_format=true` | [L1] |
| Profanity | `profanity_filter=false` | [L1] |
| Content-Type | `audio/ogg` | [L1] |
| Сеть | `aiohttp.ClientSession(trust_env=False)`, отдельный CA context через `certifi`; env proxy игнорируется | [L1] |
| Timeout/retry | 120 секунд; до 3 попыток на сетевое исключение с backoff 1.5/3 сек | [L1] |
| Credential | `DEEPGRAM_API_KEY` из environment после `load_dotenv()`; systemd загружает project `.env` | [L2][L3] |
| Cache | JSON по Telegram `file_unique_id`; успешный непустой transcript не отправляется повторно | [L1] |
| Входы | Telegram voice `.oga`; video note конвертируется `ffmpeg` в Opus `.oga` | [L1] |
| MCP | Project `.mcp.json` содержит только Orchestra server | [L6] |

Credential существует в project/worktree/VoiceType env и текущем process env; проверка значений без вывода секрета показала, что все четыре значения идентичны и имеют длину 40 символов [M2]. В `.env.example` он объявлен optional [L3].

Прямой маршрут был выбран сознательно: commit `63b9c7a` фиксирует измерение 34 с через Hiddify против 3.8 с напрямую. В текущем retained journal 46 успешных запросов дали среднюю API latency 2428 мс, без строк retry/failure/parse error [M1][L9]. Старый six-way test в тот же период, однако, получил 1.4–1.5 с через proxy и 1.3–2.5 с direct: 9× преимущество не воспроизводилось [L10]. Поэтому direct обоснован меньшим числом внешних failure modes и текущей стабильностью, а не гарантированным latency advantage во всех состояниях сети.

**Confidence: CONFIRMED** — фактический source code, systemd unit, git history и runtime journal.

## 2. Отслеживание стоимости

### Что есть

`_transcribe_audio()` получает `metadata.duration` и пишет только `audio=<seconds>`, file size и `transcribe=<ms>` в journal [L1]. В persistent transcription cache хранится transcript по `file_unique_id`, но не duration, model, request ID или cost [L1]. Сохранённые файлы позволяют задним числом получить duration через `ffprobe`, пока upload cleanup их не удалил.

### Чего нет

- Нет Deepgram usage/cost таблицы, counter или dashboard metric.
- Нет `tag=orchestra...`, поэтому Deepgram usage/billing не умеет отделить Orchestra от Codex и VoiceType.
- Нет отдельного API key/accessor на приложение: проверенные источники используют один credential [M2].
- Общий `cost_usd` Orchestra не подходит: backend берёт его из `claude-agent-sdk` `ResultMessage.total_cost_usd`, а session/dashboard суммируют только это поле [L4][L5].

Deepgram Management API умеет отдавать usage/billing breakdown и per-request cost; request logs доступны до 90 дней, summarized usage — дольше [S5][S6]. Tags специально предназначены для разрезов по приложению/окружению [S7]. На проверенном project API за 2026-05-01…2026-07-18 вернул `usage_tags_count=0` и `billing_tags_count=0` [M3].

**Confidence: CONFIRMED** — source/schema audit плюс read-only Deepgram Management API.

## 3. Как настроен Deepgram у Codex

Формулировка «Codex MCP» не соответствует фактической реализации:

- `~/.codex/config.toml` объявляет MCP servers `serena`, `orchestra`, `openaiDeveloperDocs`, `kwin`; Deepgram там отсутствует [L7].
- Deepgram находится в `~/.codex/skills/deepgram-transcribe/` как skill с bundled Python CLI [L8].
- CLI читает credential в порядке: process `DEEPGRAM_API_KEY` → explicit `--env-file` → `DEEPGRAM_ENV_FILE` → `/mnt/data/Projects/Python/VoiceType/.env` [L8]. Фактически это тот же ключ, что у Orchestra [M2].

Codex defaults:

| Параметр | Codex skill |
|---|---|
| Model | `nova-3` |
| Language | `multi`; `--language ru` доступен явно |
| Formatting | `smart_format=true`, `numerals=true`, `paragraphs=true` |
| Diarization | optional `diarize_model=latest` |
| Vocabulary | repeatable `keyterm=` |
| Input | MIME определяется по расширению; audio/video загружаются как есть |
| Output | text рядом с файлом, stdout или raw JSON |
| Timeout/retry | 900 секунд; собственного retry loop нет |
| Network | стандартный `urllib`, поэтому наследует `HTTPS_PROXY`/`HTTP_PROXY` |

`diarize_model=latest` соответствует актуальной рекомендации Deepgram и сам включает diarизацию; дополнительный `diarize=true` не нужен [S8].

**Confidence: CONFIRMED для этой машины** — Codex config, skill и script прочитаны напрямую; глобальное утверждение про все Codex installations не делается.

## 4. Orchestra против Codex

| Аспект | Orchestra TG | Codex skill | Что лучше здесь |
|---|---|---|---|
| Model | Nova-3 | Nova-3 | Паритет |
| Language | `ru` | `multi` default | Orchestra дешевле и детерминированнее для русских voice; Codex гибче для неизвестного файла/code-switching |
| Цена PAYG pre-recorded | $0.0043/мин | $0.0052/мин при `multi` | Orchestra на 17.3% дешевле относительно multilingual price; `multi` на 20.9% дороже относительно mono baseline [S1] |
| Formatting | smart format | smart + numerals + paragraphs | Codex богаче; для Nova-3 non-English smart formatting уже даёт punctuation/paragraph behavior, а `numerals=true` полезен только если важен числовой формат [S9][S10] |
| Domain terms | нет | optional keyterms | Codex лучше для разовых встреч/терминологии; добавлять глобальные keyterms в TG без ошибок распознавания не обосновано [S11] |
| Proxy | принудительно direct | inherited proxy | Direct убирает proxy failure mode и сейчас даёт 2.43 с average; старые A/B latency были противоречивы [M1][L9][L10] |
| Cache | Telegram `file_unique_id` | нет | Orchestra лучше для повторно присланного файла |
| Observability | duration/latency journal | output only | Оба не дают application cost tracking |

Итог: **не копировать Codex defaults целиком**. Он решает другую задачу — произвольные локальные audio/video, иногда с несколькими языками и спикерами. Для короткого Telegram voice текущий Orchestra path проще, дешевле и уже измеренно работает.

## 5. Цены и выбор модели

Актуальные публичные PAYG rates на 2026-07-18 для relevant pre-recorded моделей взяты из `application/ld+json` structured offers официальной pricing page [S1][M5]. Rendered extractor смешивает streaming и pre-recorded tabs, поэтому route names в structured data важны.

| Модель/режим | PAYG | Growth | Применимость |
|---|---:|---:|---|
| Nova-3 monolingual pre-recorded | **$0.0043/мин** ($0.258/ч) | $0.0036/мин | Лучший default для известного русского языка |
| Nova-3 multilingual pre-recorded | $0.0052/мин ($0.312/ч) | $0.0043/мин | Только когда реально нужен code-switching/auto language |
| Whisper Large pre-recorded | $0.0048/мин ($0.288/ч) | $0.0048/мин | Дороже mono Nova-3; хуже scalability, только pre-recorded |
| Nova-2 legacy streaming | $0.35/ч = $0.00583/мин | примерно на 12.5% ниже | Legacy; Deepgram рекомендует его для языков без Nova-3 или filler words, не для русского TG [S1][S2] |

Текущая pricing page не публикует отдельный pre-recorded Nova-2 offer. В фактическом account billing старый `sync::nova` line item в мае вышел около $0.00439/мин, но это account/history measurement, а не гарантированная публичная ставка [M3].

Nova-3 получил отдельную monolingual Russian model в ноябре 2025 и сейчас официально рекомендуется как general-purpose batch/streaming model; `nova-2` оставлен для языков, ещё не покрытых Nova-3, и filler words [S2][S3]. Whisper Cloud сам Deepgram описывает как менее масштабируемый и медленный, с дополнительными concurrency/processing limits; current docs также не рекомендуют его, когда Nova покрывает задачу [S12].

На pricing page есть внутреннее противоречие: structured offers различают streaming и pre-recorded rates, а FAQ заявляет отсутствие premium между ними [S1]. Для Orchestra это не меняет выбор: запросы — pre-recorded, account billing за май–июль наблюдал $0.004400–$0.004423/мин для `sync::nova-3`, то есть рядом с публичным $0.0043/мин [M3]. Invoice/API measurement сильнее текста FAQ.

**Рекомендация модели: KEEP `nova-3&language=ru`.** Переходить на `multi` только после A/B с human transcript на voice, где русский реально смешан с английскими фразами. Nova-2 и Whisper не дают подтверждённого выигрыша ни по цене, ни по возможностям; WER на нашем корпусе остаётся **UNCERTAIN**.

## 6. Сколько уходит в месяц

### Orchestra voice — восстановлено локально

`ffprobe` по всем retained `data/uploads/voice_*.oga` и video-note audio дал [M4]:

| Период | Voice files | Минуты Orchestra | Оценка по $0.0043/мин |
|---|---:|---:|---:|
| 2026-05 | 250 voice + 1 video note | 113.675 | **$0.489** |
| 2026-06 | 142 | 58.500 | **$0.252** |
| 2026-07-01…18 | 46 | 17.852 | **$0.077** |
| Июльский прогноз (31 день, линейно) | ≈79 | 30.745 | **$0.132/мес** |

Среднее за два полных сохранённых месяца май+июнь — около 86.1 мин и **$0.37/мес**. Практический диапазон текущего масштаба: **$0.13–$0.49 в месяц**.

Ограничения оценки:

- Upload cleanup ограничен 1 GiB и может удалить старые media, поэтому это точная сумма для сохранившихся файлов, но не вечный ledger [L1].
- Transcription cache содержит 525 успешных unique IDs, а файлов осталось 439; для удалённых файлов duration не хранится [M4]. Значит lifetime spend до мая из локального состояния уже не восстановить.
- Июльские 46 файлов полностью совпали с 46 success lines в retained journal (1071.2 с = 17.853 мин), что подтверждает метод на текущем периоде [M1][M4].
- Deepgram биллит посекундно без округления, поэтому суммирование duration корректно; multichannel умножает billable duration, но Telegram voice/converted note здесь mono [S1].

### Весь общий Deepgram project — фактический billing API

| Период | Requests | Часы | Billing USD |
|---|---:|---:|---:|
| 2026-05 | 1,919 | 17.613 | **$4.64947** |
| 2026-06 | 4,478 | 30.422 | **$8.07340** |
| 2026-07-01…18 | 2,016 | 14.036 | **$3.72317** |
| Июльский прогноз (31 день, линейно) | ≈3,472 | ≈24.17 | **$6.41/мес** |

Доля локально измеренного Orchestra voice: примерно 10.8% минут в мае, 3.2% в июне и 2.1% в июле. Остальное нельзя честно поделить между VoiceType, Codex и другими callers из-за общего key и нулевого tagging [M3].

Текущий project balance — **$177.9266 USD credit** [M3]. Поэтому billing USD выше — dollar-equivalent consumption; фактическое списание с карты может оставаться $0, пока действует credit. Тип credit (promo/purchased) из sanitized list response не определялся.

## Рекомендации

1. **Добавить `tag=orchestra-tg` в Deepgram URL.** Это минимальное изменение даст точный application spend для **будущих** запросов без локальной тарифной константы [S7]. Прошлые untagged расходы он ретроактивно не разделит; tag также должен оставаться уникальным для Orchestra.
2. **Оставить `nova-3&language=ru` и direct network path.** Это соответствует current Russian support, минимальной relevant цене и текущим runtime measurements.
3. **Добавить локальный usage event на success:** `ts`, `request_id`, `duration_seconds`, `model`, `language`, `cached`, `estimated_cost_usd`. Для invoice truth периодически читать billing breakdown по tag; dashboard estimate не должен смешиваться с виртуальным LLM `cost_usd`.
4. **При необходимости строгой изоляции создать отдельный Deepgram API key для Orchestra.** Tags достаточно для аналитики; отдельный accessor лучше для revoke/quota и защищает атрибуцию от callers, забывших tag.
5. **Не переключаться на `multi` по аналогии с Codex.** Сначала 20–30 representative voice + human ground truth, заранее выбранные WER/semantic-error criteria; принимать surcharge только если качество заметно лучше.
6. **Не переходить на Nova-2/Whisper.** Цена/ограничения хуже для текущей задачи, а доказательств выигрыша на русском корпусе нет.
7. **Optional:** `numerals=true` можно добавить без смены модели, если ошибки в числах действительно встречаются. Это форматирование, не cost-observability fix; без примеров ошибки приоритет низкий [S10].

## Affected files, риски и edge cases для возможной Phase 2

- `app/tg_bridge.py`: tag, request metadata, usage persistence/logging.
- `app/db.py`: только если нужен локальный durable ledger/dashboard; для простого tagging не требуется.
- `app/main.py` + frontend usage UI: только если пользователь хочет отдельную voice metric.
- `.env.example`: отдельный key/tag env только если выбран отдельный accessor; не добавлять реальный secret.
- Tests: сейчас `_transcribe_audio` не покрыт targeted tests; нужны mocked HTTP response, cache hit, API error и duration/cost event.

Риски:

- Один и тот же voice может быть повторно billed после потери/corruption transcription cache.
- Retry после неопределённого network outcome теоретически может повторить уже обработанный request; exact spend должен приходить из Deepgram billing, не из числа локальных function calls.
- `language=ru` может хуже обработать настоящее code-switching; это quality trade-off, не подтверждённый баг.
- Pricing меняется; локальная USD estimate должна иметь явную rate date или быть заменена billing API.
- Не смешивать реальный Deepgram billing с виртуальным/API-equivalent LLM cost в текущем dashboard.

## Counter-evidence и неопределённости

- Codex rule предполагает, что `multi` полезен для Russian + English names; это правдоподобно, но не проверено на Orchestra voice. Поэтому `ru` — экономичный default, не доказанный WER champion.
- Deepgram — vendor source и заявляет преимущество Nova-3; независимого русского benchmark на нашем аудио нет. Рекомендация не утверждает конкретный accuracy uplift.
- Pricing page одновременно показывает разные structured rates для streaming/pre-recorded и говорит в FAQ, что premium нет. Для расчёта использованы pre-recorded structured offer и проверка реальным billing API.
- Старый local proxy test не воспроизвёл commit-level 9× latency gap и иногда был быстрее через proxy [L10]. Direct сохраняется ради меньшего числа failure modes, не как универсально самый быстрый маршрут.
- Retained uploads не являются полным lifetime ledger. Май–июль измерены; более ранний локальный spend неизвестен.
- Общий account billing точен, но attribution нет. Любая попытка назвать все $8.07 июня «voice Orchestra» была бы ошибкой примерно на порядок.

## Measurements (raw normalized output)

### M1 — systemd journal, retained range 2026-07-03…2026-07-18

```text
success=46 audio_seconds=1071.200 audio_minutes=17.853 avg_audio_seconds=23.287 max_audio_seconds=62.400 avg_latency_ms=2428.0
Transcription cache hit: 0
Deepgram failed after 3 attempts: 0
Deepgram parse error: 0
Deepgram attempt 0
first_deepgram_log=2026-07-03T14:17:52+07:00
last_deepgram_log=2026-07-18T15:03:11+07:00
```

### M2 — credential source comparison, secret redacted

```text
orchestra_env: present=True, chars=40
worktree_env: present=True, chars=40
voicetype_env: present=True, chars=40
process_env: present=True, chars=40
all pairwise equality checks: True
```

### M3 — Deepgram Management API, read-only, IDs redacted

```text
projects_count=1
usage_tags_count=0
billing_tags_count=0
2026-05 usage: 17.612962 hours, 1919 requests; billing_total=4.649470
2026-06 usage: 30.422359 hours, 4478 requests; billing_total=8.073400
2026-07-01..18 usage: 14.036423 hours, 2016 requests; billing_total=3.723170
observed sync::nova-3 rate: May $0.004400/min; June $0.004423/min; July $0.004421/min
balance: 177.92661517 usd
line_items: sync::nova-3, sync::nova, surcharge::n3mbatch
```

### M4 — retained uploads/cache

```text
transcription_cache_entries=525
voice_file_month=202605 files=250 minutes=113.549
voice_file_month=202606 files=142 minutes=58.500
voice_file_month=202607 files=46 minutes=17.852
videonote_audio_month=202605 files=1 minutes=0.126
voice_files_total=438 minutes_total=189.900
```

### M5 — current pricing page structured offers

```text
Streaming - Nova-3 Monolingual - Pay As You Go: 0.0048 USD/min
Pre-Recorded - Nova-3 Monolingual - Pay As You Go: 0.0043 USD/min
Pre-Recorded - Nova-3 Multilingual - Pay As You Go: 0.0052 USD/min
Pre-Recorded - Whisper Large - Pay As You Go: 0.0048 USD/min
```

Эти route-specific offers извлечены из raw `application/ld+json`; observed account `sync::nova-3` rate $0.004400–$0.004423/мин независимо подтверждает порядок величины [M3].

## Sources

### Local primary sources

- **[L1]** `app/tg_bridge.py:26-30, 68-81, 146-197, 986-1036, 1121-1127` — handler, request, params, cache, credential load.
- **[L2]** `/etc/systemd/system/orchestra.service:8-14` — project working directory и `EnvironmentFile=/mnt/data/Projects/Python/orchestra/.env`.
- **[L3]** `.env.example:38-39` — optional `DEEPGRAM_API_KEY`.
- **[L4]** `app/backend_claude.py:250-305`, `app/session.py:453-503` — LLM `ResultMessage.total_cost_usd` → session cost.
- **[L5]** `app/db.py:608-630, 900-915` — dashboard/session cost aggregation and usage snapshots.
- **[L6]** `.mcp.json:1-16` — только Orchestra MCP.
- **[L7]** `~/.codex/config.toml:105-126` — Codex MCP definitions без Deepgram.
- **[L8]** `~/.codex/skills/deepgram-transcribe/SKILL.md`, `scripts/transcribe.py:17-144` — Codex workflow, defaults, credential resolution и request params.
- **[L9]** git commit `63b9c7aa5b3d4b6614b6f0ff01a973a0f0745d02` — proxy 34 с против direct 3.8 с.
- **[L10]** `docs/research-deepgram.md:118-145` — subsequent six-way network test; все варианты работали, latency gap не воспроизвёлся.

### External primary sources, fetched 2026-07-18

- **[S1]** [Deepgram Pricing](https://deepgram.com/pricing) — current structured offers, legacy FAQ, per-second billing.
- **[S2]** [Models & Languages Overview](https://developers.deepgram.com/docs/models-languages-overview/) — назначение Nova-3/Nova-2, Russian и multilingual support, Whisper limits.
- **[S3]** [Nova-3 Russian model update, 2025-11-04](https://developers.deepgram.com/changelog/2025/11/4) — monolingual Russian availability.
- **[S4]** [Multilingual Voice Agents](https://developers.deepgram.com/docs/multilingual-voice-agent) — `language=multi` для code-switching.
- **[S5]** [Logs & Usage Data](https://developers.deepgram.com/docs/using-logs-usage) — 90-day request logs, summarized usage, per-request pricing.
- **[S6]** [Get Project Billing Breakdown](https://developers.deepgram.com/reference/manage/billing/breakdown/get) — billing dollars grouped by line item/tag/accessor.
- **[S7]** [Tagging Your Usage Data](https://developers.deepgram.com/guides/fundamentals/tagging-your-usage-data) — application/environment attribution.
- **[S8]** [Speaker Diarization](https://developers.deepgram.com/docs/diarization) — `diarize_model=latest` enables diarization.
- **[S9]** [Smart formatting](https://developers.deepgram.com/docs/self-hosted-smart-formatting) — Nova-3 non-English formatting behavior.
- **[S10]** [Numerals](https://developers.deepgram.com/docs/numerals) — `numerals=true`, Russian support.
- **[S11]** [Keyterm Prompting](https://developers.deepgram.com/docs/keyterm) — Nova-3 domain-term hints.
- **[S12]** [Deepgram Whisper Cloud](https://developers.deepgram.com/docs/deepgram-whisper-cloud) — pre-recorded-only, scalability and timeout caveats.
