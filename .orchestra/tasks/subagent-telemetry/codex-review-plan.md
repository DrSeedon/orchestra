- при кастомных профилях SDK-функции читают `CLAUDE_CONFIG_DIR` из process env, а не из параметра. Значит endpoint должен учитывать `session.profile/config_dir`, иначе будет пусто вне `personal`;
- если `task_id != agent_id`, нужен fallback через `list_subagents(sdk_session_id, cwd)` и сохранённый mapping. `tool_use_id` тут не мусор, это мост к live `parent_tool_use_id`.

4. **Что собирать из “лишнего”**  
- `tool_use_id` — собирать обязательно.
- `session_id` SDK — собирать обязательно как `sdk_session_id`.
- `uuid` — дешево и полезно для дедупа/debug; хранить хотя бы `start_uuid/end_uuid/last_uuid`.
- `data: dict` — не колонками. Если требование “ничего не терять” буквально, положить raw JSON в `raw_data_json`/`raw_event_json`. Для аналитики почти наверняка мусор, но без probe выкидывать рано.

Главный blocking не cost, а путаница `sessions.id` vs SDK `session_id` и `task_id` vs `agent_id`. Без этого endpoint транскрипта легко будет возвращать пусто при живых данных.
tokens used
147,199
Вердикт: план правильный по направлению, но перед реализацией надо поправить несколько реальных мест.

1. **Cost**  
Понимание верное: `ResultMessage.total_cost_usd` уже является total по SDK-сессии, субагенты туда входят. `TaskUsage` хранить только как атрибуцию субагента, не прибавлять к `session.cost_usd`.  
Дополнить: `TaskProgress.usage` не суммировать по progress-событиям, брать latest/final. Если `TaskNotification.usage is None`, оставить последние progress-значения.

2. **Таблица оправдана, но схема не хватает**  
Для отдельного чата + токенов таблица `subagents` не оверинжиниринг даже для 1 dev. Это одна маленькая таблица-индекс к SDK JSONL.

Но:
- `task_id TEXT PRIMARY KEY` рискованно. Лучше `UNIQUE(orchestra_session_id, task_id)` или отдельный `id`, потому что уникальность `task_id` глобально не гарантирована.
- Нужен отдельный `sdk_session_id` из Task*-message. Сейчас `session_id` в таблице ссылается на `sessions(id)`, а `get_subagent_messages()` требует Claude SDK session id. После compact/current-session смены без `sdk_session_id` старые транскрипты можно потерять.
- `COALESCE` с пустыми строками не спасает: `''` не `NULL`. Надо либо не передавать пустые поля, либо `COALESCE(NULLIF(excluded.summary,''), summary)`.

3. **Endpoint: runtime-probe нужен, но недостаточен**  
Плану надо явно зафиксировать:
- route `{session_id}` должен быть Orchestra DB session id, а в SDK передавать `subagents.sdk_session_id`;
- `directory` для SDK это `cwd` проекта, не `config_dir`;
- при кастомных профилях SDK-функции читают `CLAUDE_CONFIG_DIR` из process env, а не из параметра. Значит endpoint должен учитывать `session.profile/config_dir`, иначе будет пусто вне `personal`;
- если `task_id != agent_id`, нужен fallback через `list_subagents(sdk_session_id, cwd)` и сохранённый mapping. `tool_use_id` тут не мусор, это мост к live `parent_tool_use_id`.

4. **Что собирать из “лишнего”**  
- `tool_use_id` — собирать обязательно.
- `session_id` SDK — собирать обязательно как `sdk_session_id`.
- `uuid` — дешево и полезно для дедупа/debug; хранить хотя бы `start_uuid/end_uuid/last_uuid`.
- `data: dict` — не колонками. Если требование “ничего не терять” буквально, положить raw JSON в `raw_data_json`/`raw_event_json`. Для аналитики почти наверняка мусор, но без probe выкидывать рано.

Главный blocking не cost, а путаница `sessions.id` vs SDK `session_id` и `task_id` vs `agent_id`. Без этого endpoint транскрипта легко будет возвращать пусто при живых данных.
