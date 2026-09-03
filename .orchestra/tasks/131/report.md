# #131 — Отчёт об исполнении: рабочий контур Orchestra на VPS

Дата: 2026-08-03. Phase 3 (исполнение). Все 4 шага выполнены, откат не потребовался.

## Итог

`https://orchestra.seedon.ru` — рабочий контур с актуальным кодом и оркестратором,
который знает сегодняшний день. VPS подготовлен к нагрузке (swap + приоритеты памяти).
Локальный контур не затронут: 85 сессий на ноуте работают как работали.

## Что сделано, с фактическими проверками

### Шаг 1 — swap
| | BEFORE | AFTER |
|---|---|---|
| Swap | 0 | **4095 МБ** |
| swappiness | 60 | **10** |
| Диск свободно | 133G | 129G |

`swapon --show` → `/swapfile file 4G`, `/etc/fstab` прописан (переживёт ребут).

### Шаг 2 — приоритеты памяти (`/proc/<pid>/oom_score_adj`, не `systemctl show`)
| Юнит | BEFORE | AFTER | Статус |
|---|---|---|---|
| orchestra | 0 | **800** | применено (на рестарте шага 4) |
| tinyproxy | 0 | **-900** | применено сразу |
| kesha-bot-vps | 0 | 0 | дроп-ин ждёт рестарта (согласовано) |
| telegram-bot-api | 0 | 0 | дроп-ин ждёт рестарта (согласовано) |

Лимиты Orchestra: `memory.high=2147483648` (2G), `memory.max=3221225472` (3G) — были `max`.
**Наблюдение:** memory-лимиты применились БЕЗ рестарта, systemd меняет cgroup на лету;
`OOMScoreAdjust` — только на рестарте.

tinyproxy проверен работой, а не `is-active`: через него `github.com` → **HTTP 200 за 0.25s**,
`api.anthropic.com` → **405**. Порт 18080 (12343 — локальный конец ssh-туннеля на ноуте).

### Шаг 3 — код и БД
Код: `41c7dc4` → **`519843c`** (в два приёма: сначала вершина origin `5578f16`, затем
`519843c` после того, как оркестратор запушил main). `CLAUDE.md` = 32661 байт, `docs/tasks/131/`
и `docs/workers/migrate-vps.md` на месте.

БД — изменена **ровно одна строка**, `rowcount: model=1, session_id=1`:
```
ДО:     Orchestra-orchestrator  claude-opus-4-6[1m]  f163042a-...  idle
ПОСЛЕ:  Orchestra-orchestrator  claude-opus-5[1m]    ''            idle
        backend/frontend/back   claude-opus-4-8[1m]  <не тронуты>
```
Миграция схемы: `turn_usage`, `tool_errors`, `merge_operations`, `improvement_rules`,
`voice_costs` — **все 5 созданы**. Соответствует прогону на копии в Phase 1 (`rows lost: NONE`).

Модель после старта **не откатилась**: `claude-opus-5[1m]` с пином `[1m]` (проверена строка,
не alias), `session_id` остался пустым.

### Шаг 4 — оркестратор
`uv sync --extra rag` вернул RAG-пакеты. Проверено не отчётом `uv`, а фактом:
```
sqlite_vec import: OK, version 0.1.9
vec extension loaded: v0.1.9      ← vec_version() отвечает
fastembed import: OK
```

Сессия поднята (не создана заново): `session_id` сменился с июльского `f163042a` на новый
`5f2931e0`, контекст 5% — старт с чистого листа состоялся.

**Проверка знаниями, невозможными в июле** (ответ дословно):
> **(1)** Не `compact_worker`, а `UPDATE sessions SET session_id='' ` при **остановленном**
> сервисе. Причина: компакт просит саму сессию законспектировать себя — устаревшие убеждения
> переезжают в саммари, а исходник для перепроверки теряется. Сброс session_id заставляет
> агента перечитать факты с нуля. (Живой сервер перезаписывает поля сессии из памяти →
> правка только при стопнутом сервисе + перепроверка после рестарта.)
>
> **(2)** Swap 4.0 GiB (used 0), RAM 7.8 GiB. `OOMScoreAdjust` у orchestra = **800**,
> подтверждено ground truth: `/proc/281278/oom_score_adj` = 800 (не `systemctl show`,
> который печатает значение всегда).

Оба ответа опираются на правила, появившиеся сегодня, и на состояние VPS, созданное
шагами 1-2. Отдельно ценно, что он сам сверился через `/proc`, а не через `systemctl show`.

Дашборд: `https://orchestra.seedon.ru/` → **302**, `/api/agents` → **401** (авторизация цела).

## Незапланированное: блокер прав и как он снят

`git stash`/`fetch` упали под `kesha`:
`insufficient permission for adding an object to repository database .git/objects`.

Причина — каталог наполовину принадлежал root (**295** файлов в `.git`, **3021** в рабочем
дереве) при `User=kesha` в юните. Следы июльских операций от root. Работало ровно до первой
попытки записи в `.git`.

Снято `chown -R kesha:kesha` после согласования, со страховками:
- снимок владельцев ДО → `/home/kesha/backup-131-owners.txt` (3316 строк, откат пофайлово)
- режимы доступа (`%a`) до и после: `.env` 644, `data/orchestra.db` 644, `data/` 755,
  `.git` 755 — **не изменились**, chown тронул только владельца
- не-kesha файлов после: **0**

## Точка отката (актуальна)

```
/home/kesha/backup-131-orchestra.db      (1.3 МБ, до обновления)
/home/kesha/backup-131-orchestra.db-wal  (367 КБ)
/home/kesha/backup-131.env
/home/kesha/backup-131-commit.txt        → 41c7dc4b8aae5626bdc46d5e642ce247ae716c46
/home/kesha/backup-131-owners.txt        (3316 строк — владельцы до chown)
```
Откат: `systemctl stop orchestra` → `git checkout 41c7dc4` → вернуть БД и `.env` →
`systemctl start orchestra`. Приоритеты: `systemctl revert orchestra tinyproxy
kesha-bot-vps telegram-bot-api` + `daemon-reload`. Swap: `swapoff /swapfile`.

## Найденные дефекты (не чинил — вне скоупа)

1. **Bootstrap игнорирует `WORKSPACE_DIR`.** При старте:
   `Bootstrap: cannot create workspace /workspace/project ... exit status 1`.
   Юнит задаёт `WORKSPACE_DIR=/home/kesha/workspace/project`, а bootstrap лезет в дефолтный
   `/workspace/project`, которого нет. **Не наше и не сегодняшнее** — то же предупреждение
   есть в июльском журнале до обновления. На работу не влияет, сервис поднимается.
2. **`uv sync` без `--extra rag` тихо сносит RAG**, оставляя `RAG_ENABLED=true` в `.env`.
   Конфигурация начинает врать сама себе. Поймано и исправлено в шаге 4, но грабли общие:
   любой будущий деплой на VPS обязан использовать `uv sync --extra rag`.

## Что осталось незакрытым

- **`MemoryMax=3G` подобран от пика 158 МБ БЕЗ воркеров.** Это оценка, не измерение рабочей
  нагрузки. Реальную границу покажет
  `cat /sys/fs/cgroup/system.slice/orchestra.service/memory.events`: рост `oom_kill` →
  поднять до 4G; рост `high` — норма (троттлинг).
- **Проверка наследования `adj=800` живым воркером** (`claude`/MCP в cgroup Orchestra) не
  выполнена: воркеров на VPS не спавнили — по границе задачи их не переносим. Механизм
  подтверждён косвенно на дереве `kesha-bot-vps`, где дочерние `claude` и `workspace-mcp`
  несут `adj` юнита. Выполнить при первом реальном воркере на VPS.
- **`kesha-bot-vps` и `telegram-bot-api` получат свои `-500`/`-700` только после рестарта.**
  До тех пор защита держится на `800` у Orchestra — она уходит первой в любом случае.
