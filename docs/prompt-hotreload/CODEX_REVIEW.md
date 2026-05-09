## Tests

`pytest tests/test_session.py tests/test_manager.py -q` -> 19 errors на импорте: `ModuleNotFoundError: No module named 'claude_agent_sdk'`.

## Summary

Hot-reload частично чинит старые проблемы: больше нет тега `[SYSTEM UPDATE]`, хеш считается до замены `system_prompt`, а `_prompt_injected` защищает от повторного inject в каждом turn. Но реализация все еще не production-ready: worker prompt после рестарта собирается без форматирования и без custom-инструкций, а обновленный prompt не сохраняется в DB. Context window берется из последней iteration, но cache-метрики вычисляются и тут же теряются. Direct message inject имеет fallback в pending queue, но есть гонка, где injected message может обогнать стартовое сообщение текущего turn.

## Замечания

blocking: app/manager.py:207 — для worker `_current_prompt` ставится в сырой `WORKER_SYSTEM_PROMPT`, тогда как созданный worker получает форматированный prompt с `{worker_name}`, `{orchestrator_name}`, `{scope}`, `{branch}` и возможным custom `system_prompt` из `create_session`. После рестарта первый hot-reload inject отправит агенту незаполненные placeholders и потеряет custom-инструкции. Фикс: хранить custom-фрагмент/metadata отдельно и пересобирать текущий worker prompt с теми же параметрами, либо сравнивать/обновлять только platform-role часть без уничтожения per-agent prompt.

blocking: app/db.py:94 — `save_session()` на `ON CONFLICT` не обновляет `system_prompt`, поэтому `app/session.py:162` меняет prompt только в памяти. После следующего рестарта DB снова вернет старый prompt, и hot-reload снова injected тот же текст. Фикс: добавить `system_prompt=excluded.system_prompt` в UPSERT или хранить отдельный persisted `prompt_hash/prompt_version`.

blocking: app/session.py:160 — `_prompt_injected` и `system_prompt` обновляются до `connect/query/listen` success. Если `client.connect()` или `client.query()` упадет, refresh фактически не попал в Claude transcript, но следующий turn уже не повторит inject. Фикс: помечать refresh delivered только после успешного `client.query()` или после `ResultMessage`, а до этого держать pending prompt update.

blocking: app/session.py:167 — `_active_client` публикуется до `connect()` и до первичного `client.query(message)`. `send()` во время этого окна может вызвать `active_client.query()` сразу после connect и отправить injected message раньше исходного сообщения turn, включая prompt-prepend. Фикс: защищать connect/initial query/direct inject одним lifecycle lock или выставлять `_active_client` только после отправки initial query.

blocking: app/session.py:225 — `cache_hit/cache_read/cache_create` записываются в `_last_context`, но строка 230 полностью заменяет dict без этих ключей. API/UI не увидят cache tracking. Фикс: собрать один dict: `percentage`, `total_tokens`, `max_tokens`, `cache_hit`, `cache_read`, `cache_create`.

suggestion: app/session.py:220 — при пустом или отсутствующем `iterations` код fallback'ится на top-level `usage`. Если top-level содержит сумму нескольких API calls, это нарушает контракт "context window = последняя iteration". Фикс: считать context только из `iterations[-1]`; при пустом списке оставить предыдущее/zero значение и залогировать missing usage shape.

suggestion: app/manager.py:223 — после reload persisted context получает `max_tokens: 200000` независимо от модели, хотя runtime-расчет использует `CONTEXT_LIMITS`. Для `claude-opus-4-6[1m]` процент после рестарта будет завышен в 5 раз. Фикс: брать `CONTEXT_LIMITS.get(session.model, 200000)` при rehydrate.

suggestion: app/session.py:204 — `_did_report` становится `True` уже на `ToolUseBlock` `send_message`, до результата tool call. Если MCP send упал, auto-report будет подавлен, хотя report не доставлен. Фикс: помечать report только после успешного `ToolResultBlock` для соответствующего tool call или хотя бы не подавлять auto-report при error result.

suggestion: app/session.py:163 — полный role prompt уходит как user message. Это делает инструкции обычным transcript-контентом, который агент может процитировать, отправить другому агенту или засветить в dashboard/tool output. Фикс: считать prompts публичными и не класть туда секреты, либо вводить redacted hot-reload payload/версионированный non-secret diff.

nit: app/prompts/base.md:13 — prompt учит распознавать тег с `...`, а реальный sentinel в `app/session.py:163` имеет другой полный текст. Фикс: завести стабильный точный sentinel, например `[Orchestra platform note: role_instructions_refreshed]`, и использовать его одинаково в prompt и inject.

## Вердикт

No-go: hot-reload и cache tracking требуют фикса blocking issues перед merge.

## Round 2

### Tests

`pytest tests/test_session.py tests/test_manager.py -q` -> 19 errors на импорте: `ModuleNotFoundError: No module named 'claude_agent_sdk'`.

### Fixed / Still Broken

FIXED: app/session.py:230 — cache metrics больше не теряются: `percentage`, `total_tokens`, `max_tokens`, `cache_hit`, `cache_read`, `cache_create` теперь записываются одним `_last_context = {...}`.

FIXED: app/session.py:169 — прежняя race, где `_active_client` публиковался до `connect()` и initial `query()`, закрыта: `_active_client = client` теперь после `client.query(message)`.

FIXED: app/session.py:156 — прежний false positive с хешем и lifecycle `_prompt_injected` после failed `query()` исправлены: сравнение идет до изменения `system_prompt`, а `_prompt_injected=True` ставится после успешного `client.query(message)`.

FIXED: app/db.py:96 — `system_prompt=excluded.system_prompt` добавлен в UPSERT, поэтому обновленный prompt теперь может пережить restart.

FIXED: app/manager.py:223 — persisted context rehydrate теперь берет `max_tokens` из `CONTEXT_LIMITS`, а не всегда `200000`.

STILL BROKEN: app/manager.py:207 — worker placeholders теперь форматируются, но custom `system_prompt` все еще теряется. `create_session()` собирает `WORKER_SYSTEM_PROMPT + custom` на app/manager.py:106, а `_load_from_db()` строит `current_prompt` только из `WORKER_SYSTEM_PROMPT`; при первом reload worker с custom prompt получит false prompt update даже без изменения platform prompt, а затем `app/session.py:174` и `app/db.py:96` перезапишут DB без custom-инструкций. Фикс: хранить custom prompt отдельно или извлекать/сохранять custom tail при сборке `_current_prompt`; то же решение нужно для custom orchestrator prompts на app/manager.py:104.

### New Bugs

blocking: app/session.py:123 — после переноса `_active_client = client` за initial `query()`, сообщения, пришедшие во время `connect()` или initial `query()`, попадают в `_pending`, но debounce не армится из-за `status == RUNNING`. Если текущий turn упадет до `ResultMessage`, ветки exception на app/session.py:176 и app/session.py:181 ставят `IDLE`, но не запускают pending queue; сообщение застрянет до следующего user send. Фикс: после любого error/timeout при переходе в `IDLE` проверять `_pending` и вызывать `_arm_debounce()`.

suggestion: app/session.py:222 — старый edge case не закрыт: пустой/missing `iterations` все еще fallback'ится на top-level `usage`, что может снова считать сумму вместо последней API iteration. Фикс: если `iterations` пустой, не обновлять context или явно логировать unsupported usage shape.

suggestion: app/manager.py:225 — после restart cache metrics теряются, потому что DB хранит только `context_pct/context_tokens`, а rehydrate восстанавливает только `percentage/total_tokens/max_tokens`. Если cache tracking должен быть виден после reload, добавьте persisted `cache_hit/cache_read/cache_create` или явно обнуляйте их в `_last_context`.

### Verdict

No-go: один старый blocking по custom prompts все еще открыт, плюс новый blocking с застревающей `_pending` queue после failed turn.
