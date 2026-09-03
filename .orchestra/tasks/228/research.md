# Research #228 — аудит принуждения ограничений агентов

Дата среза: 2026-08-12. Исследование не меняет runtime, настройки или prompts.

## Вопрос

- **Контекст:** Orchestra запускает Claude/Codex/Grok-агентов с системными prompts,
  CLI-аргументами, MCP-инструментами, admission-кодом и role/pipeline-конфигурацией.
- **Изменение под проверкой:** заменить доверие к текстовым запретам платформенным
  принуждением там, где нарушение может совершить запрещённое действие.
- **Baseline:** текущий код и конфигурация; prompt считается только инструкцией, пока
  отдельный прогон не покажет, что действие физически остановлено.
- **Решающие исходы:** где живёт каждое ограничение, какой seam ему нужен, вызывается
  ли guard, совершился ли side effect, что увидели агент и parent, и безопасны ли оба
  направления prompt-ошибки.

Полная построчная карта: [`enforcement-matrix.md`](enforcement-matrix.md). Сырые и
изолированные прогоны: [`probes/`](probes/).

## Гипотезы и falsifiers

1. **H1 — exact tool-name deny физически принуждается.**
   Опровергнет фактическое исполнение запрещённого built-in или MCP tool.
   **Итог: подтверждено.** `--disallowedTools` удалил `Read` и один exact MCP tool;
   соседний MCP tool остался.
2. **H2 — роль сама по себе создаёт role-specific Orchestra MCP ACL.**
   Опровергнет одинаковый catalog при разных `ORCHESTRA_ROLE`.
   **Итог: опровергнуто.** Worker и orchestrator получили одинаковые 36 full / 12
   read-only tools; доступ меняется только `ORCHESTRA_ACCESS_MODE`.
3. **H3 — `can_use_tool` является обязательным interposition и может держать
   payload-инвариант.** Опровергнет разрешённый call с нулём callback invocations.
   **Итог: опровергнуто.** `Bash(run_in_background=true)` исполнился, callback = 0.
4. **H4 — `PreToolUse` видит payload до исполнения даже при широком allow.**
   Опровергнут созданный command-marker, отсутствие hook event либо allow, победивший
   hook deny. **Итог: подтверждено.** При `Bash(*)` hook вернул exit 2, marker не
   появился.
5. **H5 — большинство prompt-ограничений можно перенести в tool hooks.**
   Опровергнет большой самостоятельный класс правил, зависящих от истории/состояния
   или смысловой оценки. **Итог: скорее опровергнуто.** Найдены 15 конкретных
   NAME/PAYLOAD backlog bundles и 33 runtime/culture bundles, причём несколько
   culture rows схлопывают десятки отдельных checks. Точный процент не заявляется:
   гранулярность bundles неодинакова.

## Главный результат: три ступени, а не «prompt против code»

1. **Имя tool → catalog deny.** `disallowedTools` работает сегодня и применим к
   exact built-in и fully-qualified MCP name.
2. **Аргументы tool → обязательный `PreToolUse`.** `can_use_tool` — лишь замена
   permission prompt для calls, которые ещё не были разрешены; это не guard каждого
   вызова. Production `PreToolUse` в Orchestra сейчас не настроен ни разу.
3. **Состояние/последовательность/авторизация → Orchestra runtime или честная
   рекомендация.** Hook не знает, был ли approval, чей это worker, какой RED commit
   заморожен и сколько review rounds уже потрачено, если это состояние не ведёт
   сервер.

**CONFIRMED — evidence tier 1:** все три границы доказаны текущими executable
прогонами. Для semantics `can_use_tool` и `PreToolUse` дополнительно открыта
официальная документация Claude Code [1][2] и установленный SDK source
`claude_agent_sdk/types.py:1888-1908`.

## 1. Механика tool-name enforcement

### Каталог различается по ролям только частично

Production argv:

```text
worker:       --disallowedTools ScheduleWakeup,CronCreate,CronDelete,CronList,Workflow
orchestrator: --disallowedTools ScheduleWakeup,CronCreate,CronDelete,CronList,Workflow,Task,Agent
```

Свежие CLI init catalogs показали `Task=true` у worker и `Task=false` у
orchestrator. Отдельный `Agent` в Claude Code 2.1.197 не рекламировался ни в одном
catalog. `SendMessage` и `Monitor` присутствовали у обеих ролей. Значит, фраза
`NEVER use built-in Agent` не совпадает с фактическим worker capability: его
эквивалентный native delegation tool `Task` оставлен намеренно.

**CONFIRMED — tier 1:** два role CLI run, exit 0; raw:
`probes/tools/role-worker.raw.jsonl`, `role-orchestrator.raw.jsonl`.

### Exact deny действительно останавливает tool, включая MCP

- `--disallowedTools Read` удалил `Read` из init catalog.
- `--disallowedTools mcp__probe__ping` сделал `ping` недоступным через ToolSearch,
  при этом `mcp__probe__second` с того же server остался доступен.
- Без deny control находил `mcp__probe__ping`.

Это означает: механизм точечного запрета конкретного MCP tool конкретной роли уже
есть на Claude launch seam. Он просто не заполняется role-specific Orchestra names:
`_ORCH_DISALLOWED_TOOLS` содержит только `Task`, `Agent`, а декларативного MCP ACL в
manifest нет.

Физика отказа **тихая для parent и result status**: tool отсутствует, turn завершается
успешно, `permission_denials=[]`. Модель видит отсутствие или `No matching deferred
tools found`; parent не получает отдельное событие.

**CONFIRMED — tier 1:** baseline + exact deny CLI, sibling counter-control; raw:
`probes/tools/mcp-baseline.raw.jsonl`, `disallowed-cli.raw.jsonl`.

### Orchestra MCP role catalog сейчас общий

Четыре disposable MCP server процесса дали:

```text
orchestrator/full       36
worker/full             36
orchestrator/read-only  12
worker/read-only        12
```

Full catalogs и read-only catalogs попарно равны. `ORCHESTRA_ROLE` меняет отдельные
ответы (`list_agents`), но не registration; `manager._make_mcp_config()` передаёт
`ORCHESTRA_ACCESS_MODE=full` всем managed roles. Read-only capability работает, но
не используется для role separation. Измеренный mocked worker-role вызов
`kill_worker(force=true)` дошёл до `DELETE ... force=true`.

**CONFIRMED — tier 1:** 2×2 catalog matrix + server boundary probe; raw:
`probes/tools/catalogs.raw.json`, `probes/inventory/findings.md` F7.

## 2. `can_use_tool`: найденный guard не является enforcement

В `_make_auto_approve` четыре логические политики:

1. `AskUserQuestion` — deny всем;
2. `Monitor` — deny всем;
3. `Agent` — deny orchestrator (резервная ветка: catalog уже удаляет tool);
4. любой payload с `run_in_background=true` — deny.

Реальный `ClaudeBackend` дал два разных исхода:

```text
AskUserQuestion:
  callback invocations = 1
  decision = PermissionResultDeny
  tool_result = "AskUserQuestion is not available in Orchestra.", is_error=true

Bash(run_in_background=true):
  callback invocations = 0
  tool_result = "Command running in background ...", is_error=false
  turn_end ok=true
```

Повтор Bash был сделан с `inherit_claude_md=False` и пустым cwd. То есть user/project
settings не загружались, но обход сохранился. Живой `Bash(*)` усиливает проблему,
потому что auto-approves весь Bash, но не является причиной. Причина — порядок
permission engine: call, уже разрешённый CLI, до `can_use_tool` не доходит [2].

Формулировка `run_in_background — BLOCKED` сейчас фактически ложна. Снимать её нельзя:
side effect запрещён по последствиям (detached process погибает/теряется после turn),
а обязательный payload seam существует. Приговор — **перенос в `PreToolUse`**, не
ослабление текста.

**CONFIRMED — tier 1:** два instrumented real-backend runs и физическое исполнение
без ошибки. Raw summary: `probes/local/runtime-probes.md` P3–P4.

## 3. `PreToolUse`: обязательная payload-врезка существует и побеждает wildcard

Изолированная настройка `probes/hooks/settings.json` намеренно содержала одновременно:

```json
"permissions": {"allow": ["Bash(*)"]}
"hooks": {"PreToolUse": [{"matcher": "Bash", ...}]}
```

CLI был запущен с `--setting-sources ''`, поэтому user/project/local filesystem
settings отсутствовали. Bash должен был создать marker только при фактическом
исполнении.

```text
tool_use Bash {..., "run_in_background": true}
hook_started PreToolUse
hook_response exit_code=2 outcome=error
HOOK_CALLED ... run_in_background=True
HOOK_DENY background Bash probe
tool_result is_error=true
permission_denials=[исходный Bash payload]
execution_marker_test_exit=1
```

Положительный hook event доказывает вызов; отсутствующий marker доказывает именно
предотвращение исполнения, а не отказ после side effect. `Bash(*)` hook не поглотил.
Это согласуется с официальной документацией: `PreToolUse` выполняется до permission
prompt и exit 2 блокирует tool call [1][2].

**CONFIRMED — tier 1 + primary source:** raw:
`probes/hooks/pretooluse-run.raw.txt`; reproducible config/script рядом.

### Накладные текущего command-hook

Два валидных CLI-прогона по 24 последовательных `Bash(true)` дали hook coverage
48/48:

| Run | samples | p50 | p95 | min | max |
|---|---:|---:|---:|---:|---:|
| hook-1 | 24 | 54.806 ms | 98.955 ms | 42.498 ms | 154.167 ms |
| hook-2 | 24 | 60.403 ms | 111.988 ms | 47.352 ms | 276.882 ms |

Валидный no-hook batch занял 8259.757 ms; hooked batches — 7915.497 и
8547.431 ms. Полный model/tool-loop noise больше разницы, поэтому end-to-end A/B не
выделяет добавку. Измеряемая стоимость именно текущего command-hook с отдельным
Python process: **≈55–60 ms p50 и ≈99–112 ms p95 на Bash call**. In-process guard
может быть дешевле; это гипотеза, не измерение. Второй baseline исключён: модель
сделала 23/24 вызова.

**CONFIRMED — tier 1:** 48 matching `hook_started→hook_response` intervals; raw:
`probes/hooks/hook-overhead.raw.txt`, runner `measure_hook_overhead.py`.

## 4. Инвентаризация и граница допустимого счёта

420 lexical candidate lines были организованы в 48 audit bundles. Это навигационная
карта owners/backlog, а не census правил: N5 объединяет пять tool names, A3 — десятки
process checks. Полного candidate→bundle ledger нет, поэтому точная доля была бы
неаудируемой. Все 48 bundles перечислены в `enforcement-matrix.md`.

| Нужный механизм | Backlog bundles | Полностью enforced сейчас |
|---|---:|---:|
| NAME | 6 | 1; ещё 1 частично |
| PAYLOAD | 9 | 0 (`PreToolUse` production uses = 0) |
| RUNTIME, unsafe при забывании | 18 | 3 узких guard; остальные partial/text |
| Semantic/culture | 15 | Не применимо |
| **NAME + PAYLOAD** | **15 конкретных bundles** | Не точная доля правил |

То есть итог не «перенести всё в hooks». Есть 15 конкретных NAME/PAYLOAD bundles;
ещё 18 runtime bundles требуют server state/capability boundary, а 15 culture
bundles должны честно называться методикой. Поскольку culture bundles агрегируют
много отдельных rules, вывод «tool-layer — меньшинство» **LIKELY**, но точной доли
исследование не доказывает.

### Готовый backlog payload-hooks

1. `Bash.run_in_background` — прямой и полностью проверяемый payload invariant.
2. Явные destructive Bash signatures (`rm -r/-rf`, `chmod 777`, `curl | bash`).
3. Явные service/deploy/VCS mutations (`systemctl restart/stop/start`, `git push/pull`).
4. Direct Read/Edit/Write paths вне worktree/`owned_dirs` и protected dotpaths.
5. Direct mutation путей immutable test/oracle.
6. `kill_worker(force=true)` как дополнительный deny для разрешённых ролей.
7. `send_message`/`send_file` target constraints как дополнительный role-aware deny.
8. Очевидные secret forms/path/content at egress.
9. Очевидные polling/resource patterns (`sleep` loops, huge `/tmp` writes).

Только пункт 1 закрывается hook полностью на измеренном interface. Пункты 2–5 и
8–9 имеют обход через произвольный shell/interpreter; пункты 6–7 зависят от server
identity/state. Поэтому их hook — defense-in-depth, не окончательный security
boundary.

## 5. Что уже hard, но имеет узкую область

- **Known-role spawn topology:** `worker -> worker` получает ValueError/409 до
  worktree. Counterexample: `validation: fail-open` позволяет `worker -> ghost` в
  узком validator; полный manager падает раньше на prompt resolution. Это не
  fail-closed policy, а независимая ранняя ошибка.
- **Weekly quota:** новый worker turn при 95% получает `QuotaGateError`/429 до
  publish. Running steering и orchestrators исключены по дизайну. Это реальный guard,
  но не общий token budget.
- **cwd admission:** `/home/kesha/.ssh` получает 403. После старта это не filesystem
  sandbox; абсолютная запись остаётся возможна.
- **owned_dirs overlap:** конфликт declared dirs отклоняет spawn. Измеренная запись
  вне declared `claimed/` после spawn успешно создала файл.
- **non-force kill guards:** running/child/dirty/unmerged состояния отклоняют kill;
  `force=true` их обходит, а semantic lifecycle/DONE/gate не читается.
- **read-only MCP mode:** реально сокращает catalog с 36 до 12, но managed roles
  получают `full`.
- **Codex native multi-agent:** launch строится с `features.multi_agent=false`, но
  Codex Orchestra MCP остаётся full; это narrow guard, не общий запрет delegation.

**CONFIRMED — tier 1:** 35 focused tests passed, плюс isolated manager/filesystem/API
falsifiers. Commands and output: `probes/inventory/findings.md` F3–F12.

## 6. Самые опасные prompt-only/partial ограничения

| Приоритет | Gap | Измеренный физический исход | Нужный owner | Rough cost |
|---|---|---|---|---|
| P0 | Запрещённая модель | Terra session accepted; отдельный реальный failure 1/1 в #227 | Server model policy/router | Ведёт #227; не дублировать |
| P0 | Background Bash | Команда исполнилась, callback=0 | `PreToolUse` | S: один payload guard + cross-runtime tests |
| P0 | Worker MCP authority | Все роли full 36; force kill дошёл до DELETE | Role catalog + server ACL | M: catalog config + endpoint identity tests |
| P0 | Filesystem/shell/external mutation | Out-of-territory write succeeds; runtimes permissive | Capability/sandbox/OS + auth | L: cross-runtime boundary, не regex-only hook |
| P1 | Built-in SendMessage/worker Task/Ask/Monitor | Tools присутствуют; только Ask measured callback deny | Exact role name deny | S–M: Claude config simple, cross-runtime parity adds work |
| P1 | Permanent kill lifecycle | Force bypasses hard checks | Server lifecycle/authorization | M |
| P1 | Token budget | #198: 8,095 vs 1,000 | Runtime supervisor | M–L depending on backend cancellation |
| P1 | Phase/oracle/review state | Files writable; phase/review ledger absent | Server task state | L |
| P1 | Denial visibility | Tool error persisted, `_did_report=false` | Server event delivery | S–M |
| P2 | Cultural rules called “BLOCKED/NEVER” | No refusal; only transcript evidence | Wording + telemetry | S per owner, but semantics require review |

`S/M/L` are relative implementation sizes, not calendar promises: S = one existing
seam + focused tests; M = shared runtime/config + role matrix; L = cross-runtime state
or OS capability architecture. Confidence on these cost labels is **UNCERTAIN**;
Phase 1 did not design/implement them.

## 7. Visibility and informing

- Catalog deny: tool absent; no `permission_denials`; parent not notified.
- `can_use_tool` deny: loud `tool_result is_error=true` to agent, persisted as
  tool_result/tool_error; turn itself can remain success.
- `PreToolUse` exit 2: loud hook error to agent, `permission_denials` populated,
  physical action stopped; turn itself still success.
- Real session-handler probe after a denial had `_did_report=false`: parent learns
  only by log inspection. No automatic security/denial message exists.

Следовательно, «fail loud» для агента и «inform parent» — разные требования. Tool
enforcement не решает audit notification автоматически.

## Counter-evidence and limits

- `can_use_tool` не бесполезен: measured `AskUserQuestion` действительно был
  остановлен. Опровержение уже: это не **обязательный** guard всех calls.
- Exact deny запрещает имя, не capability. После deny `Read` модель смогла читать
  через разрешённый `Bash(cat ...)`. Поэтому tool minimization ≠ sandbox.
- `PreToolUse` доказан только на Claude Code 2.1.197. Codex/Grok/OpenCode требуют
  собственный mandatory seam либо server-side MCP/OS enforcement.
- Hook overhead измерен на Haiku и command-hook через fresh Python process; он не
  переносится автоматически на in-process implementation.
- 48 — число audit bundles, а не canonical rules. Иной split меняет denominator;
  candidate→bundle ledger не публиковался. Поэтому предыдущая точная доля снята,
  остаются 15 явно перечисленных tool-layer backlog bundles и qualitative verdict.
- Inventory sub-study первоначально счёл `run_in_background` hard по прямому вызову
  Python callback. Live counter-run опроверг этот вывод; итоговая матрица использует
  физический backend result, а не return value невызванной функции.

## Приговор по двустороннему критерию

- **Оставить в prompt как культуру:** A1–A15, но не называть их platform blocks.
  Забывание/over-application меняет качество, стоимость или полноту; LLM нужна для
  semantic judgment.
- **Prompt недостаточен:** N1–N6, P1–P9, R2–R3, R5–R11, R13–R18. Хотя бы одно
  направление ошибки совершает запрещённое действие, теряет данные/authority или
  скрывает обязательный result.
- **Уже code-enforced в узкой области:** R1 known roles, R4 weekly new-worker quota,
  R12 cwd admission, плюс отдельные partial guards. Их prompt должен описывать точную
  область, не расширять её словами «всегда/blocked».

## Adversarial second opinion

Codex round 1 подтвердил несущую механику, но заблокировал прежнюю точную долю:
строки матрицы имели разную гранулярность, а полного candidate→row ledger не было.
Точная доля снята; 48 переопределены как navigation bundles, 15 — как конкретно
перечисленный tool-layer backlog. Также исправлены устаревшая классификация background
guard в inventory и неподтверждённое слово «upper bound» в latency artifact.

Round 2: все три находки `FIXED`, новых нет, verdict `APPROVED`. Review состоялся по
критерию артефакта: приведённая им строка “An in-process/equivalent guard may be faster
or slower; neither direction was measured.” дословно присутствует в
`probes/hooks/hook-overhead.raw.txt`. Полный журнал:
`codex-review-research.md`.

## Affected files and risks for a future implementation phase

Этот task ничего не меняет. Возможные владельцы будущих решений:

- `app/backend_claude.py` / Claude settings or SDK hooks — name/payload enforcement;
- `app/backend_codex.py`, Grok/OpenCode backends — parity or explicit unsupported
  verdict;
- `app/manager.py`, `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/pipeline.py` —
  role ACL, model/lifecycle/state enforcement;
- `pipelines/default/pipeline.yaml` — declarative role capabilities, если выбран
  manifest owner;
- `pipelines/default/prompts/**`, `CLAUDE.md` — только после code decision: точная
  документация гарантии против рекомендации.

Риски: hook bypass через альтернативный tool/shell indirection; role ACL, который
отрежет обязательный report path; false-positive command parser; live settings/hot
reload window; cross-runtime divergence; security denial без parent notification.

## Sources and measurements

1. [Claude Code hooks reference](https://code.claude.com/docs/en/hooks) — primary
   vendor source: `PreToolUse`, input payload, exit-code blocking, decision precedence.
2. [Claude Agent SDK permissions](https://code.claude.com/docs/en/agent-sdk/permissions)
   — primary vendor source: permission resolution order and callback fallback.
3. `docs/tasks/228/probes/tools/findings.md` — direct tool/catalog runs and raw-file
   index (evidence tier 1).
4. `docs/tasks/228/probes/local/runtime-probes.md` — real-backend callback and local
   guard falsifiers (tier 1).
5. `docs/tasks/228/probes/hooks/pretooluse-run.raw.txt` — blocking hook result and
   missing marker (tier 1).
6. `docs/tasks/228/probes/hooks/hook-overhead.raw.txt` — 48 hook intervals and A/B
   caveat (tier 1).
7. `docs/tasks/228/probes/inventory/findings.md` — 13 source families, 35 focused
   tests, isolated state/path/model/kill probes (tier 1).
8. `docs/tasks/228/enforcement-matrix.md` — 48-row navigation/backlog ledger; не
   статистический census правил.
9. Task #198 research — direct `token_budget` violation (8,095/1,000); referenced by
   `CLAUDE.md:192-193`.
10. Task #227 — forbidden-model enforcement owner; this audit references rather than
    duplicating the fix.
