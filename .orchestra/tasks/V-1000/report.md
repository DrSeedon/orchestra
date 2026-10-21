# V-1000 — Gemini CLI on Jio Google AI Pro: доступ остановлен до пробы

Проверка: 2026-10-21, VPS/worktree `/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker`.

## Результат

`gemini` на VPS не установлен (`command -v gemini` не нашёл исполняемый файл). В npm registry опубликован `@google/gemini-cli@0.65.0` (`npm view @google/gemini-cli version`), Node.js 20.20.2 и npm 10.8.2 доступны. Значит CLI устанавливаем, но он не настроен для запуска здесь.

В `~/.gemini` отсутствуют стандартные `oauth_creds.json` и `google_accounts.json`; найденное состояние относится к `antigravity-cli`, а не подтверждает авторизацию Gemini CLI или Jio-аккаунта. Содержимое credential-файлов не читалось. Без интерактивного Google OAuth реальная проба невозможна; login не запускался и обход авторизации не предпринимался. API key не использовался.

Чтобы продолжить авторизацию на VPS, владелец должен выполнить в интерактивном SSH-терминале под своим обычным Unix-пользователем:

```sh
npx --yes @google/gemini-cli@0.65.0
```

Команду выполнить в интерактивном SSH-терминале на VPS под обычным Unix-пользователем. В onboarding выбрать вход через Google и войти именно в Google account, на котором активирован Jio-promo Google AI Pro. В браузере завершить показанный CLI OAuth flow и вернуться в тот же терминал. Это ожидаемое действие владельца; до его выполнения headless trial не запускался.

Есть существенное ограничение: прежнее исследование #249 содержит официальную документацию Google о прекращении обслуживания Gemini CLI для consumer Gemini Code Assist / Google AI Pro / Ultra с 18.06.2026, включая запрет нового `Login with Google`; при этом Standard/Enterprise остались поддержаны. Поэтому запуск команды может показать, что consumer login уже недоступен. Jio-анонс называл AI Pro преимущества в Gemini app, но не устанавливал исключение для CLI. Этот вывод и entitlement gap остаются актуальны; Jio-подписка сама по себе не доказывает доступ к Gemini CLI. Источники, уже проверенные в #249: [официальное уведомление о deprecation](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en), [анонс Jio Google AI Pro](https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/).

## Что из #249 остаётся в силе

Читал артефакты из истории main: `docs/tasks/249/google-source-matrix.md`, `research.md`, `experiment-protocol.md` и замороженный `plan.md` из коммитов `8001d4a`, `892884a`, `1f593c0` (в текущем дереве они лежат в `docs/tasks/249/`, а не `.orchestra/tasks/249/`). Сохраняют силу: consumer Gemini CLI был объявлен снятым; Jio→CLI/Code Assist entitlement не был подтверждён; Antigravity CLI был отдельным кандидатом без API key; его ранее измеренные свойства и ограничения относятся к Antigravity, не к Gemini CLI. В частности, прежний Antigravity batch потратил около 16 процентных пунктов weekly quota на 13 коротких результатов — это не оценка ёмкости Gemini CLI.

## Не измерено

Условие задания требует остановиться при необходимости интерактивного Google login. Поэтому нет headless task, данных о Gemini CLI model, wall time, tokens, лимитах или расходе подписки. Интеграционные швы Orchestra (ACP/app-server, quota gate, usage, MCP, sandbox) не анализировались; capacity и вывод «добавлять ли пул» по Gemini CLI остаются не измеренными. Продолжение возможно после интерактивной авторизации владельца и только если Google реально допускает Jio-account inference в Gemini CLI. Никаких изменений `app/`, платных API-вызовов или рестартов не было.

## Продолжение V-1000: Antigravity CLI

Проверка VPS и ноутбука через reverse SSH tunnel: 2026-10-21. Ноутбук проверен read-only по skill `laptop-access`.

### Установка, версия и Jio-авторизация

- На VPS `agy` не находится в `PATH` и отсутствует в обычных местах установки (`~/.local/bin/agy`, `/usr/local/bin/agy`, `/usr/bin/agy`, `/opt/antigravity/bin/agy`). В `~/.gemini/antigravity-cli/bin/` есть вспомогательные `agentapi` и `webm_encoder`, но нет CLI executable. Канонический `~/.gemini/antigravity-cli/antigravity-oauth-token` отсутствует.
- На ноутбуке бинарник установлен: `/home/maxim/.local/bin/agy`, версия **1.1.13**. На ноутбуке каталог `~/.gemini/antigravity-cli` существует, но канонический OAuth token отсутствует; имя token-файла не найдено среди файлов каталога. Содержимое credential-файлов и логов не читалось.
- Следовательно, сейчас ни на одной из двух машин не подтверждена авторизация, тем более Jio-account. На ноутбуке интерактивная авторизация потребовала бы команды `~/.local/bin/agy` из обычного терминала и входа именно Google account, где активирован Jio-promo AI Pro; первый вход проходит через browser OAuth и controlling TTY. Не запускал её. Важное уже установленное ограничение: #249 ранее проверил этот же Jio AI Pro account на Antigravity и получил `Eligibility check failed ... not currently available in your location`; покупка Pro не сняла country gate. Повторный вход не гарантирует, что задача сможет исполниться.

### Живая проба

Не запускал inference: нет OAuth credentials, а Jio account уже дал eligibility error в #249. Поэтому для текущего Jio subscription: success — нет подтверждённого успешного запуска; wall time/model/tokens — не измерялись; новый quota delta — не измерен. Нельзя трактовать существующий state directory как login.

### Стоимость интеграции по текущему коду

Antigravity не говорит ни ACP, ни Codex app-server JSON-RPC: #249 измерил `agy --output-format stream-json` как NDJSON с отдельными `init`/`step_update`/`result` событиями и отдельными tool/MCP шагами. Значит нужен специализированный JSONL subprocess adapter, близкий по жизненному циклу к `BackendLike` per-turn runtime, но без переиспользования RPC-протокола Codex/Grok. `BackendLike` требует `connect/send/events/interrupt/disconnect` ([backend_protocol.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/backend_protocol.py:8)); capabilities регистрируются через `RuntimeDefinition` ([runtime_registry.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/runtime_registry.py:29), builtin registry сейчас содержит Claude/Codex/Grok/Harness в строках 331–383). Парсер должен переносить JSONL stream/tool lifecycle и terminal errors в `AgentEvent`; план #249 уже определял этот контракт.

Минимально обязательные seams:

1. **Runtime/model catalogue.** Добавить runtime и namespaced model IDs, provider metadata, context cap с честной неизвестностью. Каталог валидирует и runtime, и provider ([models.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/models.py:450)). Цены не выдумывать: подписочный расход не имеет подтверждённой долларовой цены.
2. **Quota gate и usage telemetry.** Сейчас `_model_target()` знает только Anthropic/Codex и классифицированный Grok/Harness; Antigravity без нового mapping получает `runtime ... has no worker quota policy` ([quota_gate.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/quota_gate.py:853)). Admission ждёт свежий provider snapshot (максимум 300 секунд) ([quota_gate.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/quota_gate.py:1182)); источник snapshot сейчас нормализует только Anthropic/Codex/Grok и не имеет Antigravity cache/refresh ([routes/system.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/routes/system.py:1490)). Нужно представить каждую реальную quota group самостоятельным provider bucket с observation timestamp, utilization и reset time; Gemini и third-party models нельзя смешивать, если поставщик отдаёт отдельные pools. Неизвестность оставлять unknown, не превращать в 0% или ложный остаток.
3. **Turn usage.** Из CLI `result.usage` можно положить известные input/output/cache/reasoning counters в `TurnUsage`; контекст помечать unknown, пока не доказана семантика. `turn_usage` хранит runtime/model, usage и nullable `cost_usd` плюс `cost_unaccounted` ([schema.sql](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/schema.sql:544)); обычный terminal-event writer уже поддерживает unknown cost ([session_turns.py](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-gemini-worker/app/session_turns.py:315)). Provider quota samples нужно также подключить к отображению/истории, иначе dashboard не покажет третий pool.
4. **MCP и workspace/sandbox.** #249 на 1.1.12 подтвердил именно вызов, а не discovery, stdio MCP; профиль должен передавать Orchestra MCP-серверы в CLI и проверять фактически запущенный список. Нужны отдельный HOME для runtime state/conversations и `--add-dir <worktree>`: разные cwd сами по себе направляли tools в общий scratch. Это предотвращает коллизии, но не является adversarial security boundary: при общем Unix user и shell tools один worker потенциально читает sibling HOME/credential. Сильная sandbox-защита через этот флаг не доказана. Операторская readiness должна проверять credentials, region/model и quota до публикации нового worker; наличие каталога или token-файла entitlement не подтверждает.

Это средний/существенный runtime-порт, не только регистрация одной модели: backend + auth/readiness + route/catalogue + quota-cache/API + учёт/представление + тесты event lifecycle, negative admission, HOME/worktree, MCP и credential loss. Код не менялся; оценку в человеко-днях не делаю без прототипа и contract tests.

### Ёмкость и решение

На eligible **чужом корпоративном control account** #249 зафиксировал 13 коротких Gemini Flash-low результатов: 276,577 input, 3,445 output, 1,546 thinking, 256,572 cache-read, 280,022 total tokens; Gemini weekly `remaining_fraction` упал с 1.0 до 0.83995521068573 — расход **16.0045 п.п.** При грубой линейной нормализации это около **81 результатов того же смешанного размера на weekly pool**. Это не универсальный request cap: пробы различались по инструментам/контексту, а остановку по 5 п.п. тогда обнаружили с опозданием. Измерение было на 1.1.12 и не на Jio-account.

В том отчёте `/quota` показывал две недельные группы (Gemini и Claude/GPT) с `remaining_fraction` и reset timestamp; **5-часового окна в Antigravity snapshot не было**. Значит 81/week — только прежняя грубая оценка Gemini weekly pool на стороннем eligible account; для Jio текущая подтверждённая weekly capacity — **0 successful tasks measured**, а фактический доступ — неподтверждён/ранее отказал по location. Для решения о third pool это сейчас **не стоит интегрировать ради Jio Pro**: реальная ёмкость Jio не установлена и существующее evidence отрицательное. Техническая пригодность CLI на 1.1.12 подтверждена прежним trial (stream/tools/MCP/resume/isolation), но она не конвертируется в доступ Jio. Новый VPS runtime потребует отдельной успешной owner-account проверки после interactive OAuth; никаких платных API-вызовов не требуется и не проводилось.
