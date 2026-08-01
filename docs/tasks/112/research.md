# #112 — Serena MCP: процессы, worktree-изоляция, LSP lifecycle и upgrade 1.6.1

Дата исследования: 2026-08-01.

## Вопрос

**Контекст.** Orchestra запускает Codex-воркеров в отдельных Git worktree. Serena подключена глобально как stdio MCP и для каждого активного проекта поднимает language server.

**Проверяемое изменение.** Сравнить текущую Serena 1.1.2 с 1.6.1, выяснить, можно ли безопасно делить или выгружать процессы и где управлять подключением.

**Baseline.** Serena 1.1.2 из `/home/maxim/.local/bin/serena`, глобальная запись Codex `--project-from-cwd`, отдельный Codex app-server на сессию.

**Решающий outcome.** `find_symbol` должен читать именно текущий worktree; committed/dirty содержимое другой ветки не должно подменяться главным checkout. Вторичные outcomes: число процессов, retained memory, отсутствие лишних language servers, восстановление после idle.

Общая память машины не исследовалась: это #113. Здесь учитываются только процессы Serena и их потомки.

## Короткий вердикт

1. **Главная проблема была не памятью, а тихой потерей изоляции.** Serena 1.1.2 с `--project-from-cwd` выбирала родительский `/mnt/data/Projects/Python/orchestra` для worktree без собственного `.serena/project.yml`. В одном live-снимке ошибочно привязаны 10 из 20 Serena roots; независимая проверка оркестратора нашла 16 таких запусков в логах за день. В синтетическом кейсе `find_symbol` реально вернул символ главного checkout и не увидел символ worktree.
2. **Upgrade 1.6.1 исправляет конкретный дефект.** Тот же `/tmp`-кейс после upgrade выбрал ближайшую worktree `.git`, вернул worktree-only символ и перестал видеть main-only символ. 1.6.1 установлена через изолированный `uv tool`; общий `serena_config.yml` не изменён.
3. **Один общий Serena instance для всех worktree — неподдерживаемая и операционно небезопасная схема.** Официально один HTTP instance можно делить только нескольким агентам одного проекта. Для разных проектов Serena рекомендует отдельные instances; разные worktree являются разными снимками кода, даже если общий Git common-dir один.[3] Session-level невозможность такой изоляции на уровне исходников не доказывалась и для рекомендации не требуется.
4. **В 1.6.1 нет idle eviction и нет lazy-on-first-tool запуска LSP.** Language server стартует в фоне сразу при активации проекта. Внешне убитый LS будет пересоздан при следующем symbolic tool, но это аварийное восстановление, а не поддерживаемая idle-выгрузка.
5. **TypeScript поднят не ошибочно.** Единственное наблюдаемое TS-дерево принадлежало `seedon-site/feat-attribution`, где `.serena/project.yml` явно содержит `languages: [typescript]`. Один logical TypeScript LS развернулся в wrapper + два `tsserver` (partial semantic и full) + `typingsInstaller`.
6. **Upgrade не заменяет уже живые процессы.** После установки executable уже 1.6.1, но 17 наблюдаемых Serena roots продолжали работать старым `/usr/bin/python3.13` процессом. Им нужен отдельный контролируемый recycle; сервис и живые сессии в рамках #112 не перезапускались.

## Гипотезы и falsifiers

### H1 — «Процессов много, потому что Serena стартует по экземпляру на Codex process»

Причина: stdio MCP — дочерний процесс клиента; Orchestra держит отдельный Codex app-server на worker session, а `codex_review` запускает дополнительный `codex exec`.

**Falsifier:** Serena roots имеют общего родителя/endpoint или один root обслуживает разные cwd.

**Результат: CONFIRMED.** У всех наблюдаемых roots родителем был конкретный Codex process; cwd совпадал с cwd app-server/review. Каждый root имел команду `serena start-mcp-server --context=codex --project-from-cwd`.

### H2 — «Один shared Serena безопасно заменит все instances»

**Falsifier:** официальный shared mode изолирует активный проект и кэш по MCP session так, что один process безопасно обслуживает разные worktree.

**Результат: REFUTED как поддерживаемая эксплуатационная схема.** Документация допускает shared HTTP instance для нескольких агентов **одного проекта**, но для разных проектов предписывает отдельный instance.[3] Worktree содержат разные снимки файлов, поэтому делить instance между ними нельзя без отдельно доказанной session-level изоляции active project и cache; такого доказательства в документации нет, а source-level конкурентный тест в рамках #112 не выполнялся.

### H3 — «Новая версия даёт idle unload/lazy LSP и поэтому решит память»

**Falsifier:** release changelog или 1.6.1 source содержит idle timeout/eviction либо LSP создаётся только на первом symbolic call.

**Результат: REFUTED.** В конфиге 1.6.1 есть `tool_timeout`, но нет inactivity timeout. `_activate_project` сразу ставит `_init_active_project_language_backend()` в background task, а `Project.create_language_server_manager()` запускает по одному LS на каждый настроенный язык. Changelog говорит о background **определении языков**, а не о lazy LSP.[2]

### H4 — «Upgrade исправляет worktree hijack без дополнительного `project.yml`»

**Falsifier:** тот же worktree без `.serena/project.yml` после 1.6.1 всё ещё выбирает ancestor project или читает main-only symbol.

**Результат: CONFIRMED.** До/после эксперимент ниже дал противоположные, ожидаемые результаты.

### H5 — «Serena никому не нужна, её можно выключить»

**Результат: REFUTED до начала исследования.** Переданный замер за 7 дней: 858 Serena calls, из них 492 `find_symbol`; top consumers — `audit-worktree` 173, `feat-mccfr-scale` 171, `upgrade-claude5` 113, `grok-quota` 74. Повторный подсчёт не делался по прямому указанию задачи.

## Прямые измерения

### M1 — откуда берутся roots

Текущая конфигурация:

```text
~/.codex/config.toml:
{'command': 'serena',
 'args': ['start-mcp-server', '--context=codex', '--project-from-cwd']}

~/.claude.json: Serena entry отсутствует
<scope>/.mcp.json: Serena entry отсутствует
```

`app/backend_codex.py:216-246` запускает отдельный `codex app-server --stdio` с `cwd=self.cwd`. Он передаёт Orchestra MCP через `-c`, но не отключает глобальный Codex MCP config. Поэтому глобальная Serena автоматически стартует внутри каждого worker app-server.

`app/mcp_stdio.py:944-1055` запускает `codex exec` для `codex_review` без `mcp_servers.serena.enabled=false`; review process тоже наследует глобальную Serena. В одном снимке это были 4 дополнительных Serena roots. Этот ресурсный вклад передан в #113.

### M2 — процессные деревья и языки

Снимок `/proc` меняется вместе с числом активных workers/reviews. В 14:14 наблюдалось 20 Serena roots; 16 принадлежали worker app-server, 4 — `codex_review`. Типовые деревья:

```text
Python project (4 процесса):
serena
└─ /bin/sh -c python -m pyright
   └─ python pyright wrapper
      └─ node pyright-langserver

TypeScript project (6 процессов):
serena
└─ /bin/sh -c typescript-language-server --stdio
   └─ node typescript-language-server
      ├─ tsserver.js --serverMode partialSemantic ...
      ├─ tsserver.js ...
      └─ typingsInstaller.js ...
```

У `seedon-site/feat-attribution` конфиг явно задавал `languages: [typescript]`; его process tree ровно соответствовал второму варианту. У `seedon/dev-lead` было `languages: []` и только Serena root. Следовательно, перечень LS задаёт `.serena/project.yml`; глобально «оставить только Python» нельзя — это сломает реальные TypeScript-проекты.

Официальная документация подтверждает: project config задаёт языки, для которых spawned language servers, и workspace folders.[3] Auto-detection добавляет только самый представленный язык по умолчанию; в нашем post-upgrade `/tmp`-кейсе с одним Python-файлом 1.6.1 сгенерировала `languages: [python]`.

### M3 — RSS против swapped footprint

Serena-only `/proc/*/smaps_rollup` snapshot:

```text
worker app-server instances:
  16 roots / 63 tree processes
  RSS 1547.7 MiB
  PSS 135.8 MiB
  SwapPss 3281.9 MiB
  PSS+SwapPss 3417.7 MiB

codex_review instances:
  4 roots / 16 tree processes
  RSS 797.7 MiB
  PSS 455.8 MiB
  SwapPss 215.0 MiB
  PSS+SwapPss 670.8 MiB
```

Числа snapshot-dependent: новые LS были resident во время indexing, старые были в основном вытеснены в swap. Поэтому сумма RSS около 0.9–2.3 GiB в разные минуты не описывает retained footprint под сильным swap pressure. Общая арифметика машины оставлена #113.

### M4 — live worktree hijack на 1.1.2

В одном live-снимке сравнивались Serena cwd и первая строка `Auto-detected project root` из соответствующего `~/.serena/logs/.../mcp_*_<pid>.txt`:

```text
roots=20 correct=10 misbound=10
```

Примеры:

```text
cwd=/.../orchestra/research-memory
active=/mnt/data/Projects/Python/orchestra

cwd=/.../seedon-site/feat-remove-ip-api
active=/mnt/data/Projects/Python/orchestra
```

Worktree с собственным `.serena/project.yml` выбирались правильно. Worktree без него попадали под известный bug 1.1.2: ancestor Serena project выигрывал у более близкой worktree `.git`. Changelog 1.6.0 описывает именно этот дефект и его последствие: stale reads и misdirected edits.[2]

### M5 — воспроизводимый до/после кейс

Fixture: `/tmp/orchestra-serena112-hijack-20260801`.

- главный checkout имеет untracked `.serena/project.yml` и функцию `main_checkout_only()`;
- nested Git worktree `worktrees/worker` не имеет своего `.serena/project.yml` и вместо неё содержит `worker_branch_only()`;
- MCP запускается из cwd worktree с `--project-from-cwd`;
- probe явно передаёт полный `env` в MCP stdio subprocess; `SERENA_HOME` отдельный в каждом прогоне, поэтому живой registry/config не участвует.

**До, Serena 1.1.2:**

```text
Auto-detected project root: /tmp/orchestra-serena112-hijack-20260801
Active project: serena112-main
find_symbol(main_checkout_only)   -> MAIN_CHECKOUT_SENTINEL
find_symbol(worker_branch_only)   -> []
```

**После, установленная Serena 1.6.1, тот же fixture без worktree project config:**

```text
Auto-detected project root: /tmp/orchestra-serena112-hijack-20260801/worktrees/worker
Active project: worker
find_symbol(main_checkout_only)   -> []
find_symbol(worker_branch_only)   -> WORKER_BRANCH_SENTINEL
```

**Pass.** Изменилось именно содержимое, которое возвращает symbolic tool, а не только строка лога.

Первый вариант probe не передавал `env` в `StdioServerParameters`, поэтому MCP SDK отфильтровывал `SERENA_HOME` и оба запуска читали живой global config. После замечания Codex эксперимент повторён с явным `env=dict(os.environ)` и двумя чистыми homes. Герметичные raw outputs: `/tmp/serena112-hermetic-before.{out,err}` и `/tmp/serena112-hermetic-after.{out,err}`; каждый home содержит собственные `serena_config.yml` и log.

## Idle и внешнее завершение LS

### Собственного idle timeout нет

В Serena 1.1.2 и 1.6.1 не найден inactivity/idle config или eviction loop. `tool_timeout: 240` ограничивает один tool call. `Project.shutdown()` останавливает LS при смене проекта или завершении Serena; MCP root остаётся жить столько, сколько живёт клиент.

Это совпадает с live-измерением: Serena roots оставались у idle/waiting sessions 33–60 минут. В Orchestra Codex runtime имеет `hibernate=False`, поэтому общий 5-минутный worker hibernate не применяется. Причина/исправление lifecycle принадлежит #113, не #112.

### Можно ли внешне погасить только LS

Технически следующий symbolic call проверяет `is_running()` и пересоздаёт LS; если LS умер во время tool call, wrapper перезапускает его и один раз повторяет вызов. Но отдельного API «unload until next use» нет.

Принудительный child kill не рекомендуется:

- есть race с активным LSP request;
- теряется warm index/process state и добавляется cold-start latency;
- неаккуратный kill может оставить потомков; исправление orphaned LS при SIGKILL/OOM пока находится только в **Unreleased main**, не в 1.6.1.[2]

Безопасная граница lifecycle — owning Codex backend/MCP connection, а не отдельный `tsserver`/pyright child. Это следует решать в #113 через controlled hibernate/reconnect.

## Upgrade 1.1.2 → 1.6.1: что изменилось и риск

На момент проверки официальный PyPI latest — **1.6.1 от 2026-07-21**; исходно было **1.1.2 от 2026-04-14**.[1]

### Ресурсные и correctness изменения

- **1.2.0:** HTTP prompts стали session-aware; system prompt стал lazy. Это улучшает shared HTTP correctness, но не разделяет разные projects.[2]
- **1.3.0:** исправлен partial agent shutdown при disconnect одного HTTP client.[2]
- **1.5.2:** pyright/fortls устанавливаются on demand вместо bundle; это packaging/disk change, не idle memory management.[2]
- **1.6.0:** исправлен nested-worktree hijack; auto-detection языков перенесён в background thread; добавлен `ls_workspace_folders`; для TypeScript/VTS отключена automatic typing acquisition на старте.[2]
- **1.6.1:** исправлены stale symbolic results после внешних file changes и лишняя invalidation raw symbol cache.[2]
- **Нет:** нового shared mode, idle eviction или lazy language-server startup. Shared HTTP для same-project — уже существующая архитектура.[3]
- **Unreleased, не считать полученным:** Linux orphan cleanup при unclean Serena termination, Codex `SessionEnd` cleanup hooks, Rust memory tuning и переименование `languages` → `language_servers`.[2]

### Breaking/API audit

1. **Project mode config.** В 1.3 project-level `base_modes` больше нельзя override; нужен `added_modes`.[2] Read-only scan 32 существующих worktree `.serena/project.yml`: ни в одном нет непустого `base_modes`/`default_modes` override. New 1.6.1 parser загрузил global config copy и все 32 project configs: `32 ok / 0 failed`.
2. **Project schema.** 1.6.1 всё ещё читает и генерирует ключ `languages`; rename в `language_servers` находится только в Unreleased. Сгенерированный post-upgrade config подтвердил `languages: [python]`.
3. **Tool surface.** MCP `tools/list` на одинаковом project:

   ```text
   1.1.2: 21 tools
   1.6.1: 24 tools
   removed: check_onboarding_performed
   added: find_declaration, find_implementations,
          get_diagnostics_for_file, replace_in_files
   ```

   `check_onboarding_performed` вызывался 6 раз за последние 7 дней. В новой версии onboarding status перенесён в activation message. Для новых MCP connections tool catalog корректен; старый вызов из сохранённого контекста может один раз получить `tool not found`.
4. **Cache/index smoke.** Staged 1.6.1 запущена на текущем real worktree и существующем `.serena` layout: MCP initialize успешен; `find_symbol(CodexBackend)` и `find_symbol(_codex_factory)` вернули символы. Отдельный `/tmp` fixture прошёл auto-generation и Python indexing.

### Как установлен upgrade и как откатить

Использован официальный isolated tool layout, а не `pip --user`: pip dry-run требовал бы обновить общие user-site `anthropic`, `mcp`, `starlette`, `cryptography` и другие зависимости.

```text
before executable: /home/maxim/.local/bin/serena (plain launcher)
before version:    1.1.2

install:
uv tool install --force --no-python-downloads -p 3.13 serena-agent==1.6.1

after executable:
/home/maxim/.local/bin/serena ->
/home/maxim/.local/share/uv/tools/serena-agent/bin/serena
after version: 1.6.1
```

Проверка: SHA-256 живого `~/.serena/serena_config.yml` до/после одинаковый (`d008f2...fec`). User-site package 1.1.2 не удалён.

Надёжный rollback — повторная изолированная установка точной предыдущей версии из PyPI, а не восстановление временного launcher:

```bash
uv tool install --force --no-python-downloads -p 3.13 serena-agent==1.1.2
```

Эта команда проверена без переключения live executable через отдельные `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR`: install завершился `rc=0`, installed metadata вернула `1.1.2`, launcher вернул `start-mcp-server --help` с `--project-from-cwd`. Raw outputs: `/tmp/serena112-rollback-install.{out,err}` и `/tmp/serena112-rollback-help.{out,err}`. После реального rollback версия проверяется через metadata, потому что 1.1.2 ещё не поддерживает `serena --version`:

```bash
/home/maxim/.local/share/uv/tools/serena-agent/bin/python \
  -c "from importlib.metadata import version; print(version('serena-agent'))"
```

Копии старых launcher/config и wheel в `/tmp/orchestra-serena112-*` остаются только краткоживущей локальной страховкой; план отката от них не зависит. Откат live executable не выполнялся, поскольку post-upgrade проверки прошли.

## Нужна ли страховка `--project` / `project.yml`

**Для известного дефекта 1.6.1 достаточна:** точный before/after test доказывает, что ближайшая worktree `.git` теперь выигрывает даже без project config. Обязательное создание `.serena/project.yml` не нужно как hotfix.

**Как defense-in-depth явный путь всё равно оправдан:** цена regression — тихие ответы по чужой ветке. Предпочтительный отдельный дизайн после #93:

- убрать Serena из безусловного глобального Codex config;
- inject Serena per worker через Orchestra с `--project <exact-worktree-path>`;
- для `codex_review` явно отключать Serena, если review workflow использует встроенные code tools;
- smoke-test должен создавать nested worktree без project config и проверять content sentinel, как M5.

Это среднерисковая правка shared spawn/runtime, а не часть upgrade. Простое копирование `project.yml` во все worktree слабее: это ещё один snapshot, который может устареть, и его нужно синхронизировать.

## План мероприятий: цена и риск

| Приоритет | Мера | Статус / цена | Риск | Проверка |
|---|---|---|---|---|
| P0 | Upgrade Serena 1.1.2 → 1.6.1 isolated `uv tool` | **Сделано**; минуты, без shared Python dependency upgrade | Низкий–средний: удалён один редко используемый tool; живые roots остаются старыми | M5 before/after; 32/32 configs parse; real-worktree symbol smoke |
| P0 | Безопасно перевести уже живые Serena 1.1.2 owners на 1.6.1 | Не сделано; сначала нужен atomic drain/reconnect в lifecycle owner либо согласованное maintenance-окно | Высокий без drain: проверка `idle` гоняется с новым send и может оборвать turn; без recycle текущие misbound sessions не исправлены | Заблокировать новые sends → дождаться завершения turns → disconnect/reconnect с сохранённым session ID → проверить root/version → открыть sends; при отсутствии такой блокировки только согласованный restart с явно принятой потерей текущих turns |
| P1 | Отдельная #93-follow-up: explicit per-worker `--project`, убрать unconditional global inheritance, content-level regression test | 0.5–1 инженерный день | Средний: shared runtime/MCP wiring затрагивает все Codex sessions | spawn worker без `.serena`, main/worktree sentinels; test `codex_review` не стартует Serena |

Не рекомендованные меры:

- **Выключить Serena глобально:** опровергнуто 858 вызовами/7 дней.
- **Один HTTP instance на все worktree:** неподдерживаемая схема с недоказанной session-level изоляцией; официальный shared case ограничен одним project.[3]
- **Глобально оставить только Python:** сломает реальные TypeScript projects; текущий TS server был настроен правильно.
- **Периодически `kill` language-server children:** unsupported race-prone workaround; lifecycle должен принадлежать MCP/Codex owner.

## Confidence и counter-evidence

- **CONFIRMED — worktree hijack 1.1.2 и fix 1.6.1.** Tier 1: один и тот же `/tmp` fixture проверен через реальные MCP `find_symbol`; Tier 2: официальный changelog описывает тот же bug.
- **CONFIRMED — per-Codex stdio topology.** Tier 1: `/proc` parent/cwd/command snapshot; Tier 2: Orchestra source и официальная client config.
- **CONFIRMED — TypeScript tree был легитимным.** Tier 1: project config + exact process cmdline.
- **CONFIRMED — нет idle eviction/lazy LS в 1.6.1.** Tier 2: installed release source/config and official changelog; Tier 1 live roots переживали idle. Absence claims are version-specific.
- **LIKELY — external LS kill восстановится на следующем symbolic call.** Tier 2 source содержит `is_running()` restart и one-retry path; отдельный destructive experiment на живом процессе не выполнялся.
- **UNCERTAIN — точная экономия от будущего hibernate/review exclusion.** Process population и resident/swap distribution быстро меняются; расчёт и owner lifecycle переданы #113.

Counter-evidence/ограничения:

1. Наличие собственного `.serena/project.yml` уже защищало часть worktree на 1.1.2; bug не поражал абсолютно все sessions.
2. Shared HTTP полезен, если несколько agents действительно работают с **одним и тем же exact project/worktree**. В нашем снимке повторный cwd возникал главным образом из-за `codex_review`, который разумнее запускать без Serena, чем строить shared service только ради него.
3. Upgrade не уменьшил число уже работающих 1.1.2 processes и сам по себе не выгрузил память.
4. Unreleased improvements не входят в 1.6.1 и не использованы в выводе о текущем результате.
5. Общий HTTP instance теоретически мог бы получить полноценную session-level изоляцию в будущей реализации; #112 доказал отсутствие поддерживаемого контракта для разных worktree, а не математическую невозможность такого дизайна.

## Источники

1. [PyPI: serena-agent release history, latest 1.6.1 (2026-07-21)](https://pypi.org/project/serena-agent/) — primary package registry.
2. [Official Serena CHANGELOG](https://raw.githubusercontent.com/oraios/serena/main/CHANGELOG.md) — primary source; разделы 1.2.0–1.6.1 и Unreleased.
3. [Official Serena workflow: projects, languages, multiple agents](https://oraios.github.io/serena/02-usage/040_workflow.html) — primary documentation.
4. [Official Serena client setup: stdio/HTTP and Codex global config](https://oraios.github.io/serena/02-usage/030_clients.html) — primary documentation.

Локальные primary sources/measurements:

- `/home/maxim/.codex/config.toml` — только Serena MCP stanza читалась, секреты не выводились.
- `app/backend_codex.py:216-246`, `app/runtime_registry.py:208-217`, `app/mcp_stdio.py:944-1055`.
- Serena 1.1.2 source: `/home/maxim/.local/lib/python3.13/site-packages/serena/`.
- Serena 1.6.1 isolated source: `/home/maxim/.local/share/uv/tools/serena-agent/lib/python3.13/site-packages/serena/`.
- Герметичные raw before/after: `/tmp/serena112-hermetic-before.out`, `/tmp/serena112-hermetic-before.err`, `/tmp/serena112-hermetic-after.out`, `/tmp/serena112-hermetic-after.err`.
