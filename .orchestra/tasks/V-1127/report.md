# V-1127 — Pro API credits, data-sharing tokens, SentinelX

Наблюдение: 2026-10-29 UTC. **RESEARCH ONLY / RESEARCH DONE.**

Полезный механизм подтверждён: подходящая подписка даёт отдельный API-грант. Доступность суточной льготы конкретному аккаунту, совместимость гранта с её требованием баланса и бесплатность инструментального агентного трафика **не установлены**. SentinelX не подтверждает обещание бесконечных лимитов. Реализация и активация не выполнялись.

## Таблица утверждений

Обозначения источников раскрыты ссылками ниже; описание происхождения и короткие дословные доказательства — в [sources.md](sources.md). «Не проверено» относится к аккаунту пользователя, а не к наличию публичного документа. Количество токенов не означает RPM/TPM, контекст или денежный баланс.

| mechanism | claim | official URL + observed date | exact supported fact | eligibility / account unknown | model IDs | token counting / input-output / cached / tool use | reset / time | overage behavior | data / shared scope | what source does NOT establish |
|---|---|---|---|---|---|---|---|---|---|---|
| Подписочный API-грант | Pro даёт API-кредиты | [S1], 2026-10-29; запуск [S10] 2026-10-28 | Pro $100/$200/$500 → соответственно $100/$200/$500 за цикл; Business Standard/Premium → $20/$100 за оплачиваемое место, общий месячный потолок $500 | Оплаченная подписка ≥7 дней; владелец подписки/workspace и API-организации; одинаковый email. Личный допуск не проверен | Это денежный грант, не список бесплатных моделей | Расход по API-тарифам | Первый грант пропорционален остатку цикла; затем при продлении; истекает в конце цикла, переноса нет. Annual Business: годовая выдача | См. следующую строку | Только связанная API-организация и её project keys; data-sharing не назван условием | Не доказывает положительный баланс по условиям S2 или повышение usage tier |
| Расход гранта | Можно строить API-агентов | [S1], 2026-10-29 | Responses, Agents с sandbox, Decisions, Realtime/GPT-Live, Images, встроенные tools/storage покрываются. Codex через API keys исключён | Активные бесплатные credits позволяют API без payment method; аккаунт не открыт | Доступность модели отдельно | Денежная оплата допустимого API-трафика, включая tools | Цикл подписки | Сначала free credits, затем purchased; без остатка HTTP 429 / `credit_balance_exhausted` | Сам грант не включает передачу данных для обучения | Не увеличивает ChatGPT/signed-in Codex allowance; исключение Codex не означает запрет generic Responses с кодом |
| Data-sharing | Суточные токены | [S2], 2026-10-29 | Build: 250K/2.5M; Launch/Grow: 1M/10M; два общих по группе счётчика организации | Offer+owner opt-in+положительный баланс; личный статус неизвестен | Группы A/B ниже | Input+output; cached/tool eligibility не уточнены | 00:00 UTC ежедневно; прекращение программы — уведомление за 30 дней | Пересекающий квоту запрос целиком платный; несогласованность примеров ниже | Включённые проекты; Enterprise/ZDR исключены | Ни безлимит, ни гарантированная льгота Responses/function-calling |
| API usage tier | Грант автоматически даёт большую квоту | [S3], 2026-10-29 | Build/Launch/Grow: purchases $5/$100/$500; approved monthly usage $500/$5K/$200K | Уровень организации неизвестен; grant ≠ доказанная purchase | Лимиты зависят от модели и service tier | RPM/TPM отдельно; cached input учитывается в TPM [S8] | Минутные rate limits и месячный usage limit — разные пределы | Rate limit может отказать до исчерпания денег | Org/project, возможны shared model limits | Нельзя переводить сумму гранта в tier. Старые числовые tiers не каноническое текущее название |
| Контроль расходов | Бюджет всегда останавливает запросы | [S4], 2026-10-29 | Alert только уведомляет. Enforced hard limit org/project останавливает запросы с соответствующим 429 | Нужны полномочия; настройки не проверялись | Все затронутые маршруты проекта/организации | Денежный учёт; не токенный суточный лимит | Месячный цикл; propagation не мгновенна | Возможен небольшой перерасход; нет гарантии нулевого превышения | Org hard limit охватывает все проекты | Не доказывает, что alert является cap, или что действующий cap настроен |
| Function calling | Локальные инструменты и inference — разные расходы | [S5], [S6], 2026-10-29 | Функции выполняет приложение; схемы — input tokens. Built-in tools имеют свои charges, их токены тарифицируются моделью | Общий API-контракт; incentive applicability не доказана | `gpt-6-astra`, `gpt-6.1-sol`: tool calling требует Responses | Генерация аргументов/передача результатов — модельный трафик; запуск локальной функции — работа приложения | Каждый шаг цикла — новый API-вызов | Обычная тарификация; расходы внешней функции отдельно | Содержимое tool-result уходит модели, если приложение его передаёт | Общая токенная тарификация не определяет смысл исключения tool use в S2 |
| Signed-in ChatGPT/Work/Codex | Плагин создаёт дополнительную квоту | [S11], [S12], 2026-10-29 | Work и Codex делят credits/usage; остаются продуктовые и fair-use пределы | Зависит от плана/surface/workspace; аккаунт неизвестен | Выбранная модель и surface, не имя плагина | Подписочный учёт отличается от API billing | По продуктовому allowance | Достижение allowance не покрывается API-грантом автоматически | Правила подключённого продукта | Нельзя считать обычный Chat, Work и Codex одним режимом или обещать независимый безлимит |
| SentinelX | «Плагин бесконечных лимитов» | [S13], 2026-10-29 | OpenAI listing: PensaInfra, управление хостами, файлы/скрипты/сервисы, allowlist, OAuth; примеры ведут в Work | Доступ по плану и настройкам; подключения не было | Плагин не задаёт inference-модель | Host-tool bridge, не документированный inference endpoint | Квоты OpenAI и хоста отдельно | Обход лимитов не заявлен в карточке | Третья сторона и хостовые права — отдельная граница | MCP/OpenCode endpoint не равен OpenAI inference API и не даёт токены |

## Точные группы моделей S2

**A — 1M / 250K:** `gpt-6.1-sol`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-sol`, `gpt-5.5-2026-04-23`, `gpt-5.4-2026-03-05`, `gpt-5.2-2025-12-11`, `gpt-5.1-2025-11-13`, `gpt-5.1-codex`, `gpt-5-codex`, `gpt-5-2025-08-07`, `gpt-5-chat-latest`, `gpt-4.5-preview-2025-02-27` (закрыта), `gpt-4.1-2025-04-14`, `gpt-4o-2024-05-13`, `gpt-4o-2024-08-06`, `gpt-4o-2024-11-20`, `o3-2025-04-16`, `o1-preview-2024-09-12`, `o1-2024-12-17`.

**B — 10M / 2.5M:** `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.4-mini-2026-03-17`, `gpt-5.4-nano-2026-03-17`, `gpt-5.1-codex-mini`, `gpt-5-mini-2025-08-07`, `gpt-5-nano-2025-08-07`, `gpt-4.1-mini-2025-04-14`, `gpt-4.1-nano-2025-04-14`, `gpt-4o-mini-2024-07-18`, `o4-mini-2025-04-16`, `o1-mini-2024-09-12`, `codex-mini-latest`.

Следовательно, Luna без версии неоднозначна. `gpt-6.1-terra`, выпущенная 26 октября [S10], в прочитанном перечне отсутствует; включение по семейному имени не доказано. Перечень содержит закрытую модель: наличие строки не доказывает доступность endpoint сегодня.

Для масштаба, публичные **Standard** rate limits [S3] приведены ниже. Это не измеренные лимиты аккаунта; Ultrafast и long-context ограничения проверяются отдельно. Free tier в S3 имеет approved usage $100/месяц при допустимой географии; это потолок использования, не выдача $100.

| Tier | Astra/Sol/Terra RPM; TPM | Luna RPM; TPM |
|---|---|---|
| Build | 5 000; 1 000 000 | 5 000; 2 000 000 |
| Launch | 10 000; 4 000 000 | 10 000; 10 000 000 |
| Grow | 15 000; 40 000 000 | 30 000; 180 000 000 |

## Неразрешённые вопросы и противоречия

1. **Грант → положительный баланс:** S1 разрешает API на бесплатных credits, но S2 не определяет тип необходимого баланса. Ни достаточность Pro-гранта, ни обязательность отдельной покупки для incentive из этих двух документов не следуют. S3 требует purchases для tier; сумма гранта не доказывает Launch. Аккаунт и поддержку не опрашивал.
2. **Function calling → complimentary:** S5 подтверждает обычный агентный цикл, а S1 покрывает Responses денежным грантом. Однако S2 исключает tool use без определения границы. Возможны разные трактовки: только инструментальные charges либо также трафик запросов с tools. Источники не позволяют выбрать одну. Нельзя обещать бесплатность function schemas, arguments, tool-result traffic, built-in tools или всех Responses; нельзя и объявлять любой локальный агент запрещённым для денежного гранта. Список Codex-моделей S2 не отменяет отдельное исключение Codex API-key usage из S1.
3. **Cached:** S8 разделяет ordinary/cached/cache-write input и подтверждает TPM-учёт кеша. Его ценовые коэффициенты не определяют incentive-счётчик. Нельзя считать суточную квоту по cache-discounted dollars или обещать кеш без расхода квоты. Для reasoning/cache-write/инструментальных токенов точная формула incentive не установлена.
4. **Overage S2:** пример 750K+500K называет 250K превышения, но правило целого запроса и таблица 975K+30K требуют платить за пересекающий запрос полностью. Это текстовая несогласованность; более подробное правило безопаснее для оценки расходов, но реальный billing не измерен. Суточная льгота сама по себе не останавливает платный трафик.
5. **Данные:** S2 исключает fine-tuned models, training, evals и tool use из токенной льготы. Sharing используется для улучшения/обучения; нужны права на данные, чувствительные/конфиденциальные материалы передавать нельзя. По S9 API по умолчанию не обучает модели без opt-in; это не обещание нулевого хранения. Репозиторий, логи и ответы tools нельзя автоматически объявить допустимыми для sharing.

## Применимость к прочитанному коду Orchestra

Это статическое чтение исходников в worker-copy, не проверка работающего процесса или приватного каталога. Версия Git не установлена: `.git` отсутствует. Хеши прочитанных файлов — `localSources` в [source-observations.json](source-observations.json). В конфиги, credential stores, БД и пользовательские аккаунты не заходил.

| Точка и место | Уже есть / возможное применение / не принимать | Важность и возможная польза | Стоимость переноса / нужная проверка / внешняя граница |
|---|---|---|---|
| `app/models.py:104–120`, `app/runtime_registry.py:363`, `app/backend_codex.py:2655` | **Уже есть:** GPT Astra/Luna/Sol → runtime `codex`; backend использует подписочную авторизацию. **Не принимать:** считать это расходом Pro API-гранта | Высокая: предотвращает ошибочную оценку новой доступной квоты. Benefit NOT MEASURED | Для API нужен отдельный явно проверенный путь; замена credentials существующего Codex не доказана совместимой и не разрешена |
| `app/models.py:692–708`, `app/mcp_stdio.py:3681–3684` | **Уже есть:** `billing='api_credit'` только для Claude; обычный agent dispatch допускает hub. **Не принимать:** передавать OpenAI-грант через одноимённый флаг | Высокая: это реальный admission, а не недостаток названия. Benefit NOT MEASURED | Нужны отдельное решение владельца и проверка допустимости маршрута; молча ослаблять правило нельзя |
| `app/runtime_registry.py:350`, `app/runtime_registry.py:318`, `app/backend_harness.py:232–250`, `app/harness/llm.py:608` | **Уже есть:** Harness → GigaChat либо OpenRouterClient; OpenRouter base URL и `/chat/completions`. **Возможное применение:** собственный API-loop как отдельная будущая работа, прямого production Responses adapter не найдено | Высокая: Astra/Sol требуют Responses для tools [S5]. Benefit NOT MEASURED | Простая смена base URL не переносит Responses events, reasoning/tool state, resume, cancellation, schema и billing; это контрактная работа, не готовый переключатель |
| `app/models.py:536–580`, `app/model_catalog.py` | **Уже есть:** OpenRouter допускает точные `:free` и именованные paid routes, с live-catalog/tool checks. **Не принимать:** считать OpenRouter вызовом связанной OpenAI API-организации | Высокая: чужой биллинг не доказывает расход собственного OpenAI-гранта. Benefit NOT MEASURED | Не расширять paid allowlist и не обходить catalog gate; API-key/organization принадлежность требует проверки в отдельной авторизованной задаче |
| `app/harness/loop.py:340–395`, `app/harness/prompts.py`, `app/harness/mcp.py` | **Уже есть:** tool schemas, agent loop, отдельное исполнение tools. **Возможное применение:** повторно использовать концепцию orchestration, не гарантируя wire compatibility | Средняя: сокращает возможный объём новой реализации. Benefit NOT MEASURED | Нужны meaningful offline fixtures для Responses continuation, multiple calls, recovery/cancellation; передача tool-output за новую границу требует решения по данным |
| `app/claude_api_credits.py`, `app/db.py:2590`, `app/backend_harness.py:85–91` | **Уже есть:** Claude-specific credit accounting; режимы subscription/api_credit/openrouter_credit/free. **Не принимать:** исторический Claude balance или API-equivalent cost за OpenAI entitlement | Высокая: деньги, quota tokens и подписка учитываются по разным договорам. Benefit NOT MEASURED | Для будущего OpenAI-пути отдельно установить grant expiry, org/project, incentive attribution, whole-request charge и terminal billing errors; стоимость такого учёта не оценивалась |
| `app/backend_hub.py:32–40`, `app/backend_hub.py:302` | **Уже есть:** `hubsol` ведёт к hub runtime и его Codex-модели. **Не принимать:** приписывать текущему запуску расход личного API-гранта | Высокая: usable hub accounts не являются доказательством account-specific eligibility. Benefit NOT MEASURED | Состояние/биллинг чужого пула не исследовались; ничего туда не переключал |
| `app/runtime_registry.py:214–278`, `app/harness/mcp.py`; V-1122 | **Уже есть:** MCP-подключения. **Возможное применение SentinelX:** узкий дополнительный host-tool bridge; **не принимать:** замену inference provider или «infinite limits» | Условная/низкая для данной задачи: кредитам не помогает. Benefit NOT MEASURED | Сторонний hub, OAuth, политика всех write/script paths, resume и права ОС требуют отдельного рассмотрения; установка не разрешалась |

По доступному `app/**/*.py` поиск `OPENAI_API_KEY`, `api.openai.com`, `responses.create`, `/responses`, `api_credit` не обнаружил прямого рабочего OpenAI API-кредитного маршрута; последнее имя относится к Claude. Статический отрицательный поиск не исключает внешнюю конфигурацию или динамически зарегистрированный plugin. `register_runtime()` допускает расширения; публичные файлы не устанавливают состав живого процесса.

## SentinelX: ограниченное повторное уточнение

Карточка [S13] повторно открыта; источник PensaInfra и назначение управления хостом подтверждаются. Исследование публичного кода повторно не проводилось: использован существующий [V-1122/report.md](../V-1122/report.md), особенно разделы о quota и `local_api`. Возможность вызывать OpenCode/его локальный API через bridge означает доступ к инструментам приложения; из этого не следует предоставление inference OpenAI, API-credits или независимого allowance. Подмена Chat на Work меняет применимый контракт: [S11] явно объединяет Work/Codex usage. Утверждение о конкретной старой сессии без её model/surface/usage остаётся непроверенным.

## Фактические проверки и оставшиеся ограничения

- Открыл официальные страницы через веб-инструмент; основные developers/Learn документы дополнительно получил напрямую публичным GET. Сборщик `node .orchestra/tasks/V-1127/collect-sources.mjs` выполнен, результат: 10 HTTP 200 и 3 HTTP 403; тело/хеш 403 не выдаются за статью. Это сбор доказательств, не тест поведения приложения.
- Сопоставил S1 с текущим Markdown и S10; S2 — с отдельно открытым старым help-lb снимком. Различия происхождения описаны в sources.md. Прямой доступ к двум Help-страницам и listing не удался; веб-копии не являются независимым live HTTP подтверждением.
- Прочитал перечисленные source locations и существующий V-1122; в итоговых артефактах нет сырых source dumps, приватных путей, аккаунтных данных или ключей. Дословные выдержки ограничены 25 словами на источник.
- Перед завершением повторно сравнил SHA-256 11 исходных файлов с manifest: изменений нет. Проверил четыре новых артефакта чтением и поиском приватных путей/форм ключей; совпадений не было. Git diff недоступен без `.git`; собственные изменения ограничены каталогом V-1127.
- Код приложения не менялся; `app` не импортировался. Pytest/full-suite не запускались: задача документальная; поведенческих проверок API/аккаунта нет. Provisioned uv не понадобился; другой интерпретатор за требуемый runner не выдаётся.
- Не было inference/model calls, evals, reviews, paid requests, opt-in, account linking, установки, OAuth, изменения настроек, рестартов, Git-операций или публикации сайта. Никакой защищённый контекст не загружался.
- Импорт артефактов брокером в основной worktree этим отчётом не подтверждён. Остаток исследования — закрытые account-specific условия и неоднозначная граница tool use; их нельзя снять статическим чтением. Любая будущая проба требует отдельного разрешения на аккаунт, расходы и данные.

**RESEARCH DONE.**

[S1]: https://developers.openai.com/api/docs/guides/chatgpt-api-credits
[S2]: https://help.openai.com/en/articles/10306912-sharing-feedback-evaluation-and-fine-tuning-data-and-api-inputs-and-outputs-with-openai
[S3]: https://developers.openai.com/api/docs/guides/rate-limits
[S4]: https://developers.openai.com/api/docs/guides/spend-limits
[S5]: https://developers.openai.com/api/docs/guides/function-calling
[S6]: https://developers.openai.com/api/docs/pricing
[S8]: https://developers.openai.com/api/docs/guides/prompt-caching
[S9]: https://developers.openai.com/api/docs/guides/your-data
[S10]: https://developers.openai.com/api/docs/changelog
[S11]: https://learn.chatgpt.com/docs/enterprise/work-admin-faq
[S12]: https://learn.chatgpt.com/docs/pricing
[S13]: https://openai.com/business/plugins/sentinelx/
