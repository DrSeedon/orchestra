# V-1085 — практическая карта ElevenLabs

Срез **2026-10-25 UTC**. Подробные условия, первичные ссылки и неизвестное: [report.md](report.md). Все выводы ниже — рекомендации; исследование не запускало генерацию и не меняло реализацию.

| Задача | Выбор | Статус / цена / следующий шаг |
| --- | --- | --- |
| Русская озвучка видео | **Sergey + `eleven_flash_v2_5`**, HTTP `with-timestamps`, MP3 44.1 kHz/128 kbps | Root подтвердил active Starter, Flash TTS и fine-tuned совместимость голоса. ≈0,5 credits/учитываемый символ; quality на нашем тексте не измерено |
| Английская версия собственного сценария | Тот же Flash 2.5, EN-текст и `language_code=en` | Проверить EN-подачу Sergey; native EN voice — отдельный выбор, возможна иная надбавка |
| Субтитры к только что синтезированной речи | Character alignment из `with-timestamps` → локально SRT/VTT | Не запускать STT того же звука без необходимости; обработка слов/сегментов на стороне монтажа |
| Числа, даты, аббревиатуры по-русски | Нормализовать текст до TTS, alias dictionary | Flash 2.5 normalization `on` не обещать Starter; русские phoneme dictionaries для него не поддержаны |
| Неясное ударение/неразборчивая фраза | Правка текста/alias, затем ограниченное сравнение Multilingual/v3/v4 | Отдельный бюджет A/B; superiority Turbo на русском не доказана; Turbo 2/2.5 официально deprecated |
| Несколько актёров | Text to Dialogue, ≤10 voices/≤2 000 chars на запрос | Другая модель/цена/права; не делать fallback автоматически |
| Субтитры записанного видео | Scribe v2; если transcript готов — Forced Alignment | Public API $0.22/hour; наш credit rate неизвестен. Add-ons/каждый канал могут увеличить счёт |
| Живая диктовка/субтитры | Scribe v2 Realtime WS | Public $0.39/hour; нужна отдельная реализация и проверка квоты |
| Очистка записанного микрофона | Voice Isolator | Duration billing; public $0.12/min; сначала оценить необходимость, артефакты не измерены |
| Сохранить собственную подачу, изменить тембр | Voice Changer `/v1/voice-changer/{voice_id}` | Public $0.12/min; ≤5 min/segment; не переводит текст |
| Эффект/атмосфера к видео | Sound Effects | Explicit duration: docs 40 credits/s; auto ≈200/gen FAQ; public API иначе в $/min. Точный account режим сначала выяснить |
| Фоновая музыка | Music API возможен на Starter | **Отдельное решение о лицензии**: Starter — individual use, без streaming distribution, исключения film/TV/radio/Studio Games. Публичные лимиты 17 и 40 min расходятся |
| Перевести готовый ролик с голосами | Dubbing project API | Отдельный бюджет; create уже оплачивает минимум один язык. V2 редактирование transcript/regenerate — Enterprise; не обещать на Starter |
| Голосовой агент/телефония | ElevenAgents / Realtime / Speech Engine | Другой режим billing: call/connected minutes, LLM и carrier отдельно. Не следует автоматически из покупки TTS Starter |
| Сделать собственный клон | IVC, только с правами на запись | Starter допускает; upload/verification — отдельное действие. Создание PVC требует Creator+ |
| Генерировать видеоряд/картинки API | Flows Image/Video | **API требует Pro+**; наличие веб-инструмента в Starter не означает API-доступ |
| Корпоративные identity, residency, zero-retention | Service accounts / Enterprise features | На обычном Starter не обещать; требуется изменение плана/договора |

## Подтверждённый ресурс и расчёт

- Пользователь выбрал **Sergey - Rich, Engaging and Captivating**; публичный library `voice_id=XuEV9VY3VUASYgJVNBh0`.
- Root-reported private account check **25 Oct 2026**: Flash `character_cost_multiplier=0.5`, `cost_discount_multiplier=1.0`, хотя `token_cost_factor=1.0`; Sergey `sharing.rate=1.0`, `financial_rewards_enabled=false`, Flash fine-tuned available.
- По Shared Voices API `rate` — multiplier. Сохранённый `sharing.rate=1.0` интерпретируем как нейтральный: **0,5 × 1 = 0,5**, а не 1,5. Schema вложенного sharing менее точная, поэтому это вывод по метаданным, без собственной оплаченной проверки списания.
- 1 200 учитываемых символов ≈600 credits, 10 000 ≈5 000. 30 000 свободных credits условно дают 60 000 chars; фактический остаток и оплаченная цена не передавались.
- Root: оба legacy extension flags false. PAYG/Auto Top Up — отдельные механизмы, их состояние неизвестно; их нельзя включать без отдельного разрешения.

## Что поручить следующему этапу

1. Реализовать только согласованный TTS-сценарий с выбранными ID, предварительным бюджетом по окончательному тексту, сохранением принятого звука и timing.
2. Проверить небольшой русский фрагмент по ранее выданному разрешению на расход. Отчёт не содержит samples и не выдаёт vendor claims за результаты прослушивания.
3. При обрыве запроса сверять job/history/usage перед повтором: повтор POST может стоить ещё одну генерацию. Не полагаться на «две бесплатные regeneration» без подтверждения именно API-пути.
4. Остальные продукты рассматривать отдельно: полезность не является разрешением на upload, генерацию, платный fallback, звонки, top-up или upgrade.

Ключ хабу не нужен; read-only результаты root достаточны для этого исследования. Работник не запрашивал ключ, `.env`, логи или личные файлы.
