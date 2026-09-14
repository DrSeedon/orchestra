---
name: agent-teams
description: Как запускать ИИ-агентов для параллельной работы в Claude Code — Agent Teams (команда из Opus-architect + Sonnet teammates, shared task list, peer-to-peer SendMessage, worktree-изоляция) или одиночные встроенные Agent. Триггеры — "запусти агентов", "запусти команду", "agent team", "параллельно сделай", "командой агентов", "можно это через агентов", "ебашь с агентами", спавн teammates/teammate, TeamCreate, isolation worktree, shared task list. НЕ использовать для одиночных мелких правок (правлю сам). ОБЯЗАТЕЛЬНО читать перед любой работой с агентами — чтобы не повторять race condition без worktree.
---

# Agent Teams — универсальная инструкция

> **⚠️ ПЕРВОЕ что смотреть при запуске:** `isolation: "worktree"` в каждом `Agent()` вызове. Без этого **все teammates делят одну рабочую копию** → `git checkout` одного перетирает WIP других → bardak.

## Три инструмента по убыванию мощи

| Инструмент | Когда | Оверхед старта |
|---|---|---|
| 🟢 **Agent Teams** — 2-5 teammates со shared task list и peer-to-peer SendMessage | Фича в 3+ зонах, ресёрч с разных углов, gap analysis | 1-2 мин на спавн команды |
| 🟡 **Одиночный Agent tool** (`subagent_type: general-purpose/Explore/Plan`) | Узкая задача в одной зоне, багфикс, единичный ресёрч | 3-5 сек |
| ⚪ **Сам, без агентов** | Мелкая правка 1-2 строки, 5-минутная задача | 0 |

**Проверенный результат Agent Teams:** команда 5 teammates (Opus-architect + 4 Sonnet) реального мобильного приложения — 2400 LOC кода + 573 LOC E2E + 1509 LOC ТЗ за **90 минут**. 242 pytest passed, 12 атомарных коммитов, 1 баг пойман QA-teammate. Эквивалент 1.5-2 дней соло-работы.

## Требования окружения

```json
// ~/.claude/settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Plus Claude Code **2.1.32+** (проверить `claude --version`).

## 🚨 КРИТИЧНО: isolation: "worktree"

**Это правило номер один.** Без него — guaranteed race condition.

Правильно:
```
Agent({
  team_name: "feature-name",
  name: "backend",
  subagent_type: "general-purpose",
  model: "sonnet",
  isolation: "worktree",     // ← ОБЯЗАТЕЛЬНО
  run_in_background: true,
  prompt: "..."
})
```

Что даёт `isolation: "worktree"`:
- Каждый teammate получает свой `repo/.auto-claude/worktrees/{random-name}/`
- `git checkout` одного агента не затрагивает других
- Cleanup автоматический — если агент ничего не изменил, worktree+ветка удаляются
- Осиротевшие worktree (после краша) чистятся при старте новой сессии если старше `cleanupPeriodDays`

### Проверка что worktree настроен
```bash
git worktree list                  # сколько активных, где
git worktree remove path/to/wt     # снести руками
git worktree prune                 # почистить orphaned
```

### Передача gitignored файлов (.env)

Worktree — чистый checkout, untracked не копируются. Создать `.worktreeinclude` в корне репо:
```
.env
.env.local
config/secrets.json
```
Копируются только gitignored (tracked не дублируются). Работает и для subagent worktrees.

## Команда из 5-6 teammates — универсальный шаблон

```
architect (Opus)    — пишет ТЗ, challenge-режим, ревью
backend (Sonnet)    — бэк-API, ORM, миграции, тесты
frontend (Sonnet)   — UI, SPA, компоненты, стили в коде
design (Sonnet)     — CSS-токены, шрифты, иконки, копирайтинг
qa (Sonnet)         — E2E-тесты, Playwright, unit-тесты в ветке
verifier (Sonnet)   — post-deploy smoke на проде после merge (ОПЦИОНАЛЬНО)
```

Для разных стеков роли переименуются, суть та же: **N зон = N teammates**, дальше сами работают параллельно.

### Verifier (6-й teammate) — когда добавлять

**Урок 23.04.2026:** qa-teammate писал E2E для _новой_ фичи в ветке, но **не проверял что существующие endpoints работают после merge**. Результат — breaking change в deps (Starlette 1.0 `TemplateResponse` API) прошёл через pytest и задеплоился → 5 дней 500 у юзера.

Решение — 6-й teammate **verifier** с ролью:
1. Ждёт CI deploy (polling `systemctl is-active` / health-endpoint)
2. Прогоняет `scripts/post_deploy_smoke.sh` на проде (должен существовать в проекте!)
3. Если smoke упал — SendMessage team-lead: «regression на URL X, ожидали 200, получили Y, traceback: ...»
4. Team-lead решает: откат merge (`git revert`) или пинг виновника (backend/frontend) на hotfix

**Когда нужен verifier:**
- Рефакторинг большого объёма (много файлов / много endpoint'ов затронуто)
- Обновление мажорной версии зависимости (Starlette/FastAPI/SQLA/Django)
- Прод уже живой с юзерами (регрессия = downtime у клиента)

**Когда не нужен:**
- Новый проект без юзеров
- Фича в изолированном модуле без взаимодействия с остальным
- Маленький патч в один файл

## Модели — как распределять

| Роль | Модель | Почему |
|---|---|---|
| architect | **Opus** | Спеки, challenge, ревью — здесь размышление даёт прирост |
| все остальные (backend/frontend/design/qa) | **Sonnet** | Имплементация — Opus не даёт прироста над Sonnet, сжигает tokens |
| explorer-задачи (grep, `ls`, списки файлов) | **Haiku** | Дешёвая пехота |

## 🔬 Ресёрч командой — недооценённый юзкейс

Agent Teams — не только для кода. Команда ресёрчеров разбирает тему с разных углов *параллельно*:

- **Архитектор** — смотрит на код, структуру, паттерны, точки расширения
- **Бизнес-аналитик** — gap analysis, требования, приоритеты, MoSCoW
- **Ресёрчер** — гуглит best practices, доки, сравнивает подходы
- **Data-инженер** — смотрит на данные, БД, flow, масштабирование

Каждый тратит *весь свой контекст* на свою узкую область. Результат — 3-4 глубоких отчёта за 10-15 минут вместо 1 поверхностного. Для ресёрча worktree опционален (если не меняют код).

Примеры промптов для ресёрч-команды — в [references/examples.md](references/examples.md).

## 📐 Фаза 0: Планирование (СТОП — жди ОК от юзера!)

Прежде чем собирать команду — предложи план юзеру и *дождись утверждения*:

1. **Разберись в задаче** — прочитай CLAUDE.md, контекст, код
2. **Определи состав** — 2-5 тиммейтов, роли под конкретную ситуацию
3. **Опиши план** — фазы, зависимости, ожидаемый результат
4. **Задай 2-4 уточняющих вопроса** — приоритеты, scope, ограничения
5. **СТОП. Жди "ОК".** Не создавай команду, не пиши промпты пока юзер не утвердит

Юзер может: изменить состав, приоритеты, scope, попросить подготовительную работу.

Шаблон промпта для тиммейтов — в [references/template.md](references/template.md).

## 📐 Правильный flow запуска команды

**Строгая последовательность**, не смешивать:

1. **Подготовка workspace**
   - `git worktree list` — убедиться что в текущем репо изоляция будет работать
   - `.worktreeinclude` создан (если есть кред-файлы)

2. **TeamCreate**
   ```
   TeamCreate({team_name: "feature-name", agent_type: "team-lead"})
   ```

3. **TaskCreate первой задачи** — «написать N ТЗ в docs/tasks/»

4. **Спавн architect (только!)**
   ```
   Agent({
     model: "opus",
     name: "architect",
     team_name: "feature-name",
     isolation: "worktree",
     run_in_background: true,
     prompt: "...читай такие-то источники, пиши ТЗ в формате Y..."
   })
   ```

5. **Architect пишет ТЗ** (~25 минут на средний скоуп), уходит в idle.

6. **Я ревьюю ТЗ сам** (5-10 минут) — читаю, критикую, кидаю правки architect'у через SendMessage если надо.

7. **Коммичу ТЗ в main** — чтобы teammates читали его как стабильный источник.

8. **Только после** спавню оставшихся teammates **параллельно**:
   ```
   [4x Agent spawns с isolation: "worktree", run_in_background: true]
   ```

9. **Создаю остальные задачи в shared task list** с `TaskUpdate(addBlockedBy: ["1"])` — автозависимости.

10. **Teammates сами claim'ят** задачи, читают ТЗ из main, работают в своих worktree, коммитят в свои ветки.

11. **Я слежу**: `TaskList` + teammate-messages в inbox + Pyright-диагностика в моём чате (видно какие файлы правятся).

12. При teammate-сообщениях — **ревью `git log` + `git diff` agent-ветки**, НЕ верю отчётам слепо.

13. Все готовы → `merge` веток в main **последовательно** (разрешая возможные конфликты), push, CI деплой, smoke.

14. `SendMessage` с shutdown_request каждому teammate → `TeamDelete`.

## 📋 После отчёта работника (ОБЯЗАТЕЛЬНО)

Когда работник присылает "готово, читай REPORT.md":

1. **Read REPORT.md целиком** — не скиммить. Ревью `git diff` ветки — не верить отчёту слепо.
2. **Findings/concerns** — каждый найденный баг/проблему вне scope → оценить критичность → `TaskCreate` или записать в TODO.md. Не терять.
3. **Фидбек на процесс** — проблемы и предложения работника → решить: менять worker.md / CLAUDE.md / скиллы или нет. Работник даёт данные, CTO принимает решения.
4. **Post-deploy действия** — если работник указал "после деплоя запустить X" → записать и сделать сразу после push.
5. **Score** — если <10/12, разобраться почему. Диагностика: плохой промпт → правка worker.md, непонятная задача → правка формулировок, баг в коде → TODO.

**Антипаттерн:** прочитал summary в SendMessage, сказал "каеф", замержил, не открыл REPORT.md. Работник потратил контекст на анализ — если не читать, данные теряются.

**ЗАПИСЫВАЙ ВСЁ СРАЗУ.** Ты CTO в Claude Code — через секунду забудешь. Фидбек работника, найденные баги, предложения по workflow, post-deploy действия — **сразу** в файл (TODO.md, TaskCreate, или docs/). Не "запомню и сделаю потом". Оперативные штуки не держать в голове — записать и вернуться. Контекст может сжаться, сессия может упасть — файл останется.

**IDLE ≠ ЗАКОНЧИЛ.** Idle notification = "turn закончился", НЕ "работник всё сделал и ждёт". Работник может быть в середине задачи — просто его turn кончился и он продолжит. Не считай idle за сигнал "свободен" — жди явного сообщения "готово" или спрашивай через SendMessage "статус?". Не назначай новые задачи idle-работнику пока не подтвердил что текущая закрыта.

**WORKER AGENT ОБЯЗАТЕЛЕН.** При спавне работника:
1. `subagent_type: "worker"` — подтягивает `~/.claude/agents/worker.md` (глобальный, для всех проектов). Содержит: scorecard 15/15, Pit of Success (10 принципов), Codex workflow, фидбек на процесс, MCP tools, stuck detection, disk state
2. Промпт — ТОЛЬКО контекст конкретной задачи: что сделать, какие файлы, тесты, координация. Worker.md сам содержит весь workflow (план → Codex → код → Codex → коммит → отчёт)
3. НИКОГДА не писать workflow заново в промпте — он уже в worker.md. Дублирование = путаница
4. Путь: `~/.claude/agents/worker.md` (глобальный) или `.claude/agents/worker.md` (проектный override)

**НЕ ОСТАНАВЛИВАЙСЯ.** Пока в task list есть pending/in_progress задачи — CTO работает: мержит, ревьюит, создаёт новые задачи, назначает работникам, читает репорты. Не жди что юзер скажет "давай дальше". Юзер = CEO, он ставит приоритеты. CTO сам двигает работу вперёд пока есть backlog.

## 🤖 Управление командой в процессе

### Shared Task List
- `TaskCreate({subject, description})` — создать задачу
- `TaskUpdate({taskId, owner, status, addBlockedBy})` — назначить, обновить, зависимости
- `TaskList()` — текущий список с зависимостями
- Teammates сами claim'ят через `TaskUpdate(owner="my-name", status="in_progress")`

### Peer-to-peer SendMessage
- Между teammates напрямую, **не через меня**
- Пример: frontend пингует backend «схема endpoint'а X?» → backend отвечает → frontend применяет
- Реально работает в боевых условиях, сэкономило merge conflict

### Broadcast `*` — дорого
- `SendMessage({to: "*"})` шлёт всем teammates
- Каждый = отдельный LLM-инстанс, стоит линейно
- Использовать только для финального summary / shutdown_request

## ❌ Что НЕ делать

- Spawn без `isolation: "worktree"` — race condition **гарантирован**
- Ожидать что teammate сам создаст `git checkout -b` — может забыть, указать в промпте явно
- Разрешать teammate коммитить напрямую в main — путь только через feature branch + мой merge
- Спавнить 5 teammates когда работы на 5-10 минут — оверхед > выигрыша
- Спавнить параллельно **без готового ТЗ** — agents без спеки = bardak, сначала Opus-architect
- Спавнить несколько teammates в одну зону файлов — merge-конфликт гарантирован
- Делать `shutdown_request` самому себе или teammate'у без `SendMessage` — надо через message type
- `TeamDelete` когда teammates ещё active — провалится. Сначала shutdown всех, потом delete

## ✅ Что делать обязательно

- **Честность в промпте**: «если застрял — напиши `status: blocked`, не выдумывай что сделал». Sonnet слушается.
- **JSON-отчёт в конце** промпта teammate'а: `{branch, commits, tests, note}` — парсить легко, видно halfdone.
- **Ключи и креды искать самому** перед спавном. Положить в промпт: "ключ в X, НЕ проси у юзера".
- **Смоук-тест на проде руками** после мержа — агенты хорошо пишут код, но `curl | grep ожидаемое` — всегда я.
- **Конфликт Alembic миграций**: несколько агентов создали migration revision → `Multiple head revisions`. Лечение: `alembic merge -m "..." head1 head2 head3` после всех мержей.
- **`git worktree prune` после команды** — чистит orphaned-worktree на всякий случай.

## 🎯 Лайфхак «Opus architect → Sonnet orchestra»

Opus 4.7 architect за 25 минут выдаёт **в 3-5 раз более качественное ТЗ** чем ты успеешь накидать вручную за то же время. Spec-формат senior инженера: файлы с line numbers, invariants (IV), principles (PC), assumptions (AS), unknowns (UK), phases с acceptance.

Sonnet'ы по такому ТЗ работают **как по инструкции** — не гадают, не спорят, не переделывают. Результат предсказуемый.

**Если время позволяет — всегда architect-first**, даже если кажется «я и сам могу написать спеку за 5 минут». Качество спеки = качество результата × N-teammates.

## 🔁 Когда НЕ нужны Agent Teams

- **Последовательная задача** (task B зависит от task A, нельзя параллелить) — один агент с линейным workflow проще
- **Правки в одном файле** — teammates конфликтуют при merge независимо от worktree
- **Мелкие багфиксы на 5-10 минут** — оверхед на планирование выше выигрыша
- **Нет готового ТЗ** и нет времени на architect-phase — одиночный Opus решит быстрее чем команда без спеки
- **Непонятная задача** — сначала сам разобраться (plan mode), потом решать нужна ли команда

## 🧰 Troubleshooting

### «Team already exists»
Если `TeamCreate` падает — значит старая команда висит. `TeamDelete` (может потребовать shutdown_request'ы всем teammates сначала).

### Teammate не отвечает
- Проверь `TaskList` — может он в pending-задаче, ждёт dependency
- `SendMessage` — вопрос «жив?» — если idle, он ответит автоматом
- В крайнем случае — `shutdown_request`, спавни нового

### Race condition все равно
- Забыл `isolation: "worktree"` — `git worktree list` покажет сколько worktree, если 1 (один main) — проблема
- Остановить всех через shutdown_request, `TeamDelete`, разобраться с текущими ветками руками, перезапустить с isolation

### Orphan worktrees после краша
```bash
git worktree prune  # git сам убирает записи
rm -rf .auto-claude/worktrees/{orphan-name}  # если осталась сама папка
```

### «Cannot cleanup team with N active members»
`TeamDelete` требует сначала shutdown всех teammates. Пробежаться `SendMessage` каждому с `{type: "shutdown_request"}`, дождаться подтверждения, потом `TeamDelete`.

## 🪜 Старый механизм: одиночный встроенный Agent

До Agent Teams (или когда команда не нужна) используется обычный `Agent` tool. Те же правила:
- Отдельная git-ветка `fix/XXX-YYYY-MM-DD` или `feat/...`
- Промпт-контракт (honest reporting, JSON-отчёт)
- После мержа — smoke руками, не верить отчётам
- `git diff --name-only` + `git status` проверять всегда

Разница с Teams: нет peer-to-peer, нет shared task list, нет автоматических worktree (нужно руками или через `up:git-worktrees` skill если такой есть в проекте).

## 📚 Референсы

- Официальная дока: https://code.claude.com/docs/en/agent-teams
- Common workflows: https://code.claude.com/docs/en/common-workflows#run-parallel-claude-code-sessions-with-git-worktrees
- Subagents: https://code.claude.com/docs/en/sub-agents (для нестандартных ролей с кастомным toolset)
