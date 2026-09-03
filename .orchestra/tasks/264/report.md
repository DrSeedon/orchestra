# #264 — Grok не поднимался как рантайм воркера: два дефекта подряд

Симптом (репро оркестратора, 13.08 16:47):

```
Grok MCP conformance failed: missing required servers ['orchestra'];
required servers not ready ['orchestra']; required MCP launch reported no tools.
```

Итог: **оба дефекта найдены и починены, Grok-агент живьём вызвал Orchestra-тул и ответил.**
`grok mcp list` («No MCP servers configured») — ложный след: Orchestra отдаёт сервер через
ACP `session/new`, а не через конфиг Grok, поэтому в `grok mcp list` его никогда и не было.

## Дефект 1 (несущий) — репозиторный `.mcp.json` съедал сервер по имени

В репозитории лежал **трекнутый** `.mcp.json`, объявляющий сервер с тем же именем
`orchestra` (коммит `085c4632` «add .mcp.json for local Claude Code testing», пути ноутбука
`/mnt/data/Projects/Python/orchestra`, которых на VPS не существует).

Механизм — дословно из отладочного лога самого Grok (`/tmp/grok-debug-264.log`):

```
INFO  managed_mcp: MCP server loaded from source server="orchestra" source=ConfigToml {...}
INFO  config::mcp: loaded MCP servers source=".../fix-grok-mcp/.mcp.json" count=1
WARN  folder_trust: folder untrusted: skipping repo-local (project-scoped) MCP server server=orchestra
INFO  acp_session::spawn: Session '...' created with 0 MCP servers
```

Grok сливает project-scope **поверх всех остальных источников ПО ИМЕНИ** (README, строка
2000: «the project version **replaces** it entirely»), и только ПОТОМ выбрасывает
project-запись из-за недоверенной папки. Наш сервер аннигилируется вместе с ней.

Проверено, что проигрывают **все** способы доставки, а не только наш (одинаковый cwd с
коллизией, `docs/tasks/264/probe_collision.py`):

| маршрут | `created with N MCP servers` |
|---|---|
| ACP `session/new` (как в проде) | 0 |
| `config.toml` в GROK_HOME | 0 |
| `--plugin-dir` (документирован как «always trusted», плагин **обнаружен**: `loaded MCP servers source="plugin:orchestra" count=1`) | 0 |
| `--plugin-dir` + ACP-план | 0 |

Контроль: тот же ACP-план в cwd **без** `.mcp.json` → `created with 1 MCP servers`,
`config_names=["orchestra"]`. То есть маршрут исправен, ломала именно коллизия имени.

Запись мертва для всех наших потребителей: `app/runtime_registry.py:126,135` явно
пропускают ключ `orchestra` из `.mcp.json`/`settings.json`, а `_make_mcp_config` его
игнорирует с предупреждением. Единственный, кто её читал, — Grok, и читал разрушительно.

**Правка:** `.mcp.json` удалён (в нём была ровно одна эта запись).

## Дефект 2 — Grok 1.0.3 перестал заполнять `servers_updated`, проверка личности падала всегда

После снятия коллизии сервер стартовал, но connect падал уже иначе:
`servers with unexpected identity ['orchestra']`. Сырой поток уведомлений при живом
connect:

```
_x.ai/mcp/servers_updated  {"mcpServers": []}          <- пусто
_x.ai/mcp/init_progress    {"total": 1, "connected": 1}
_x.ai/mcp_initialized      {"mcpToolCount": 37}
_x.ai/mcp/server_status    {"name": "orchestra", "status": "ready"}
итог: started=['orchestra'] ready=['orchestra'] identities={} tools=37
```

`_started_server_identities` наполняется ТОЛЬКО из `servers_updated`, а `_started_servers` —
ещё и из `server_status`. В 1.0.3 роспись роли пуста, поэтому «личность не сообщили»
читалось как «личность неверная» — при полностью корректном роспуске из 37 тулов.

**Правка** (`app/backend_grok.py`): личность сверяется только там, где рантайм её реально
прислал; вместо потерянного признака добавлен счётный инвариант из `init_progress.total` —
`overloaded`: число загруженных сессией серверов обязано совпадать с планом запуска.

### Остаточная дыра, названная честно

`servers_updated` был каналом, по которому #98 ловил подмену сервера с тем же именем (и
через который когда-то утёк чужой `OPENROUTER_API_KEY`). Пустой — он этот контроль больше
не даёт. Что осталось: точное совпадение множества имён, `total` из `init_progress` (лишний
сервер поднимает счётчик), ненулевой `mcpToolCount`, плюс GROK_HOME, которым владеет
Orchestra и который не помечает папки доверенными — а недоверенная папка, как измерено
выше, вообще не даёт project-scope загрузиться. Не покрыт случай «папка стала доверенной И
кто-то объявил сервер с именем `orchestra`»: подмену через ACP теперь не увидеть.
Настоящее лечение — канареечный хендшейк от нашего же `mcp_stdio.py` (кандидат из
`docs/tasks/98-grok-runtime-audit/research.md`), это отдельная задача.
Тесты личности из #98 (`tests/test_backend_grok.py`, 82 passed) остались зелёными: где
рантайм личность присылает, подмена по-прежнему ловится.

## Диагностика на будущее

Сообщение об отказе теперь само называет причину (`_shadowing_hint`): если недостающий
сервер объявлен в `.mcp.json` или `.grok/config.toml` рядом с cwd, отказ печатает файл и
средство. Иначе следующий такой случай — снова часы поиска, потому что наблюдаемый роспись
пуста в обоих случаях.

## Доказательства

**Живой прогон** через настоящий `GrokBackend` (`docs/tasks/264/live_grok_worker.py`,
собран как `_grok_factory`, поэтому `_verify_mcp_isolation` отрабатывает по-настоящему):

```
CONNECTED tools=37, started=['orchestra'], ready=['orchestra']
EV tool_use    search_tool: {"query": "list_agents orchestra"}
EV tool_result ... "tool_name": "orchestra__list_agents" ...
EV tool_use    use_tool: {"tool_name": "orchestra__list_agents", "tool_input": {}}
EV tool_result {"status": "completed"}
EV stream      COUNT=30
EV turn_end    stop_reason=end_turn
```

Агент получил задание, вызвал тул Orchestra и ответил числом из живых данных.

**Мутация** (`docs/tasks/264/mutation_check.py`, маркер печатается перед каждой фазой):

| фаза | `.mcp.json` | результат |
|---|---|---|
| baseline | нет | CONNECTED tools=37 |
| mutant-shadow | есть | REFUSED + подсказка называет файл |
| reverted | нет | CONNECTED tools=37 |
| mutant-cmd (битый путь к бинарю) | нет | REFUSED |
| reverted-cmd | нет | CONNECTED tools=37 |

Мутант воспроизводит **дословно** прод-ошибку оркестратора — то есть чинили именно тот
дефект, о котором был тикет. Зелёный повтор после отката отличает «мутация откачена» от
«мутант продолжает исполняться». Мутации — данные (JSON-файл, план в памяти), не `.py`,
поэтому `__pycache__` тут не при чём и `touch` не требуется.

## Версия про побочный ущерб от #251 — ОТВЕРГНУТА

Правка `~/.grok/config.toml` ради телеметрии к делу не относится: managed GROK_HOME
(`data/grok-home`) уводит Grok от пользовательского конфига, и **все** пробы выше
поднимались на свежезаписанном шаблоне `_GROK_SANDBOX_CONFIG` — и всё равно падали. То есть
дефект воспроизводится на заведомо чистом конфиге.

Побочная находка (не причина, но реальна): managed `data/grok-home/config.toml` **дрейфует**
— Grok переписывает его сам. На момент начала задачи он потерял блоки `[features]` и
`[telemetry]` и приобрёл `[cli]`/`[ui]`/`[marketplace]`. Orchestra самолечится: сравнение с
шаблоном в `_write_sandbox_config` восстановило их при первом же моём connect (сейчас на
диске шаблон + дописанный Grok'ом `[marketplace]`). Телеметрия при этом всё равно закрыта
переменными окружения в `_build_env`, так что ущерб ограничен окном между переписыванием и
следующим коннектом. Отдельного тикета просит, чинить в рамках #264 не стал.

## Что нужно знать перед мержем

- `.mcp.json` **трекнут в main и лежит в 28 существующих worktree**. Новые воркеры
  ответвляются от main и после мержа коллизии не увидят; воркеры на СТАРЫХ ветках будут
  ловить её, пока не подтянут main. Grok-воркера спавнить на ветке с этим удалением.
- `app/workspace.py:29` копирует `.mcp.json` в каждый новый worktree через `PROJECT_FILES`.
  После мержа копировать нечего. Но в ЛЮБОМ другом репозитории со своим `.mcp.json`,
  объявляющим `orchestra`, дефект повторится — теперь он хотя бы называет себя сам.
- Файл трекнутый и общий с контуром ноутбука: там пути `/mnt/data/Projects/Python/...` могли
  быть живыми. Удаление согласовать.
