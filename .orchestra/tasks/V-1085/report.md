# V-1085 — ElevenLabs API для активного Starter

Дата исследования: **25 октября 2026, UTC**. Статус: исследование; код продукта не менялся, ElevenLabs SDK не устанавливался, генерации и запросы с ключами не выполнялись. Все внешние обращения работника — чтение публичных официальных документов. Это снимок документации на указанную дату, а не бессрочная гарантия тарифов.

**Практический выбор: сохранённый Sergey + `eleven_flash_v2_5` через HTTP TTS, с timestamps для субтитров. Для нашего аккаунта ставка модели 0,5 кредита/символ подтверждена read-only проверкой root.** Для русской речи заранее писать числа и сокращения так, как они должны звучать. Качество Sergey на конкретном русском сценарии ещё не прослушивалось; превосходство Flash/Turbo по разборчивости не измерено.

Короткие действия и развилки: [recommendations.md](recommendations.md). Полный справочный охват: [endpoint-catalog.md](endpoint-catalog.md), **400 уникальных method/path из 592 страниц API Reference**, плюс дополнительные conversation/Realtime WS из официальных guides. [Манифест](sources/api-inventory.json) сохраняет URL, дату получения и SHA-256 страниц; тела страниц, ключи и ответы личного аккаунта в него не входят. Каталог подтверждает существование документации, не права нашего аккаунта.

## 1. Что подтверждено именно для нас

### Свидетельство root, а не собственный API-замер работника

Оркестратор передал 25.10.2026 результаты независимой read-only проверки аккаунта. Сырые JSON остались локально у root; работник их не запрашивал и не читал.

| Объект | Переданное root значение | Что следует / граница доказательства |
| --- | --- | --- |
| Подписка | `tier=starter`, `status=active` | Starter активен; цена оплаченного счёта и остаток здесь неизвестны |
| Каталог аккаунта | 11 моделей | Это не означает доступность всех моделей из публичного сайта; полный список root не передавал |
| Flash | `eleven_flash_v2_5`, доступен TTS | Выбранная модель доступна этому аккаунту |
| Ставка Flash | `model_rates.character_cost_multiplier=0.5`, `cost_discount_multiplier=1.0` | Базовый расчёт: 0,5 кредита за учитываемый символ без дополнительной скидки |
| Другое поле модели | `token_cost_factor=1.0` | Нельзя подменять им явный `model_rates.character_cost_multiplier` и объявлять ставку 1 |
| Расширение лимита | `can_extend_character_limit=false`, `allowed_to_extend_character_limit=false` | Нет подтверждённого разрешения на legacy overage; это не доказывает отсутствие отдельного PAYG-баланса/Auto Top Up |
| Выбранный пользователем голос | **Sergey - Rich, Engaging and Captivating**, `voice_id=XuEV9VY3VUASYgJVNBh0` | Публичный идентификатор библиотечного голоса, не секрет; root нашёл его в полном saved list |
| Тип/совместимость Sergey | professional / copied from library; Flash v2.5 fine-tuned available | Можно использовать чужой разрешённый библиотечный PVC на Starter; это не создание собственного PVC |
| Sergey sharing | `sharing.rate=1.0`, `financial_rewards_enabled=false` | Нейтральная ставка голоса по переданным метаданным; нет признака платной надбавки владельцу. Фактическое списание генерацией не проверялось |

Поля `model_rates`, их единицы и deprecation старых лимитов описаны в [Models API][models-api]. У [Shared Voices API][shared] поле `rate` прямо определено как **rate multiplier**, а `fiat_rate` отдельно имеет единицу USD / 1000 credits. В [Get voice][voice-get] вложенное `sharing.rate` описано менее точно — как rate of voice sharing. Поэтому перенос этой семантики на сохранённую копию Sergey — **обоснованная интерпретация метаданных**, не отдельный биллинговый замер.

Расчёт для Sergey: `N × 0.5 × 1.0 × 1.0 ≈ 0.5N credits`, где множители — модель, скидка, голос. `sharing.rate=1.0` не прибавляет ещё один кредит: нейтральный множитель сохраняет 0,5. `financial_rewards_enabled=false` поддерживает отсутствие надбавки, но сам по себе этот флаг не заменяет rate. Для другого голоса с множителем 2 цена той же модели станет примерно 1 кредит/символ; при 3 — 1,5. Механизм удорожания описан в [официальной справке custom rates][multipliers].

Пока остаётся неизвестным: округление/минимальное списание для конкретного запроса, окончательная тарифицируемая длина после правил произношения, фактический `voice_multiplier` для выполненной генерации. Для будущего аудита есть измерение usage с измерением `voice_multiplier` в [Workspace Usage API][usage]. В этой задаче генерация ради проверки не разрешена и не делалась.

### Публичный Starter и наш действующий аккаунт — разные уровни сведений

[ElevenCreative pricing][pricing] сейчас показывает Starter **$6/месяц**, 30 000 credits; публичная акция первого месяца $1 до 1 ноября не доказывает условия уже купленной подписки. Годовая цена в пересчёте — $5/месяц. Общий месячный пул расходуется разными Creative-продуктами. Неизрасходованное может переноситься на два месяца при сохранении платного плана; downgrade/cancel меняет правила переноса. См. также [Billing][billing].

**Обнаруженное расхождение официальных источников нельзя скрывать:** [публичный новый API pricing][api-pricing] показывает для Starter 150 000 символов Flash/Turbo и 75 000 v2/v3/v4, тогда как Creative FAQ продолжает описывать 30 000 credits и 0,5–1 credit/char. Это не основание объявить наш лимит 150 000 символов или пересчитать его в 0,2 кредита/символ. Документация [PAYG][payg] отдельно описывает legacy-подписки и необратимый переход на новую версию pricing. Конкретную причину несовпадения root не подтверждал. Наше рабочее основание — возвращённые аккаунту `model_rates`, а `character_limit`/остаток следует брать из аккаунта, не из рекламы.

При **условном** полном доступном пуле 30 000 credits и отсутствии других расходов/надбавки это 60 000 учитываемых символов Flash. Это расчёт, не показание текущего остатка. 10 000 символов — около 5 000 credits, 1 200 — около 600. Минуты нельзя обещать по символам: скорость и язык меняют длительность. Для 1 200 символов после ручной нормализации нужно считать именно окончательный текст. [Character counting FAQ][character-count] прямо включает буквы, цифры, пробелы, пунктуацию, SSML/audio tags; pronunciation rules тоже могут изменить учитываемую длину.

## 2. Экономный путь для видео и русской речи

| Модель | RU / EN; назначение | Экономика и актуальность | Решение для видео |
| --- | --- | --- | --- |
| `eleven_flash_v2_5` | RU и EN, многоязычная быстрая озвучка; до 40 000 символов в TTS-запросе | Наши 0,5 подтверждены root; публично 50% дешевле базового TTS; vendor latency около 75 ms | **Основной вариант**, Sergey совместим по root |
| `eleven_turbo_v2_5` | RU и EN, прежняя многоязычная low-latency модель | В текущем Models прямо **deprecated**; vendor называет функционально эквивалентной Flash 2.5, но с большей средней задержкой | Не выбирать для новой интеграции; обещания, что она понятнее на русском, не доказаны |
| `eleven_flash_v2` / `eleven_turbo_v2` | Только EN | Turbo v2 deprecated; для RU не подходят | В смешанном RU/EN потоке оставить 2.5, чтобы не выбирать неверный English-only маршрут |
| `eleven_multilingual_v2` | RU/EN, стабильная длинная начитка, 10 000 символов/запрос | Creative-база 1 credit/char; ставку именно нашего аккаунта root не передал | Кандидат для проблемных фрагментов после отдельной проверки стоимости/качества |
| `eleven_v3` | RU/EN, выразительность, audio tags, отдельные реплики | TTS до 5 000; dialogue имеет свой более строгий лимит; точная наша ставка неизвестна | Для актёрской подачи, не обязательный расход на каждый технический ролик |
| `eleven_v4`, `eleven_v4_turbo`, `eleven_v3_conversational` | Современные выразительные модели; v4 family RU/EN | Есть в публичных docs; наличие каждой среди наших 11 не установлено | Отдельный выбор, не автоматическая замена подтверждённого Flash |

Источники: [Models, включая Deprecated models][models], [TTS capabilities][tts-overview], [официальный model selection][selection], [TTS API][tts], [Dialogue API][dialogue]. Процент экономии, функциональная эквивалентность и latency — заявления ElevenLabs, а не наши измерения. Нельзя переносить старую репутацию «Turbo качественнее Flash» на текущую рекомендацию вендора. Для времени до первого слышимого звука нужны ещё сеть, очередь и декодирование; это объяснено в [Understanding latency][latency].

Рекомендуемый процесс после разрешения реализации/расхода:

1. Зафиксировать русский текст, смысловые сцены и произношение. «25.10.2026», «12,5%», «₽», URL, версии и аббревиатуры переписать в нужное звучание; в смешанной речи явно решить, как произносить английские названия. Не отправлять служебные ремарки как обычный текст: Flash может их прочитать.
2. Выбрать Sergey и `eleven_flash_v2_5`, русский `language_code="ru"`, `mp3_44100_128`. Начать с обычной скорости и чистого голоса без эффектов; менять один параметр за раз. Это стартовые рекомендации, не результаты прослушивания.
3. Получить `/with-timestamps`, если нужны субтитры: audio и character alignment приходят одной генерацией. Перевести символы в слова/строки SRT/VTT локально; не платить за отдельный STT той же только что синтезированной речи без причины.
4. Делить по предложениям/сценам, чтобы исправление одного ударения не требовало повторной генерации всего ролика. Передавать контекст `previous_text` / `next_text` там, где он поддерживается; сохранять аудио и параметры уже принятых фрагментов.
5. Проверить на слух числа, ударения, окончания, имена и переключения RU/EN. Если Flash не даёт разборчивость, сначала править текст/alias; затем ограниченно сравнить Multilingual/v3/v4 на проблемном фрагменте с заранее заданным бюджетом. Не переключаться на deprecated Turbo ради недоказанного улучшения.
6. Собирать видео на исходном видеомастере локально: TTS не генерирует видеоряд, не делает lip sync и не гарантирует точную длительность сцены. Тайминг подгоняют монтажом/паузами либо сценарием. Dubbing — другая задача: перевод уже существующей речи.

Важные ограничения произношения: текущий [Models guide][models] предупреждает, что включение нормализации `on` у v2.5 — Enterprise-возможность. Наличие параметра в общей схеме не обещает его на Starter. Для Flash 2.5 использовать предварительную нормализацию. По [Pronunciation dictionaries guide][pronunciation], phoneme-правила поддерживаются не всеми моделями; для Flash 2.5 применять **alias**, а не рассчитывать на русские IPA/CMU. Отдельный phoneme-путь для языков кроме EN описан у v4; его доступность у нас не проверена.

Предлагаемый будущий A/B, **не выполненный**: одинаковые 8–12 коротких фраз, Sergey, один формат и настройка скорости; числа/даты, омографы, имена, аббревиатуры, RU/EN, длинное предложение. Слепая ручная оценка разборчивости и ошибок, число перегенераций, затраты credits/принятый фрагмент. STT round-trip может подсказать ошибки, но не заменяет русскоязычного слушателя. Samples, MOS/WER, скорость генерации и экономия от снижения числа дублей сейчас неизвестны.

## 3. Как читать цены и доступность в карте

Обозначения: **Д** — документация допускает Starter; **Р** — root подтвердил конкретный ресурс аккаунта; **?** — нужно подтвердить entitlement/ставку; **Нет** — документирован более высокий план. Д не равняется выполненному запросу. Даже Д зависит от permissions ключа, voice/model, региона и остатка.

Цены ниже сознательно разделены:

| Режим / продукт | Опубликованная единица и ставка | Что это означает для нас |
| --- | --- | --- |
| Наш Flash + Sergey | ≈0,5 credits/учитываемый символ | Ставка модели Р; neutral voice интерпретирован по метаданным; списание не измерено |
| Creative FAQ | TTS 1 credit/char, Flash/Turbo API 0,5–1; STT ≈330/min; Music ≈900/min; SFX ≈200/generation; changer/isolation ≈1 000/min | Ориентиры FAQ, не универсальная матрица API/legacy |
| Новый public API: Flash/Turbo, v4 Turbo, v3 Conversational | $0.04 / 1000 chars | Не разрешение расходовать деньги и не пересчёт нашей подписки |
| Новый public API: Multilingual v2, v3, v4 | $0.08 / 1000 chars | Тот же предел применимости |
| Новый public API: Scribe v2 / Medical; realtime | $0.22/hour; $0.39/hour | Дополнения/каналы оплачиваются отдельно |
| Новый public API: Music; changer/isolation/SFX | $0.15/min; $0.12/min | SFX auto-duration и preview billing отдельно ниже |
| Новый public API: Dubbing v1 / no watermark; v2 | $0.33/min / $0.50/min; $2.20/min | Не смешивать v1 watermark-скидку с v2 |
| Новый public API: music finetune | $1.50/finetune | Обучение — отдельный расход |

Источники ставок: [Creative FAQ][pricing], [API pricing][api-pricing]. Доллары указаны до налогов. Публичные «included minutes/characters» разных продуктов — альтернативные оценки использования бюджета, их нельзя суммировать как независимые бесплатные квоты. **ElevenAgents имеет отдельный режим call minutes**, см. раздел 7; нельзя механически списывать его минуты из TTS-символов.

## 4. Речь, таймкоды и обработка звука

HTTP base: `https://api.elevenlabs.io`; клиентский WS base: `wss://api.elevenlabs.io`. **Исключение Speech Engine upstream**: это протокол сервера пользователя, ElevenLabs подключается к указанному пользователем `wsUrl`, а не наоборот. `{...}` — placeholders. CRUD = операции создания/чтения/редактирования/удаления метаданных; их наличие не означает бесплатность запуска генерации.

| Функция / endpoints / models | Вход → выход | Стоимость / Starter / ограничения | Полезный пример; неизвестное; источник |
| --- | --- | --- | --- |
| **TTS RU/EN**: `POST /v1/text-to-speech/{voice_id}`; Flash 2.5, Multilingual v2, v3; модель задавать явно | JSON text, model, voice settings, language, context → audio bytes | Flash+Sergey Р, ≈0,5/char; прочие ставки ?; лимит модели и budget применяются одновременно | Начитать русский обзор интерфейса. Разборчивость конкретного текста не измерена. [TTS][tts] |
| **TTS + timestamps**: тот же путь + `/with-timestamps` | JSON → `audio_base64`, `alignment`, `normalized_alignment`, время символов в секундах | Д; базовая TTS-единица, отдельная надбавка за timestamps в схеме не указана | Сделать субтитры без повторного распознавания. Нет обещания готового SRT или точности монтажа. [Timing][timing] |
| **HTTP streaming**: TTS + `/stream`, `/stream/with-timestamps` | Полный text → бинарный audio stream либо поток JSON с base64/timing | Д; тот же модельный расход; получение частями не делает синтез бесплатным | Раннее прослушивание длинной реплики. Обычный audio stream нельзя разбирать как SSE JSON; timestamp-поток имеет другую форму. [Stream][stream], [Stream timing][stream-timing] |
| **TTS WebSocket**: `/v1/text-to-speech/{voice_id}/stream-input`; `/multi-stream-input` | Постепенный text → base64 audio, alignment; несколько контекстов для interruption | Д; Flash/Multilingual; v3/v4 не идут в обычный TTS WS. Считается время активной генерации; idle socket не расходует стандартный concurrency | Озвучивать ответы LLM по мере поступления. Когда весь сценарий уже есть, HTTP проще; реальный TTFA неизвестен. [TTS WS][tts-ws], [Multi-context][tts-multi], [Comparison][ws-compare] |
| **Text to Dialogue**: `POST /v1/text-to-dialogue`, `/stream`, `/with-timestamps`, `/stream/with-timestamps`; v3/v4 | Массив text/voice_id, tags, settings → audio, optional alignment | Д/модель ?; цена за символ и голоса. Endpoint допускает **до 10 уникальных voices**; для надёжности ≤2 000 chars суммарно по inputs | Два персонажа объясняют продукт. Overview говорит «no speaker limit», но для конкретного запроса применяем строгую схему API. [Dialogue][dialogue], [Timing][dialogue-timing] |
| **Dialogue WS**: `/v1/text-to-dialogue/stream-input`, `/multi-stream-input` | Сначала регистрация voices, затем inputs и flush/new_turn → аудио по репликам | Д/модель ?; отдельные sessions, Starter 21 в public docs. `eleven_v3_conversational` в reference допускает один голос, v3 до 10. v4 поддержан guide, но reference всё ещё пишет v3-only — конфликт | Живой выразительный персонаж. v4 WS entitlement/контракт не считать доказанным без account check. [TTD WS][dialogue-ws], [Comparison][ws-compare] |
| **Audio effects**: `GET /v1/audio-effects/catalog`, `audio_effects` в TTS/TTD | Каталог presets + filter, distance, environment, background, pan → обработанный синтез | Д; docs не указывают доплату за эффекты. Stereo reverb/pan несовместимы с mono `pcm_*`, `ulaw_*`, `alaw_*`: 400 | Радиоголос игрового персонажа. Для обычной озвучки эффекты ухудшают практическую понятность — это инженерный риск, не измерение. [Effects][effects] |
| **Batch STT**: `POST /v1/speech-to-text`; `scribe_v2`, `scribe_v2_medical`; `scribe_v1` deprecated | multipart audio/video или source_url → JSON text, words/timestamps, language, optional diarization/events/entities; дополнительные exports | Д, ставка нашего аккаунта ?; public $0.22/hour; RU/EN, до 32 speakers. Async webhook и GET/DELETE `/v1/speech-to-text/transcripts/{id}` | Субтитры к уже записанному интервью; поиск по видео. Точность на нашем шуме неизвестна. [STT][stt], [Capabilities][stt-overview] |
| **STT realtime**: WS `/v1/speech-to-text/realtime`, `scribe_v2_realtime` | base64 audio chunks, VAD/manual commits → partial/committed transcript и optional word times | Д; public $0.39/hour, доп. опции платные; public concurrency Starter 9. Соединение и billed audio duration требуют проверки конкретного режима | Живые субтитры/диктовка. Сетевую задержку/accuracy на RU не мерили. [Realtime STT][stt-ws] |
| **Forced Alignment**: `POST /v1/forced-alignment` | multipart audio + известный plain transcript → word/character time alignment | Д; ставка как batch STT, наш credit rate ?; RU/EN; 3 GB, 10 h, 675 000 chars, без diarization | Привязать исправленную расшифровку к существующей дорожке. Не переводит и не создаёт речь; нет смысла повторять вместо TTS timing без нужды. [Alignment][alignment], [API][alignment-api] |
| **Voice Changer**: `POST /v1/voice-changer/{voice_id}`, `/stream`; `eleven_multilingual_sts_v2`, English-only `eleven_english_sts_v2` | multipart audio, целевой voice → audio с сохранением исходной подачи | Д; duration-based, FAQ ≈1 000 credits/min, new public $0.12/min; максимум 5 min/segment | Самому правильно произнести русскую реплику и заменить тембр на разрешённый голос. Не делает перевод; точность identity не измерена. [API][changer-api], [Capabilities][changer] |
| **Voice Isolator**: `POST /v1/audio-isolation`, `/stream`; history GET и DELETE | Аудио/видео с шумом → выделенная речь | Д; FAQ ≈1 000 credits/min, new public $0.12/min; ≤500 MB/1 h | Очистить запись микрофона до STT или монтажа. Не специализированный music vocal separator; артефакты неизвестны. [Isolation][isolation], [API][isolation-api] |

### Детали, которые влияют на счёт и совместимость

Для STT `use_multi_channel` обрабатывает до 5 каналов, **каждый тарифицируется по полной длительности**. API описывает keyterms +20% (при >100 terms минимум 20 s), transcript edit +30% (минимум 10 s), speaker roles +10%; keyterms максимум 1000. Публичный pricing дополнительно даёт денежные ставки add-ons, поэтому проценты нельзя без проверки переносить на неизвестный account rate. `transcript_edit` несовместим с рядом entity/multichannel режимов. API file-схема пишет `<5 GB`, capability/pricing — 3 GB: для планирования взять ≤3 GB, больший объём считать неподтверждённым. [Точный STT contract][stt].

TTS output для Starter разумно фиксировать `mp3_44100_128`. API требует Creator+ для 192 kbps MP3 и Pro+ для PCM/WAV 44.1 kHz. Public pricing и отдельные продуктовые форматы местами расходятся: не обещать lossless/192 kbps на Starter. Смена контейнера MP3→WAV локально не восстанавливает утраченную точность. Seed — best effort, не гарантия воспроизводимости; context/request stitching имеет модельные ограничения. [TTS contract][tts].

У стандартного TTS WS inactivity timeout по умолчанию 20 s, настраивается до 180 s; `auto_mode` ожидает полные предложения, фрагменты могут ухудшить качество. У TTD session idle timeout 20 s сбрасывается keep_alive. Это разные протоколы; `text` обычного TTS нельзя подставлять вместо `inputs` Dialogue. [TTS WS][tts-ws], [TTD WS][dialogue-ws].

## 5. Голоса: использовать, создавать, хранить

| Возможность / endpoints | Вход → выход | Цена / Starter / ограничения | Практика; неизвестное; источник |
| --- | --- | --- | --- |
| **Мои голоса**: `GET /v2/voices`, `GET /v1/voices/{id}`; POST edit, DELETE; GET/POST settings; samples | Пагинация/search/filter → voice metadata, fine_tuning states, previews; настройки → сохранённые значения | Д; generation credits за простое чтение не указаны. Root прошёл полный saved list; первая страница не гарантирует нахождение голоса | Выбирать Sergey по ID, не по одному имени. Срок доступности library voice может измениться. [Search][voices], [Get][voice-get] |
| **Voice Library**: `GET /v1/shared-voices`; `POST /v1/voices/add/{public_user_id}/{voice_id}` | Фильтры language/accent/category/rates → metadata; добавление → voice_id | Д; Free не имеет полного API-доступа к Library. Custom rate повышает стоимость TTS; добавление не равно платной генерации | Найти RU-диктора или EN-ведущего. Проверять `rate`, `fiat_rate`, notice, tier, model compatibility; метки/preview не доказывают качество любого текста. [Library API][shared], [Library guide][library] |
| **Instant Voice Cloning**: `POST /v1/voices/add` | Сэмплы recordings, name, labels → voice_id и requires_verification | Д (Starter+); 10 custom slots Starter, voice operations quota; отдельная setup-цена из API contract не установлена, дальнейшая речь оплачивается | Собственный голос автора курса, с правом на исходную запись. Не путать с созданием PVC. [IVC][ivc], [Slots][slots] |
| **Professional Voice Cloning**: `/v1/voices/pvc`, `/{id}/samples`, `/train`, `/captcha`, `/verification` и sample operations | Чистый датасет/проверка говорящего → trained voice | **Нет для создания на Starter**, Creator+; обучение и verification имеют отдельный lifecycle. Использование доступного библиотечного PVC возможно | Собственный постоянный бренд-диктор при апгрейде. Sergey уже библиотечный professional — апгрейд ради его использования не следует. [PVC][pvc] |
| **Voice Design**: `POST /v1/text-to-voice/design`; `POST /v1/text-to-voice`; preview `GET /{generated_voice_id}/stream` | Описание + preview text → варианты/IDs/base64; сохранить вариант → voice | Д; `eleven_multilingual_ttv_v2` или `eleven_ttv_v3`; preview text 100–1000 chars, описание 20–1000. Оплата preview text, затем обычная цена синтеза; slot при сохранении | Придуманный персонаж без клонирования человека. Цена specific model в нашем аккаунте ?; три preview не означают три постоянных слота. [Design API][design], [Guide][design-guide] |
| **Voice Remix**: `POST /v1/text-to-voice/{voice_id}/remix`, затем сохранить результат | Голос + natural-language изменение → preview/new voice variant | Д/? entitlement конкретного голоса; billing по test script; свой голос/явные права или library voice с infinite notice. Новый вариант, оригинал сохраняется | Сделать более спокойную версию собственного персонажа. Для Sergey права remix/notice root не подтверждал. [Remix][remix], [API][remix-api] |
| **Организация / discovery**: `/v1/voices/collections`, `/{collection_id}/voice/{voice_id}`, `/v1/voices/accents`, `POST /v1/similar-voices`; sample GET/DELETE | Метаданные, voice/reference → коллекции, accents, similar candidates | Д/? по resource permissions; отдельная цена discovery в docs не закреплена | Набор RU/EN голосов для серии видео. Similarity не даёт право клонировать найденного человека. [Каталог маршрутов](endpoint-catalog.md) |
| **Replication isolated environment**: `POST /v1/voices/{id}/replicate-to-isolated-environment` | Голос → копия в целевом окружении | Нет для обычного Starter: isolated residency — Enterprise | Согласованный региональный корпоративный deployment. Нужны отдельный договор и проверка доступных моделей. [Residency][residency] |

[Slots FAQ][slots] даёт Starter 10 custom voices и 65 add/edit операций на billing cycle. [Billing][billing] отдельно уточняет, что сохранённые из Library голоса не используют custom slots. Нельзя считать «professional» в metadata доказательством собственной PVC-квоты. При этом legacy Dubbing с `disable_voice_cloning` имеет собственное предупреждение о расходе voice slots: это endpoint-specific исключение, его нельзя отменять общим правилом Library. [Legacy dub create][dub-legacy].

## 6. SFX, музыка, перевод, Studio и визуальный API

| Возможность / endpoints / models | Вход → выход | Цена / Starter / ограничения | Пример; неизвестное; источник |
| --- | --- | --- | --- |
| **SFX**: `POST /v1/sound-generation`; `eleven_text_to_sound_v2` | Prompt, duration_seconds, prompt influence, loop → audio | Д; API contract 0.5–30 s, overview пишет от 0.1 — для интеграции взять минимум 0.5. Overview: 40 credits/s при explicit duration; FAQ auto generation ≈200; new API $0.12/min — режимы не смешивать | Звук перехода или зацикленный дождь для видео. Точная account ставка explicit/auto и минимальное списание ? [SFX API][sfx-api], [SFX usage][sfx] |
| **Music compose/stream/details**: `POST /v1/music`, `/stream`, `/detailed`, `/detailed/stream`; `music_v1`, `music_v2`, `music_v2_5` | Prompt либо composition_plan, instrumental, seed → audio; detailed также metadata | Д; public $0.15/min, FAQ ≈900 credits/min; фактические наши rate/caps ?. Contract разрешает 3–600 s, pricing пишет 5 min, Music Terms Starter 17 min monthly generation /30 min downloads — конфликт ограничений | Короткая фоновая музыка собственного онлайн-ролика. Не обещать десятиминутный трек или неограниченные коммерческие права. [Compose][music-api], [Music][music], [Terms][music-terms] |
| **Music plan / inpainting**: `POST /v1/music/plan`, генерация через composition_plan/source_from | Prompt/структура/sections или chunks + прежний song → JSON plan, заменённые секции audio | Д/?; **создание plan не расходует credits**, но ограничено rate limit; генерация audio отдельно по длительности; формат plan зависит от music model | Исправить только музыкальный финал. Не предполагать одинаковый plan v1/v2; цены частичной регенерации ? [Plan][music-plan], [Inpainting][music-inpaint] |
| **Audio reference / upload**: `POST /v1/music/upload` и reference механизм v2/v2.5 | Аудио → song reference/plan, copyright screening | Paid plans по overview; upload **платный как generation**, при copyright reject всё равно половина request cost | Референс собственного музыкального стиля. Не бесплатное хранилище и не обход авторских прав. [Upload][music-upload], [Music][music] |
| **Video to Music**: `POST /v1/music/video-to-music` | До 10 videos, вместе ≤200 MB/600 s → soundtrack | Д/? по выбранной model; отдельный premium/units не установлены | Подложка, учитывающая темп собственного монтажа. Наша доступность и точный billing ? [Video to Music][video-music] |
| **Stem separation**: `POST /v1/music/stem-separation` | file, stem_variation_id → downloadable separated tracks | Д/?; отдельная цена/Starter entitlement не установлены, output gates сохраняются | Убрать вокал из своего трека под начитку; разные stems ≠ voice isolation. [Stem API][stems] |
| **Music Finetunes**: `/v1/music/finetunes`, `/{id}` CRUD | Собственные разрешённые записи, name/base model → training status/id | Public $1.50/training плюс generation; Starter API entitlement конкретного training ? | Единый джингл/стиль серии. Требует отдельного решения о данных/плате, не запускать «для проверки». [Finetunes][finetunes], [Music][music] |
| **Новый Dubbing project API**: `POST /v1/dubbing/project`, GET/list/DELETE; `POST /{project_id}/language`, GET/list/DELETE targets | file/source_url, `dubbing_v1` или `dubbing_v2`, target language → async project, targets, signed audio/video URLs | Д; public v1 $0.33–0.50/min, v2 $2.20/min; плата за target/generation. **Создание проекта уже оплачивает минимум один язык** до результата; дополнительные языки оплачиваются отдельно | Локализовать готовое RU-видео на EN с голосами. v2 Alpha; модель фиксируется при create. [Project][dub-project], [Language][dub-language] |
| **Dubbing edit / BYO transcript / regenerate**: `/project/{id}/transcript...`, `/language/{id}/transcript...`, `/transcript/regenerate` | Сегменты/перевод → revision/stale, переработанный audio | V2 transcript editing, BYO translation/transcript и regenerate в текущих docs **Enterprise only**; regeneration оплачивается по edited regions с allowance | Исправить имя в переводе без полного дубля — только после подходящего entitlement. Starter не обещать эти API-редакторы. [Overview][dubbing], [Regenerate][dub-regenerate] |
| **Legacy Dubbing / Dubbing Studio**: `POST /v1/dubbing`, GET/list/DELETE `/{dubbing_id}`, audio/transcript download | file/URL + source/target, watermark/dubbing_studio → async dub и media | Legacy; Studio v1 есть в Starter marketing, maintenance mode. FAQ ≈2k/3k credits/min auto watermark/no watermark, ≈5k/10k Studio. Не тариф v2 | Поддержать старый pipeline. Форматы legacy IDs и project/target IDs не взаимозаменяемы. [Legacy API][dub-legacy], [Dubbing][dubbing] |
| **Realtime Translation**: WS `/v1/translation/realtime` | Source audio + target language → непрерывный translated audio | **Нет**, contract: Enterprise workspaces only; цена договорная/не установлена | Живой перевод трансляции. Не доступный Starter shortcut вместо batch dub. [Translation WS][translation] |
| **Studio / podcasts**: `/v1/studio/projects`, `/{id}/convert`, chapters, snapshots, content, `POST /v1/studio/podcasts` | Документ/URL/текст/главы/настройки → проект, главы, аудио snapshots/archives | Д: Starter публично 20 Studio projects; generation по модели/объёму. Podcast API сейчас покрывает LLM за счёт ElevenLabs, но audio платное; docs предупреждают о будущей оплате обоих | Длинный аудиогайд или диалоговый подкаст из своего материала. Create podcast сразу auto-convert, это не пустой бесплатный проект. [Studio API][studio], [Podcast][podcast] |
| **Pronunciation Dictionaries**: `/v1/pronunciation-dictionaries/add-from-file`, `/add-from-rules`, list/get/download, add/remove/set-rules | PLS/file или правила → dictionary id/version, применяются к TTS | Д; отдельная management цена не указана, изменения могут менять billed text length; до 3 locators в TTS | Исправить название продукта через alias. Не все models поддерживают phonemes. [Guide][pronunciation], [Rules API][dictionary] |
| **Audio Native**: `POST /v1/audio-native`, `/{id}/settings`, `/{id}/content`, `/content` | Контент страницы/проекта → embed player/settings | **Нет**, Creator+; генерации используют TTS-квоту | Озвучка статей сайта; на Starter сохранить собственный MP3 можно, но продукт Native не обещать. [Native guide][native] |
| **Image/Video / Flows**: `POST/GET /v1/flows/image`, `/video`, `/text-to-speech`; GET `/{generation_id}` | Prompt + model-specific params, references → pending generation ID, затем media | **Image/Video API: Нет на Starter, Pro+ по capability guide**, хотя web UI доступен paid plans. Цена зависит от модели/настроек/длительности; ByteDance API требует approval. Для Flows TTS gate отдельно не установлен; не переносить Flash pricing | Иллюстрации/B-roll к ролику после апгрейда. Список внешних моделей меняется; не нужен для выбранного TTS-пути. [Image/video][visual], [Video API][flows-video], [Image API][flows-image] |
| **Assets / Templates**: `/v1/assets` CRUD; `/v1/flows/templates`, `/{id}/runs` create/list/get | Upload image/audio/video; template variables/assets → asset IDs, workflow run outputs | Management цена ?; run может запускать несколько платных моделей; отдельного общего Starter тарифа нет | Повторяемый шаблон ролика. До запуска нужен состав шагов и полный бюджет. [Assets][assets], [Template run][templates] |

**Музыка требует отдельного решения даже при наличии API на Starter.** [Music Terms, редакция 09.10.2026][music-terms] ограничивают Starter индивидуальным использованием; streaming distribution (Spotify и аналоги) запрещена. Допускаемые коммерческие media rights имеют исключения film/TV/radio/Studio Games; music libraries и resale модели запрещены без письменного разрешения. Attribution на Starter не требуется. API access разрешён, concurrency 2; high-quality downloads в таблице Starter не разрешены. «Music commercial use» в карточке плана не отменяет этих условий. Для собственного индивидуального онлайн-видео путь потенциально применим; для компании, библиотеки треков, дистрибуции или иных исключений нужно проверить подходящий план/лицензию. Terms дают 17 min/month generation, а API pricing — 40 min Music для Starter: единый применимый лимит нашего аккаунта неизвестен, поэтому не обещать 40 min.

В [Image/Video guide][visual] есть не только генерация: reference-guided editing, продление видео, motion control, avatars/lip sync, upscale и background removal. Примеры семейств: Seedance/Kling/Veo/Runway/LTX/Wan для видео; GPT Image/FLUX/Seedream/Nano Banana для изображений; Sync/HeyGen/OmniHuman для lip sync, Topaz для upscale. Это внешние специализированные модели с собственными настройками/единицами, без единой ставки Flash. API Pro+ и provider/regional approvals проверяются отдельно; ни один маршрут не запускался.

Dubbing v2 не имеет watermark-discount toggle: free получает watermark, paid — без него. Для вывода production master лучше перенести dubbed audio в исходное видео: preview video может иметь другое разрешение; многоканальный оригинал не сохраняется как 5.1. Текущие ограничения/self-serve concurrency и v1 Studio maintenance описаны в [Dubbing capabilities][dubbing]. В проектном API до 3 GiB source; duration/модельные ограничения нужно сверять отдельно, а не переносить лимит веб-интерфейса на API.

## 7. Agents, Realtime и операции аккаунта

| Функция / endpoints | Вход → выход | Цена / Starter / ограничения | Пример; неизвестное; источник |
| --- | --- | --- | --- |
| **ElevenAgents**: `/v1/convai/agents` CRUD, conversation WS `/v1/convai/conversation`, signed-url/token, conversations/audio/feedback | Agent config, prompt/tools/KB, audio/text → audio replies, transcripts/events, conversation records | Д/? фактический account entitlement; новый public Starter 75 call min/6 calls, $0.08/min сверх, $0.16 burst, $0.003 text msg; LLM отдельно | Голосовой помощник на сайте. Не считать бесплатной надстройкой нашей TTS-подписки. [Agents][agents], [Agents pricing][agents-pricing], [WS guide][agent-ws] |
| **Standalone Realtime models**: `POST /v1/convai/realtime/client_secrets`, WS `/v1/convai/realtime`; `eleven_realtime_v1_mini/max` | Session config → short-lived credential; PCM audio/events → conversation audio/events/tool calls | Д/?; public $0.08/connected min + input/output LLM tokens. Mini $0.20/$6 per 1M, Max $1.80/$9; burst дороже; в наших 11 не проверены | Быстрый голосовой интерфейс к продукту. OpenAI-compatible — протокол, не право/необходимость оплачивать OpenAI API. [Realtime guide][realtime] |
| **Speech Engine**: `/v1/speech-engine` CRUD/duplicate; upstream WS-протокол на **нашем** `wsUrl` (в reference `/speech-engine/upstream`) | ElevenLabs присылает transcripts серверу пользователя; сервер отвечает text/LLM stream → speech клиенту | Д/?; public $0.08/min, свои LLM затраты отдельно; default conversation 10 min, максимум 40 min; конкретная наша квота ? | Озвучить существующего помощника, оставив собственную логику. ElevenLabs — WS client для upstream; не отправлять upstream на vendor API как обычный TTS. [Speech Engine][speech-engine], [Upstream][upstream] |
| **Agents KB/RAG/tools/MCP**: `/v1/convai/knowledge-base` file/url/text/crawl/index/search; `/tools`; `/mcp-servers`; integrations | Документы/индекс/tool schemas/permissions → knowledge/tools, executions | Базовый KB/RAG доступен в Agents marketing; storage/index/LLM/tool расходы и плановые права зависят от режима — ? | Помощник отвечает по открытой инструкции; сторонние tools требуют самостоятельного ограничения действий. [Agents][agents], [KB API][kb-api], [MCP API][mcp-api] |
| **Agents tests / analysis / lifecycle**: agent-testing, run-tests, test-invocations, simulate-conversation; conversations analysis/evaluations/search; branches/versions/deployments/drafts/merge-proposals/procedures; triage tickets/users/tags | Config/tests/conversations → results, analytics, versioned configs, tickets | Нельзя считать test/simulate бесплатными: они могут использовать генерацию/LLM; часть lifecycle permissions/планов ? | Проверять, что голосовой помощник отвечает корректно до публикации; отдельная задача и бюджет. [Tests][agent-tests], [Simulate][agent-simulate], [Полный каталог](endpoint-catalog.md) |
| **Telephony / batch calling**: phone-numbers CRUD/v2 list, SIP outbound, Twilio outbound, batch-calling submit/status/cancel | Телефонный config/список вызовов → calls/events/audio | Agents usage + LLM; Twilio/SIP carrier оплачивается отдельно; Starter доступность конкретного канала ? | Согласованный входящий голосовой канал. Исследование не разрешает звонки людям или импорт номеров. [Agents][agents], [Telephony pricing][agents-pricing] |
| **Account / subscription / models**: `GET /v1/user`, `/v1/user/subscription`, `/v1/models` | Авторизация → metadata, tier/status, character_limit/count/reset, voice quotas, rates/capabilities | Д; чтение не генерирует аудио. API сохраняет legacy имена character для credits. Root проверил часть полей | Перед запуском оценить остаток, model_rates, лимиты. Не выводить secrets/account JSON в публичный отчёт. [User][user], [Subscription][subscription], [Models][models-api] |
| **Usage / request analytics**: `POST /v1/workspace/analytics/query/usage-by-product-over-time`, `/v1/workspace/analytics/requests`; legacy GET `/v1/usage/character-stats` | Фильтры/даты/group_by → табличные units/rows, per-request status/usage | Д/? permissions; эти POST — запросы аналитики, не генерации. Возможна группировка voice/model/key/voice_multiplier | Проверить реальные списания Sergey после разрешённого использования. Сейчас исторические личные данные не читались. [Usage][usage], [Requests][requests], [Analytics guide][analytics] |
| **History**: `GET /v1/history`, `/{id}`, `/{id}/audio`; `POST /v1/history/download`; DELETE | ID/filter → metadata/audio/zip | Д; повторная загрузка результата не новая генерация. Retention/retrieval SLA не установлены | Повторно скачать принятый звук без нового TTS. После удаления remote resource нельзя рассчитывать на его восстановление. [History][history] |
| **Ключи пользователя**: dashboard API Keys; `POST /v1/workspaces/api-keys/disable`, `/third-party-disabling` | Scopes, credit cap, expiry/IP allowlist → scoped key/config; disable → revoked | Д в рамках функций/прав плана; создание ключа не даёт новой квоты. Доступность отдельных advanced controls ? | Ограничить будущий backend только TTS/voices и лимитом credits; ключ хабу/браузеру не нужен. [Keys][keys], [Auth][auth] |
| **Frontend single-use tokens**: `POST /v1/single-use-token/{token_type}` | Backend-held key → одноразовый временный token нужного продукта | Д/? token type. Для batch_scribe contract 15 min; не переносить этот срок на все типы | Дать веб-диктовке временный доступ без основного ключа. Token не отменяет billing. [Tokens][tokens], [STT][stt] |
| **Service accounts / их ключи**: `/v1/service-accounts`, `/{user_id}/api-keys` CRUD/disable | Workspace/admin grants → service identity и keys | **Нет обычному Starter**: multi-seat customers/admin; per-key concurrency controls Enterprise | Корпоративная независимая сервисная учётка после смены плана. Не выдавать эти endpoints за CRUD обычных personal keys. [Service accounts][service-accounts] |
| **Workspace admin / webhooks**: `/v1/workspace` members/groups/invites/resources/audit-logs/auth-connections; `/v1/workspace/webhooks` CRUD; convai workspace settings/integrations/environments | Membership/permissions/hooks → resource state/events | Webhooks Д/?; multi-seat/SSO/audit/residency — соответствующие повышенные планы, не автоматически Starter. Цена admin operations не установлена | Принимать async STT/dub completion и вести права команды. Секрет webhook не публиковать. [Webhooks][webhooks], [Workspaces][workspaces], [Каталог](endpoint-catalog.md) |

У Agents API много вспомогательных ресурсов: в каталоге сохранены все индексированные routes, включая triage, users, workflow-related lifecycle, secrets **schema pages**, environments, integrations и analytics. Работник читал только их публичные описания; личные values, разговоры и secret stores не запрашивались. Reception.ai — отдельный готовый продукт, а не обещанная функция нашего Starter; его внешняя provisioning/подписка сюда не переносится. [Обзор продуктов][intro].

## 8. Лимиты, deprecated и восстановление

Public [Models concurrency][models] для Starter: Multilingual v2 3; Flash 6; batch STT 12; realtime STT 9; Music 2. Отдельно TTD WS 21 sessions. Dubbing self-serve — 3 jobs на модель, это не TTS-пул. Старый [429 FAQ][error429] пишет просто Starter 3: это неполная общая цифра, при планировании учитывать семейство и `maximum-concurrent-requests` ответа. Ни одна цифра не является результатом нашего нагрузочного теста.

| Устаревшее / конфликт | Текущее действие |
| --- | --- |
| `eleven_turbo_v2_5`, `eleven_turbo_v2`, `scribe_v1` прямо в Deprecated models | Новая работа: Flash 2.5/Flash v2/Scribe v2 соответственно. Устаревшее ≠ уже выключенное |
| `eleven_monolingual_v1`, `eleven_multilingual_v1`, ранний STS | Не выбирать для нового потока; legacy-упоминание не доказывает доступность аккаунту. Универсальную дату отключения docs не дают |
| `GET /v1/voices` в Legacy | Для полного поиска использовать пагинируемый `GET /v2/voices`; `GET /v1/voices/{id}` остаётся текущим |
| `/v1/text-to-voice/create-previews` Legacy | `/v1/text-to-voice/design`, затем save `/v1/text-to-voice` |
| `/v1/dubbing` и dubbing_id downloads Legacy | Новая модель project/language resources — `/v1/dubbing/project`; не смешивать формы данных |
| Старые примеры `/v1/speech-to-speech/{id}` | Текущий reference на странице speech-to-speech документирует **`/v1/voice-changer/{id}`**; alias совместимость старого пути без исполнения не установлена |
| `GET /v1/usage/character-stats` Legacy | Workspace analytics по продуктам/units; не путать имена characters с количеством исходных символов |
| `optimize_streaming_latency` deprecated | Не строить новый путь на нём; Flash/streaming и корректные полные фразы |
| `max_characters_request_free_user/subscribed_user` deprecated/not enforced | Брать `maximum_text_length_per_request` модели |
| STT `cloud_storage_url` deprecated | `source_url`; лимиты прямой загрузки и URL отдельно сверять |
| `allowed_to_extend_character_limit`, `max_character_limit_extension` legacy | Новый `max_credit_limit_extension`: `0` disabled, `"unlimited"` без cap. Root передал старые флаги false; новое поле не передавалось |
| Get voice `with_settings` ignored/deprecated; TTD `use_pvc_as_ivc` deprecated | Не использовать как гарантированный переключатель поведения |
| Music upload boolean `extract_composition_plan` deprecated | Выбирать соответствующий music model ID; формат plan v1 отличается от v2/v2.5 |
| Audio Native `image/small/sessionization` deprecated | Player settings; на Starter сам продукт недоступен |
| Overview TTD «no speaker limit» vs API max 10; v4 WS guide vs v3-only reference | Для реализации строгий endpoint contract; новинки требуют отдельного подтверждения |

Точные первичные ссылки для этих путей собраны в [endpoint-catalog.md](endpoint-catalog.md); deprecated **поле** в schema не делает автоматически deprecated весь endpoint. В manifest это явно названо `contains_deprecated_marker`.

Для будущей реализации: 401/403 — проверять права/план, 422 — payload/model/format/limit; 429 — ограничить параллелизм и различать concurrency/system_busy. Повтор после сетевого обрыва потенциально может создать второй оплаченный результат: сначала проверить сохранённый request/job ID, history/target status. Не предполагать идемпотентность POST, возврат средств за любой отказ или бесплатную отмену. Частично полученный stream не считать полным файлом. Для async проектов сохранять ID, принимать повторные webhook события идемпотентно; signed URL может устареть — повторно получить metadata вместо новой генерации. [429 FAQ][error429], [Dubbing project contract][dub-project], [Language targets][dub-language].

Overview TTS обещает до двух free regenerations при тех же данных, но точный API billing-контракт/автоматическое распознавание повторов для нашего аккаунта не подтверждены. **Обычный повтор POST не считать бесплатным.** Смена текста/настройки — новая генерация. [TTS capabilities][tts-overview].

## 9. Примеры запросов: только placeholders, не выполнялись

Команды иллюстрируют будущую интеграцию. Каждый POST генерации расходует квоту; эти блоки не выполнялись. `<VOICE_ID>` следует заменить выбранным публичным Sergey ID **только при реальном разрешённом запуске**; `<API_KEY>` — локально у владельца backend, не передавать хабу. Файлы-примеры не создавались.

```bash
# Чтение модели/лимита: только шаблоны.
curl --fail-with-body 'https://api.elevenlabs.io/v1/models' \
  -H 'xi-api-key: <API_KEY>'

curl --fail-with-body 'https://api.elevenlabs.io/v1/user/subscription' \
  -H 'xi-api-key: <API_KEY>'

# Одна генерация: аудио и character timestamps.
curl --fail-with-body -X POST \
  'https://api.elevenlabs.io/v1/text-to-speech/<VOICE_ID>/with-timestamps?output_format=mp3_44100_128' \
  -H 'xi-api-key: <API_KEY>' \
  -H 'Content-Type: application/json' \
  --data '{"text":"<NORMALIZED_RUSSIAN_SCRIPT>","model_id":"eleven_flash_v2_5","language_code":"ru"}' \
  --output '<TIMED_AUDIO_JSON_PATH>'

# STT существующей записи: отдельный оплачиваемый запрос.
curl --fail-with-body -X POST 'https://api.elevenlabs.io/v1/speech-to-text' \
  -H 'xi-api-key: <API_KEY>' \
  -F 'file=@<AUDIO_PATH>' -F 'model_id=scribe_v2' \
  -F 'language_code=ru' -F 'diarize=true'
```

Python без SDK, только иллюстрация той же генерации:

```python
import json
from urllib.request import Request, urlopen

payload = {
    "text": "<NORMALIZED_RUSSIAN_SCRIPT>",
    "model_id": "eleven_flash_v2_5",
    "language_code": "ru",
}
request = Request(
    "https://api.elevenlabs.io/v1/text-to-speech/<VOICE_ID>/with-timestamps"
    "?output_format=mp3_44100_128",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"xi-api-key": "<API_KEY>", "Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=60) as response:
    result = json.load(response)
# result["audio_base64"], result["alignment"], result["normalized_alignment"]
```

В этих примерах нет чтения `.env`, SDK init, настоящего ключа, вывода account JSON или вызова официального onboarding CLI. Ошибки/retry/хранение реализовывать только в отдельной согласованной задаче.

## 10. Что можно использовать и что требует решения

**Готово к использованию в пределах ранее разрешённого владельцем TTS-сценария:** известный Sergey, Flash 2.5 с переданной ставкой 0,5; HTTP MP3, character timestamps, предварительная нормализация текста. Это вывод о выборе, а не разрешение этого исследовательского воркера запускать генерации. Имплементационный worker уже получил выбор пользователя от root.

**Отдельная задача/решение:** качество на русском и бюджет A/B; переход на v3/v4/Multilingual; IVC и загрузка записей; remix с проверкой прав; STT/дополнительные опции и voice changer/isolation; Music и её лицензионный режим; Dubbing и каждый target; Agents/LLM/телефония; Flows image/video; finetune; платные top-ups/Auto Top Up; upgrade тарифа и необратимая смена legacy pricing. Ничего из этого не включается как fallback автоматически.

Starter **не даёт** создание PVC, Audio Native, Image/Video API (Pro+), service accounts, Enterprise ZRM/residency или realtime translation. [Data residency][residency] и `enable_logging=false` в TTS contract — Enterprise; на Starter нельзя обещать отсутствие хранения у вендора. Для нашей простой начитки передавать публичный сценарий; внутренние логи/секреты не являются входом для TTS.

[PAYG guide][payg] разрешает top-up и на Starter; legacy overage-флаги false этого не отменяют. Баланс подписки используется первым, затем PAYG. Минимальная покупка $5; Auto Top Up — отдельное списание. Ничего из этого здесь не включалось. **Сам факт действующей подписки не является разрешением на дополнительные платежи.**

## 11. Фактические проверки и оставшийся риск

- Прочитан локальный AGENTS.md; личные файлы, `.env`, логи и credentials не читались. Изменены только артефакты этой задачи.
- Из официального llms index прочитаны 592 API Reference pages: все вернули HTTP 200; выделены 400 уникальных method/path, 11 из Legacy. Чтение HTML/Markdown docs не вызывает API генерацию. Два пути Speech Engine извлечены отдельно из документации без предположения `/v1`.
- Сверены pricing/FAQ/модельные schema/контракты; противоречия чисел и прав сохранены в отчёте, а не «разрешены» догадкой.
- Подтверждение аккаунта/Sergey — только **root-reported private account check 25 Oct 2026**. Работник его независимо с ключом не повторял. Не доказаны фактическое списание, текущий остаток, качество русского аудио и availability каждой публичной новинки.
- Для документов выполнена локальная проверка JSON/ссылок/placeholders/секретоподобных строк; результаты записаны в [verification.md](verification.md). Python snippets проверяются синтаксически без исполнения запроса.
- Продуктовый Python не менялся и `app` не импортировался; абсолютный путь импортированного `app`: **не применимо, импорт не выполнялся**. Pytest/run_tests не запускались: это исследование без изменения исполняемого кода. Никакая альтернативная проверка не выдаётся за требуемый Python test suite.
- `git commit/push` запрещены ролью этой private copy; `.git`/remote не требуются. Платформа должна импортировать файлы и создать коммит на `task-V-1085/research-elevenlabs-api` после завершения. Локального commit SHA нет; требование «коммит перед DONE» здесь технически выполняет платформа, не работник.

## Первичные источники

Все ссылки ниже — официальные ElevenLabs; прочитаны **2026-10-25 UTC**, если не указана редакция документа. Страницы без даты публикации не выдаются за опубликованные именно в день исследования. Поисковые snippets использовались для обнаружения, актуальные открытые страницы/Markdown — для выводов. Сторонние обзоры, выдача reseller pricing и их samples в доказательство не принимались.

[intro]: https://elevenlabs.io/docs/overview/intro
[pricing]: https://elevenlabs.io/pricing
[api-pricing]: https://elevenlabs.io/pricing/api
[billing]: https://elevenlabs.io/docs/overview/administration/billing
[payg]: https://elevenlabs.io/docs/overview/administration/pay-as-you-go
[models]: https://elevenlabs.io/docs/overview/models
[models-api]: https://elevenlabs.io/docs/api-reference/models/list
[selection]: https://elevenlabs.io/docs/eleven-api/choosing-the-right-model
[latency]: https://elevenlabs.io/docs/eleven-api/concepts/latency
[tts-overview]: https://elevenlabs.io/docs/overview/capabilities/text-to-speech
[tts]: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
[timing]: https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps
[stream]: https://elevenlabs.io/docs/api-reference/text-to-speech/stream
[stream-timing]: https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps
[tts-ws]: https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input
[tts-multi]: https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-multi-stream-input
[ws-compare]: https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/tts-vs-ttd-websockets
[dialogue]: https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert
[dialogue-timing]: https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert-with-timestamps
[dialogue-ws]: https://elevenlabs.io/docs/api-reference/text-to-dialogue/ttd-websocket
[effects]: https://elevenlabs.io/docs/api-reference/audio-effects/get-catalog
[stt]: https://elevenlabs.io/docs/api-reference/speech-to-text/convert
[stt-overview]: https://elevenlabs.io/docs/overview/capabilities/speech-to-text
[stt-ws]: https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime
[alignment]: https://elevenlabs.io/docs/overview/capabilities/forced-alignment
[alignment-api]: https://elevenlabs.io/docs/api-reference/forced-alignment/create
[changer]: https://elevenlabs.io/docs/overview/capabilities/voice-changer
[changer-api]: https://elevenlabs.io/docs/api-reference/speech-to-speech/convert
[isolation]: https://elevenlabs.io/docs/overview/capabilities/voice-isolator
[isolation-api]: https://elevenlabs.io/docs/api-reference/audio-isolation/convert
[voice-get]: https://elevenlabs.io/docs/api-reference/voices/get
[voices]: https://elevenlabs.io/docs/api-reference/voices/search
[shared]: https://elevenlabs.io/docs/api-reference/voices/voice-library/get-shared
[multipliers]: https://elevenlabs.io/docs/help-center/product/voices/voice-library/what-are-custom-rates-and-credit-multipliers
[library]: https://elevenlabs.io/docs/eleven-creative/voices/voice-library
[ivc]: https://elevenlabs.io/docs/api-reference/voices/ivc/create
[slots]: https://elevenlabs.io/docs/help-center/account/general/how-many-voice-slots-do-i-get-per-tier-and-how-can-i-increase-it
[pvc]: https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/professional-voice-cloning
[design]: https://elevenlabs.io/docs/api-reference/text-to-voice/design
[design-guide]: https://elevenlabs.io/docs/eleven-creative/voices/voice-design
[remix]: https://elevenlabs.io/docs/overview/capabilities/voice-remixing
[remix-api]: https://elevenlabs.io/docs/api-reference/text-to-voice/remix
[sfx]: https://elevenlabs.io/docs/overview/capabilities/sound-effects
[sfx-api]: https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert
[music]: https://elevenlabs.io/docs/overview/capabilities/music
[music-api]: https://elevenlabs.io/docs/api-reference/music/compose
[music-plan]: https://elevenlabs.io/docs/api-reference/music/create-composition-plan
[music-inpaint]: https://elevenlabs.io/docs/eleven-api/guides/how-to/music/inpainting
[music-upload]: https://elevenlabs.io/docs/api-reference/music/upload
[video-music]: https://elevenlabs.io/docs/api-reference/music/video-to-music
[stems]: https://elevenlabs.io/docs/api-reference/music/separate-stems
[finetunes]: https://elevenlabs.io/docs/api-reference/music/finetunes/create
[music-terms]: https://elevenlabs.io/music-terms
[dubbing]: https://elevenlabs.io/docs/overview/capabilities/dubbing
[dub-project]: https://elevenlabs.io/docs/api-reference/dubbing/create-project
[dub-language]: https://elevenlabs.io/docs/api-reference/dubbing/language-targets/create-language-target
[dub-regenerate]: https://elevenlabs.io/docs/api-reference/dubbing/target-transcript/regenerate-target
[dub-legacy]: https://elevenlabs.io/docs/api-reference/legacy/dubbing/create
[translation]: https://elevenlabs.io/docs/api-reference/realtime-translation/v-1-translation-realtime
[studio]: https://elevenlabs.io/docs/api-reference/studio/add-project
[podcast]: https://elevenlabs.io/docs/api-reference/studio/create-podcast
[pronunciation]: https://elevenlabs.io/docs/eleven-api/guides/how-to/text-to-speech/pronunciation-dictionaries
[dictionary]: https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/create-from-rules
[native]: https://elevenlabs.io/docs/eleven-creative/audio-tools/audio-native
[visual]: https://elevenlabs.io/docs/overview/capabilities/image-video
[flows-video]: https://elevenlabs.io/docs/api-reference/flows/video/create
[flows-image]: https://elevenlabs.io/docs/api-reference/flows/image/create
[assets]: https://elevenlabs.io/docs/api-reference/assets/create
[templates]: https://elevenlabs.io/docs/api-reference/flows/templates/runs/create
[agents]: https://elevenlabs.io/docs/eleven-agents/overview
[agents-pricing]: https://elevenlabs.io/pricing/agents
[agent-ws]: https://elevenlabs.io/docs/eleven-agents/libraries/web-sockets
[realtime]: https://elevenlabs.io/docs/eleven-agents/guides/openai-realtime-compatibility
[speech-engine]: https://elevenlabs.io/docs/overview/capabilities/speech-engine
[upstream]: https://elevenlabs.io/docs/api-reference/speech-engine/speech-engine-upstream
[kb-api]: https://elevenlabs.io/docs/api-reference/knowledge-base/create-from-text
[mcp-api]: https://elevenlabs.io/docs/api-reference/mcp/create
[agent-tests]: https://elevenlabs.io/docs/api-reference/tests/create
[agent-simulate]: https://elevenlabs.io/docs/api-reference/agents/simulate-conversation
[user]: https://elevenlabs.io/docs/api-reference/user/get
[subscription]: https://elevenlabs.io/docs/api-reference/user/subscription/get
[usage]: https://elevenlabs.io/docs/api-reference/analytics/workspace/usage
[requests]: https://elevenlabs.io/docs/api-reference/analytics/workspace/requests
[analytics]: https://elevenlabs.io/docs/overview/administration/usage-analytics
[history]: https://elevenlabs.io/docs/api-reference/history/list
[keys]: https://elevenlabs.io/docs/overview/administration/workspaces/api-keys
[auth]: https://elevenlabs.io/docs/api-reference/authentication
[tokens]: https://elevenlabs.io/docs/api-reference/tokens/create
[service-accounts]: https://elevenlabs.io/docs/overview/administration/workspaces/service-accounts
[webhooks]: https://elevenlabs.io/docs/api-reference/webhooks/create
[workspaces]: https://elevenlabs.io/docs/overview/administration/workspaces/overview
[residency]: https://elevenlabs.io/docs/overview/administration/data-residency
[error429]: https://elevenlabs.io/docs/help-center/technical/api-error-code-429

[character-count]: https://elevenlabs.io/docs/help-center/account/general/how-is-character-length-calculated
