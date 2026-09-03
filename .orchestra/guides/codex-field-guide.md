# Codex для опытного пользователя Claude Code

> Практический курс миграции Claude Code → Codex CLI/IDE для текущей машины и Orchestra.
> Актуальность проверки: 2026-07-13. Локальный Codex: `0.144.1`, вход через ChatGPT.

## 0. Главное за две минуты

Codex — не «Claude Code с другой моделью». Базовый цикл похож, но границы системы
разложены иначе:

- инструкции проекта: `CLAUDE.md` → `AGENTS.md`;
- пользовательские настройки: `~/.claude/settings.json` → `~/.codex/config.toml`;
- headless-режим: `claude -p` → `codex exec`;
- продолжение: Claude resume/continue → `codex resume --last` или `codex exec resume`;
- разрешения: Claude permission modes/tool allowlists → отдельные sandbox, approval policy,
  permission profiles, exec rules и hooks;
- status line: в Claude обычно внешний скрипт, в Codex встроенный `/statusline`;
- саб-агенты: есть локально, видны через `/agent`, включены в актуальных версиях;
- расширение: skills + plugins + MCP + hooks, а не только MCP/commands;
- опасный режим: `--dangerously-skip-permissions` → `--yolo`, но использовать его
  постоянно не следует.

Для обычной работы:

```bash
cd /path/to/repo
codex
```

Внутри первым делом:

```text
/statusline
/permissions
/model
/reasoning
/init
```

## 1. Карта понятий Claude Code → Codex

| Claude Code | Codex | Что важно |
|---|---|---|
| `CLAUDE.md` | `AGENTS.md` | Не копировать слепо: удалить Claude-specific flags и хронику |
| `~/.claude/settings.json` | `~/.codex/config.toml` | TOML, конфиг слоистый: global → project → CLI overrides |
| `.claude/settings.local.json` | project `.codex/config.toml` | Project layer работает только для trusted repo |
| `claude` | `codex` | Интерактивный TUI |
| `claude -p` | `codex exec` | Скрипты, CI, Orchestra |
| `--output-format stream-json` | `codex exec --json` | JSONL-события, форматы различаются |
| `--continue`, `--resume` | `codex resume --last`, `codex resume ID` | Есть также `fork`, `archive`, `delete` |
| `/compact` | `/compact` | Название совпадает, реализация и summary отличаются |
| `/model` | `/model` | В Codex отдельно настраивается `/reasoning` |
| `/status` | `/status` | Codex показывает context и rate limits |
| внешний `statusLine` | `/statusline` | Встроенный picker: limits, tokens, git, model, context |
| `allowedTools`/`disallowedTools` | sandbox + rules + hooks | Прямого 1:1 нет |
| permission mode | sandbox + approval policy | Техническая граница отделена от решения «кто одобряет» |
| `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox`, `--yolo` | Полный доступ, без sandbox |
| `.claude/agents/*.md` | custom agents + subagents | В CLI потоки смотрятся через `/agent` |
| `.claude/skills/*/SKILL.md` | Codex skills | Концепция похожа; пути, discovery и trust надо проверить |
| Claude plugins | Codex plugins | Codex plugin может комплектовать skills, hooks, MCP и assets |
| MCP | MCP | `codex mcp add/list/get/remove/login/logout` |
| hooks | hooks | События похожи, но схемы входа/выхода не считать идентичными |
| worktrees вручную/через команды | app/CLI worktree workflows | Есть `/worktree` на поддерживаемых поверхностях |

## 2. Установка, вход и диагностика

На этой машине устанавливать заново не нужно. Проверки:

```bash
codex --version
codex login status
codex doctor --summary
codex mcp list
```

Обновление standalone-установки:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Интерактивный вход выполняется при первом `codex`; выбрать **Sign in with ChatGPT**.
API key и подписочная авторизация — разные режимы. Для Pro надо использовать вход ChatGPT,
если задача — расходовать подписочную квоту Codex.

## 3. Рабочий цикл в терминале

### Интерактивная задача

```bash
codex -C /path/to/repo
```

Полезный стартовый prompt:

```text
Сначала прочитай AGENTS.md и релевантные nested AGENTS.md. Изучи состояние git.
Сформулируй проверяемый план, затем реализуй задачу, прогони тесты и покажи итоговый diff.
Не изменяй несвязанные пользовательские изменения.
```

### Headless-задача

```bash
codex exec --sandbox workspace-write -C /path/to/repo \
  "Исправь баг, запусти релевантные тесты и дай краткий отчёт"
```

Для автоматического парсинга:

```bash
codex exec --json -C /path/to/repo "Проверь проект"
```

Типичные JSONL-события: `thread.started`, `item.started`, `item.completed`,
`turn.completed`. Не пытаться парсить stdout как текст при `--json`.

### Продолжение и развилка

```bash
codex resume --last
codex resume SESSION_ID
codex fork --last
codex exec resume --last "Продолжи и исправь оставшиеся тесты"
```

### Review

```text
/review
```

Или headless:

```bash
codex review --uncommitted
codex exec review --uncommitted
```

Конкретная просьба работает лучше общего «review everything»:

```text
Проверь diff как production regression review. Приоритет: data loss, auth bypass,
races, несовместимость схемы и отсутствие regression tests. Не пересказывай diff.
```

## 4. Slash-команды, которые надо выучить

| Команда | Назначение |
|---|---|
| `/status` | task/session ID, context, permissions, rate limits |
| `/statusline` | постоянный footer терминала |
| `/permissions` | текущий sandbox/permission profile |
| `/model` | модель |
| `/reasoning` | reasoning effort |
| `/plan` | режим планирования |
| `/init` | scaffold `AGENTS.md` |
| `/review` | code review |
| `/compact` | принудительное сжатие контекста |
| `/agent` | посмотреть/переключить subagent threads |
| `/mcp` | состояние MCP |
| `/hooks` | источники, trust и состояние hooks |
| `/fork` | развилка текущей задачи |
| `/side` | временная боковая беседа без остановки основной задачи |
| `/fast` | fast service tier, если доступен плану |

Набор зависит от версии и поверхности. Ввести `/` — это источник истины для
конкретной сессии.

## 5. Инструкции: как мигрировать CLAUDE.md

Codex ищет `AGENTS.md` по дереву проекта; более близкий nested-файл задаёт правила
для своего поддерева. Это удобно для monorepo.

Не переносить из старого `CLAUDE.md`:

- session diary и changelog;
- утверждения о давно завершённых задачах;
- Claude-specific tool names и flags;
- секреты, токены, пароли и приватные ключи;
- взаимоисключающие инструкции разных эпох.

Перенести:

- архитектуру и точки входа;
- команды setup/lint/test/build;
- code style и invariant'ы;
- правила git/worktree;
- обязательную верификацию;
- границы инфраструктуры и безопасные operational procedures.

Хороший запрос на миграцию:

```text
Прочитай CLAUDE.md. Создай компактный AGENTS.md только из актуальных durable rules.
Историю, TODO, session notes, секреты и Claude-specific синтаксис не переноси.
Все команды проверь по реальному репозиторию. Не выдумывай отсутствующие scripts.
```

### Жёсткий лимит 32 KiB — про него нужно знать на каждой машине

Codex грузит проектный документ до `project_doc_max_bytes` (по умолчанию **32 KiB**) и режет
**внутри файла, посреди фразы** — не «пропускает лишние файлы», а именно обрывает. Кириллица
в UTF-8 занимает 2 байта на символ, поэтому русский документ влезает вдвое хуже английского.

Замер Orchestra (2026-07-26): `CLAUDE.md` 61 643 байта → до Sol-воркеров доезжало ровно
32 768 (53%), обрыв на строке 375 из 707. Отваливалась самая свежая часть — заметки
приписываются снизу, а режется хвост.

Orchestra зеркалит `CLAUDE.md → AGENTS.md` в каждый worktree (`workspace.sync_agents_md`),
так что лимит бьёт по всем Codex-агентам всех проектов.

```toml
# ~/.codex/config.toml — до первой [секции], иначе ключ попадёт внутрь таблицы
project_doc_max_bytes = 98304
```

Файл лежит вне репозитория, поэтому **на новой машине и на VPS ключ надо выставить заново**.
Ключ — страховка, а не замена компактному документу: полный файл стоит примерно вдвое
больше токенов на старте каждой сессии (замер: 29 012 → 36 966 токенов холодного старта).

## 6. Саб-агенты: сходства и отличия

Актуальный Codex умеет локальные subagent workflows. Их следует применять для
независимых веток работы, а не для каждого мелкого шага.

Попросить явно:

```text
Параллельно делегируй независимые проверки: архитектура, тестовое покрытие и security.
Не давай двум агентам редактировать один файл. Собери вывод в один итог.
```

Что отличается от привычной модели Claude:

- Codex показывает локальные agent threads через `/agent`;
- custom agents могут иметь отдельные инструкции/модель/конфиг;
- делегирование может быть предписано `AGENTS.md` или skill;
- каждый саб-агент отдельно тратит токены и создаёт собственный контекст;
- основной агент получает summary, поэтому важные доказательства надо просить явно;
- parallelism хорош для чтения и независимых модулей, хуже для общего mutable state.

Правило расхода квоты: сначала один агент исследует задачу; subagents включаются, когда
есть минимум две реально независимые ветки, которые экономят wall-clock time.

## 7. Skills, plugins, MCP и hooks

### Skill

Повторяемый workflow с `SKILL.md`, references и scripts. Подходит для review process,
deploy playbook, миграций и генерации артефактов.

### Plugin

Устанавливаемый bundle. Может объединять skills, MCP, hooks, команды и assets.
Это более крупная единица, чем skill.

### MCP

Живые внешние инструменты и данные:

```bash
codex mcp list
codex mcp add NAME --url https://example.com/mcp
codex mcp get NAME --json
codex mcp remove NAME
```

На текущей машине уже зарегистрированы `orchestra`, `serena` и
`openaiDeveloperDocs`.

### Hooks

Детерминированные scripts на lifecycle events. Главный security-event —
`PreToolUse`; он может перехватывать `Bash`, `apply_patch` и MCP calls и возвращать
`permissionDecision: deny`.

Ограничение: hook — guardrail, не абсолютная security boundary. Эквивалентное действие
иногда достижимо другим tool path. Реальная защита строится слоями:

1. OS/container/VM boundary;
2. Codex permission profile;
3. network allowlist;
4. rules;
5. hooks;
6. git checkpoints/backups.

## 8. Permissions: правильная модель в голове

В Claude часто думают «разрешить tool или запретить tool». В Codex надо разделять:

- **sandbox/permission profile** — что технически достижимо;
- **approval policy** — что делать при попытке пересечь границу;
- **auto-review** — человек или отдельный reviewer проверяет escalation;
- **rules** — решения для command prefixes вне sandbox;
- **hooks** — собственная проверка tool input;
- **AGENTS.md** — поведенческая инструкция, но не защита.

### Режимы

```text
read-only          чтение, без редактирования
workspace-write    запись внутри workspace roots
danger-full-access без локальной sandbox-границы
```

```text
untrusted   спрашивать для неизвестных/опасных команд
on-request  агент запрашивает crossing boundary
never       никогда не спрашивать; запрещённое обычно просто не выполняется
```

`--yolo` одновременно убирает sandbox и approvals. Rules/hooks поверх него полезны,
но не превращают полный host access в надёжно безопасный режим.

## 9. Рекомендованный профиль «максимум возможностей, разумная безопасность»

Цель для этой машины:

- автономная запись во все проекты под `/mnt/data/Projects`;
- публичная сеть и localhost для package managers, API и Orchestra;
- глобальные Claude/Codex/infra docs доступны на чтение;
- `~/.ssh`, OAuth credentials и auth files не читаются автоматически;
- выход за границы рассматривает auto-review вместо постоянного вопроса пользователю;
- очевидно разрушительные команды режутся PreToolUse hook;
- **без** постоянного `--yolo`.

Концептуальный `~/.codex/config.toml`:

```toml
approval_policy = "on-request"
approvals_reviewer = "auto_review"
default_permissions = "max-safe"

[permissions.max-safe]
description = "All development projects, public network, protected credentials"
extends = ":workspace"

[permissions.max-safe.workspace_roots]
"/mnt/data/Projects" = true

[permissions.max-safe.filesystem]
":minimal" = "read"
"/home/maxim/.claude/CLAUDE.md" = "read"
"/home/maxim/.claude/docs" = "read"
"/home/maxim/.config/Cursor/User" = "read"
"/home/maxim/.ssh" = "deny"
"/home/maxim/.codex/auth.json" = "deny"
"/home/maxim/.claude/.credentials.json" = "deny"

[permissions.max-safe.filesystem.":workspace_roots"]
"." = "write"

[permissions.max-safe.network]
enabled = true
allow_upstream_proxy = true

[permissions.max-safe.network.domains]
"*" = "allow"
"localhost" = "allow"
"127.0.0.1" = "allow"
```

Permission profiles — beta. Они не смешиваются со старыми `sandbox_mode` и
`sandbox_workspace_write`; надо использовать один механизм.

### Почему не `approval_policy = "never"`

С `never` auto-review не запускается. `on-request + auto_review` позволяет routine
work идти автономно, а выход из sandbox рассматривает отдельный reviewer. Он специально
нацелен на exfiltration секретов, credential probing, persistent security weakening и
необратимо разрушительные действия.

### Что блокировать hook'ом

Минимальный разумный набор:

- `rm -rf` по `/`, `$HOME`, корню всех Projects;
- `mkfs`, `wipefs`, destructive `dd` по block device;
- `git reset --hard`, `git clean -fdx`;
- `git push --force`/`-f`;
- `curl|sh` и `wget|sh`;
- shutdown/reboot/poweroff;
- отправку `.env`, SSH keys, auth/credentials через curl/scp/nc.

Не надо блокировать весь `sudo`: внутри sandbox он всё равно потребует boundary crossing,
и auto-review сможет различить установку `bubblewrap` и удаление системных данных.

## 10. Rules против hooks

Rules-файл: `~/.codex/rules/default.rules`.

```python
prefix_rule(
    pattern = ["git", "reset", "--hard"],
    decision = "forbidden",
    justification = "Use a new branch or revert commit; preserve user changes.",
)

prefix_rule(
    pattern = ["git", "push", ["--force", "-f"]],
    decision = "forbidden",
    justification = "Use a normal push or explicitly perform the force-push yourself.",
)

prefix_rule(
    pattern = ["sudo"],
    decision = "prompt",
    justification = "System-wide mutation requires boundary review.",
)
```

Проверка rules до запуска:

```bash
codex execpolicy check --pretty \
  --rules ~/.codex/rules/default.rules \
  -- git reset --hard HEAD~1
```

Rules сопоставляют argv-prefix и надёжнее regex для прямой команды, но контролируют
выход за sandbox. Hook нужен для анализа сложной shell-строки и MCP/app calls.

## 11. Proxy: реальное состояние этой машины

Единственный источник выбора — `/mnt/data/Projects/Python/orchestra/.env`, строка
`HTTPS_PROXY`. Shell-функции `claude`, `codex` и `cursor` перечитывают её при каждом
запуске. Desktop Cursor стартует через `~/.local/bin/cursor-orchestra`, который читает
тот же файл и передаёт proxy в environment и Chromium `--proxy-server`.

Проверено 2026-07-13:

| Клиент | Реальный локальный proxy | Выходной IP/маршрут |
|---|---:|---|
| Claude Code worker | `127.0.0.1:12343` | Contabo DE `158.220.127.161` |
| обычный Codex CLI | `127.0.0.1:12343` | Contabo DE `158.220.127.161` |
| текущая Codex CLI-сессия | `127.0.0.1:12343` | подтверждён active socket |
| Cursor network service | значение Orchestra `.env` | после restart совпадает с Orchestra |
| Codex app-server внутри Cursor | значение Orchestra `.env` | наследует Cursor launch environment |

До унификации Cursor UI и Codex extension действительно шли через Hiddify `12334`,
тогда как Claude и standalone Codex шли через Contabo. Конфигурация исправлена:
фиксированные proxy-поля удалены из Cursor settings, а все новые процессы получают
текущее значение Orchestra `.env`. При нынешнем выборе все клиенты идут через Contabo.
После будущей смены proxy надо перезапустить уже работающие процессы: environment нельзя
изменить задним числом.

Все локальные endpoints сейчас подняты: `12334`, `12340`, `12341`, `12342`, `12343`,
`12345`. Проверка из sandbox ошибочно показывала их закрытыми, потому что Linux sandbox
использует отдельный network namespace.

Практическое правило диагностики:

```bash
env | rg -i '^(http|https|all|no)_proxy='
ss -tpn | rg '12334|12343'
curl --proxy http://127.0.0.1:12343 https://api.ipify.org
curl --proxy http://127.0.0.1:12334 https://api.ipify.org
```

Не определять фактический маршрут только по config-файлу: уже запущенный процесс хранит
старое окружение, а приложение может иметь собственный `http.proxy`.

## 12. Orchestra + Codex

Orchestra уже имеет `CodexBackend`:

- `gpt-*` направляются в Codex CLI;
- alias `codex` соответствует `gpt-5.6-sol`;
- новые turns идут через `codex exec --json`;
- продолжение — `codex exec resume`;
- usage из `turn.completed` пишется в session metadata.

Но сейчас backend запускает Codex с
`--dangerously-bypass-approvals-and-sandbox`. Поэтому глобальный safe profile не защитит
Orchestra-запуски, пока этот flag не будет убран. Для защищённой Orchestra следует:

1. убрать `--dangerously-bypass-approvals-and-sandbox`;
2. запускать с выбранным permission profile;
3. удалить или унифицировать UPPER/lowercase proxy-переменные;
4. добавить integration test на effective argv и environment;
5. проверить resume path отдельно — там формируется другая команда.

## 13. Usage и экономия квоты

В Codex CLI:

```text
/status
/statusline
```

В `/statusline` включить:

- rate limits;
- context;
- token counters;
- model + reasoning;
- git branch;
- current directory.

Как меньше жечь квоту:

- давать узкий scope и acceptance criteria;
- не просить subagents там, где работа последовательная;
- не скармливать огромные логи — давать путь и pattern ошибки;
- держать durable rules в `AGENTS.md`, а не повторять их каждый prompt;
- использовать `/compact` после завершённого смыслового этапа;
- для mechanical задач снижать reasoning, для архитектуры повышать;
- не включать auto-review без нужды на каждой микрокоманде: routine work должен
  помещаться внутри profile.

## 14. Семидневный курс молодого бойца

### День 1 — TUI

Запустить проект, настроить `/statusline`, пройти `/status`, `/permissions`, `/model`,
`/reasoning`, сделать read-only исследование.

### День 2 — AGENTS.md

Мигрировать один `CLAUDE.md`, сократить минимум вдвое, проверить команды проекта.

### День 3 — Реальная правка

Дать маленький bugfix с тестом. Научиться steering, review diff и resume.

### День 4 — Headless

Выполнить одну задачу через `codex exec --json`, сохранить thread ID, продолжить через
`exec resume`.

### День 5 — Permissions

Сравнить `read-only`, `workspace-write` и custom permission profile. Проверить, что
секретный файл действительно недоступен, а рабочий проект записывается.

### День 6 — Subagents и review

Делегировать три независимых read-only аудита; затем выполнить `/review` одного diff.
Сравнить расход токенов с single-agent run.

### День 7 — Orchestra

Создать GPT-worker в Orchestra, проверить persistent resume, usage metadata, proxy socket
и поведение при rate limit. После этого решать, переводить ли orchestrator default с Claude.

## 15. Боевой checklist перед автономным запуском

- [ ] Есть чистый checkpoint/commit либо понятный dirty diff.
- [ ] `AGENTS.md` актуален и не содержит секретов.
- [ ] `/status` показывает ожидаемый workspace и profile.
- [ ] Запись разрешена только в нужные roots.
- [ ] Network policy соответствует задаче.
- [ ] `~/.ssh`, auth и credentials закрыты.
- [ ] Destructive hook/rules загружены и trusted.
- [ ] `/statusline` показывает limits/context.
- [ ] Для subagents разделены ownership файлов.
- [ ] В prompt есть verification и terminal condition.
- [ ] Для production/VPS mutation есть отдельный rollback.

## 16. Официальные источники

- [Codex CLI quickstart](https://learn.chatgpt.com/docs/codex/cli)
- [Developer commands и slash commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [Sandbox и approvals](https://learn.chatgpt.com/docs/agent-approvals-security)
- [Permission profiles](https://learn.chatgpt.com/docs/permissions)
- [Auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review)
- [Rules](https://learn.chatgpt.com/docs/agent-configuration/rules)
- [Hooks](https://learn.chatgpt.com/docs/hooks)
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Import from another agent](https://learn.chatgpt.com/docs/import)
- [Codex usage with ChatGPT plans](https://help.openai.com/en/articles/11369540-using-codex-with-chatgpt)
