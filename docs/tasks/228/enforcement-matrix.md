# #228 — матрица ограничений по обязательному seam

Дата среза: 2026-08-12. Строка таблицы — **аудиторский bundle**, то есть один
практический backlog/decision owner. Это навигационная группировка, не статистическая
единица: N5 объединяет пять одинаково принуждаемых имён tool, а A3 — десятки разных
process checks. Поэтому 48 строк нельзя читать как «в системе ровно 48 правил», а
отношение групп — как точную долю правил. Повторы между ролью, модулем и `CLAUDE.md`
схлопнуты; связанные ограничения с одним будущим owner тоже объединены.

Broad lexical scan нашёл 420 строк-кандидатов в 20 prompt-файлах, `CLAUDE.md` и
`pipeline.yaml`; это coverage-check, не denominator. Полный source→bundle ledger для
420 строк не составлялся, поэтому ниже публикуется число конкретных backlog bundles,
а не процент от «всех правил».

Ступени:

1. **NAME** — запрет самого tool по точному имени; должен жить в каталоге
   (`disallowedTools` / role-specific MCP `enabled_tools`).
2. **PAYLOAD** — решение зависит от аргументов tool; для Claude обязательная
   врезка — `PreToolUse`. `can_use_tool` не считается guard.
3. **RUNTIME** — решение зависит от состояния, истории, роли, авторизации или
   последовательности; нужен код Orchestra/ОС либо честная метка «рекомендация».

## 1. Ограничения по имени tool — 6

| ID | Ограничение и источник | Нужно | Сейчас | Что физически происходит при нарушении | Приговор |
|---|---|---|---|---|---|
| N1 | Нативная делегация `Agent`/`Task` запрещена; `base.md:39-40`, `backend_claude.py:49-82` | NAME | **Частично hard:** у orchestrator `Task` удалён; у worker `Task` есть | Worker может запустить нативного subagent вне worktree/session tracking; orchestrator не видит tool | Либо удалить `Task` у всех ролей, либо сузить текст; текущий универсальный запрет ложен |
| N2 | Не использовать built-in `SendMessage`; `base.md:41` | NAME | **Text-only:** `SendMessage` был в обоих измеренных Claude-каталогах | Вызов доступен и обходит Orchestra inbox/ownership | Добавить exact deny всем managed Claude-ролям; эквивалент для других runtimes |
| N3 | `AskUserQuestion` запрещён; `base.md:42`, `backend_claude.py:49-70` | NAME | **Fallback:** live callback вернул loud deny, но tool не удалён | В измеренном вызове side effect остановлен и агент получил tool error; гарантия зависит от попадания в permission fallback | Перенести в exact deny; callback-успех не заменяет catalog enforcement |
| N4 | `Monitor` запрещён; `base.md:42`, `backend_claude.py:49-70` | NAME | **Fallback:** ветка callback возвращает deny, catalog содержит `Monitor` | Прямой вызов callback отклонён; обязательность вызова callback не доказана | Exact deny; не держать name-инвариант в условном callback |
| N5 | `ScheduleWakeup`, `CronCreate/Delete/List`, `Workflow` запрещены; `base.md:29-43`, `backend_claude.py:56-82` | NAME | **Hard Claude:** удалены у всех ролей | Tool отсутствует; попытка не даёт permission denial, модель видит отсутствие | Оставить; это рабочий образец ступени 1 |
| N6 | Worker не должен иметь orchestrator-only MCP (`spawn_worker`, `kill_worker`, `get_worker_logs`, `list_orchestrators`); `roles/worker.md:9-10`, `base.md:21-25` | NAME/role | **Text-only:** 36/36 full MCP tools одинаковы у worker/orchestrator | Worker видит и вызывает tool; измеренный mocked `kill_worker(force=true)` дошёл до DELETE | Role-specific catalog ACL. Exact MCP deny технически доказан; общего runtime role ACL сейчас нет |

## 2. Ограничения по аргументам tool — 9 (backlog hooks)

| ID | Ограничение и источник | Нужно | Сейчас | Что физически происходит при нарушении | Приговор |
|---|---|---|---|---|---|
| P1 | `Bash.run_in_background=true` запрещён; `base.md:43`, `backend_claude.py:66-69` | PAYLOAD | **Не enforced:** deny лежит в `can_use_tool`; production `PreToolUse` = 0 | Реальный backend выполнил background `printf`, `is_error=false`; callback вызван 0 раз | Перенести в `PreToolUse`. Снимать текст нельзя: detached process теряется на конце turn |
| P2 | Не запускать запрещённые/деструктивные shell-команды; injected host safety + `CLAUDE.md:61-63,231` | PAYLOAD + OS | **Text-only:** callback вернул Allow для образцов `rm -rf`, `systemctl restart`, `git push` (ничего опасного не исполнялось) | Без послушания Bash/OS принимает команду | Hook может закрыть точные сигнатуры; полноценная защита от shell-обходов требует sandbox/OS policy |
| P3 | Restart/stop/start/deploy/pull/push только по явной авторизации; `CLAUDE.md:61-64`, `skills/vps-deploy.md:10-15,47-50`, `orchestration.md:230-232` | PAYLOAD + RUNTIME auth | **Text-only** | Команда исполняется с полномочиями процесса; отдельного authorization token/state нет | Статические команды — hook; наличие разрешения и окно — runtime capability, не prompt |
| P4 | Писать только в свой worktree/`owned_dirs`, не в main/secret paths; `git-workflow.md:5-15`, `roles/sub-orchestrator.md:8` | PAYLOAD + sandbox | **Частично:** overlap проверяется только при spawn; cwd admission не ограничивает последующие syscalls | Измеренная запись вне `claimed/` успешно создала файл | Hooks на Read/Edit/Write/path — первый слой; Bash-обход требует filesystem sandbox/runtime broker |
| P5 | Полученный acceptance test/oracle нельзя менять; `roles/worker.md:13-18`, `roles/full-cycle.md:117-137,195-200`, `CLAUDE.md:208-209` | PAYLOAD + RUNTIME state | **Text-only** | Edit/Write/Bash физически меняют oracle; платформа не знает RED commit/bytes | Hook на защищённые пути может закрыть прямую запись; неизменность относительно RED commit нужна в runtime |
| P6 | `kill_worker(force=true)` и target нельзя использовать вне lifecycle/ownership; `worker-lifecycle.md:4-17`, `mcp_stdio.py:1091-1106` | PAYLOAD + RUNTIME state | **Частично:** non-force guards hard; `force=true` их обходит | Измеренные тесты: force архивирует при live child; worker-role tool дошёл до force DELETE | Для workers exact deny N6; для orchestrators hook может запрещать force, но lifecycle/owner gate должен быть server-side |
| P7 | Worker/sub-orchestrator сообщает только своему parent и не пишет пользователю/чужим контурам; `roles/sub-orchestrator.md:7-9`, `report-format.md:3-27`, `orchestration.md:250-253` | PAYLOAD + RUNTIME identity | **Text-only/partial warning** | `send_message(to=...)` исполняется; cross-owner success даёт лишь post-send warning; `send_file` доступен | Target/role check в MCP/server; hook годится как дополнительный payload deny, не источник parent identity |
| P8 | Не протаскивать секреты в argv/raw artifacts и не читать/писать protected dotfiles; `CLAUDE.md:92,288`, injected host safety | PAYLOAD + data-flow | **Частично:** session cwd deny; backend argv на измеренном commit содержал token; content/path guard нет | Секрет может попасть в process list, artifact или tool input; cwd 403 не мешает чтению абсолютного пути после старта | Hooks на прямые path/content формы полезны, но основной фикс — transport/redaction/runtime; #224 уже владеет argv-проблемой |
| P9 | Не poll/sleep-loop, не класть большие данные в tmpfs, тяжёлые прогоны ограничивать; `roles/worker.md:11`, `research-method.md:75-87`, `CLAUDE.md:293-299` | PAYLOAD + resource supervisor | **Text-only** | Bash запускает loop/heavy command; нет per-tool memory/time policy Orchestra | Простые паттерны — hook; лимиты CPU/RAM/time — supervisor/cgroup, а методика остаётся рекомендацией |

## 3A. Ограничения состояния/процесса, где запрещённое действие реально возможно — 18

| ID | Ограничение и источник | Сейчас | Физический исход нарушения | Приговор |
|---|---|---|---|---|
| R1 | Known-role `can_spawn`; `pipeline.yaml:35-100`, `pipeline.py:612-658` | **Hard для известных ролей** | `worker -> worker` получает ValueError/409 до worktree; root exempt | Оставить кодом; NAME/PAYLOAD недостаточны |
| R2 | Unknown-role policy; `pipeline.yaml:3`, `pipeline.py:612-658` | **Fail-open в validator**, manager случайно падает раньше на prompt resolution | Отдельный validator принимает `worker -> ghost`; complete path не создаёт role | Не считать раннюю ошибку policy guard; если неизвестная роль запрещена — fail-closed код |
| R3 | Модель: Luna→Sol→Opus, Terra/Fable запрещены; `model-routing.md:2-16`, `CLAUDE.md:82-92` | **Text-only + registry syntax** | Terra request и mocked manager session приняты без policy warning | Runtime router/admission; блок модели ведёт #227 |
| R4 | Weekly worker quota; `quota_gate.py`, `manager.py:650-653`, `session.py:882-927` | **Hard в заявленной области** | Новый worker turn при 95% получает QuotaGateError/429 до publish; steering/orchestrator exempt | Оставить кодом; документировать точную область, не называть global budget |
| R5 | `token_budget`/goal budget должен остановить расход; goal prompt/`CLAUDE.md:192-193`, evidence #198 | **Prompt-only** | Измерено #198: 8,095 tokens при budget 1,000 и 12/12 файлов | Runtime supervisor; не дублировать status field как guard |
| R6 | Full-cycle gates Research→Plan→Implement; `roles/full-cycle.md:2-8,12-46,48-111,184-200` | **Text-only** | Agent может писать implementation до approval; server phase state отсутствует | Runtime state machine, если это запрет; иначе переименовать в workflow recommendation |
| R7 | RED/oracle existence, ticket dependency order и AC; `roles/full-cycle.md:49-109,114-137` | **Text-only** | Можно начать с green/missing test, поменять contract, нарушить blocked-by | Runtime/task artifacts + immutable commit check; prompt остаётся объяснением |
| R8 | Executor route, one attempt, Luna→Sol→self escalation; `roles/full-cycle.md:123-137`, `model-routing.md:10-13` | **Text-only** | Тот же executor можно ретраить/коучить; model policy нарушается без отказа | Runtime attempt ledger/router; #227 владеет запрещёнными моделями |
| R9 | Codex review required/round ceiling/verdict authenticity; `codex-debate.md:24-33,67-110,133-159`, `full-cycle.md:95-108,150-157` | **Text-only + tool job mechanics** | Можно пропустить review, запустить лишний round или объявить approval без verdict | Runtime review session counter + artifact/verdict parser; qualitative disagreement остаётся LLM |
| R10 | Semantic lifecycle (one-shot/persistent, gate, DONE, idle, clean); `worker-lifecycle.md:4-17`, `CLAUDE.md:143` | **Partly hard** | Non-force protects running/dirty/children; force bypasses, description/DONE/gate не читаются | Server lifecycle state + caller authorization; prompt не может защищать от permanent archive |
| R11 | Role-specific MCP authority/read-only; `manager.py:393-415`, `mcp_stdio.py:51-66,267-289` | **Capability exists, unused:** all managed roles `full` | Worker/orchestrator catalogs равны 36; mutating tools доступны | Declarative per-role catalog/ACL; не заменять одним read-only для всех |
| R12 | Safe cwd roots; `routes/sessions.py:175-180`, `routes/system.py:160-211` | **Hard admission only** | `/home/kesha/.ssh` получает 403; после safe cwd абсолютные обращения не ограничены | Честно назвать cwd admission; filesystem guarantee требует sandbox |
| R13 | Runtime sandbox/approval across Claude/Codex/OpenCode/Grok; backend launch configs | **Explicitly permissive** | Codex `danger-full-access`/`never`; OpenCode allow; Grok always approve; Claude allow fallback | Capability sandbox/OS boundary, не prompt. Ограничения по tool отдельно N/P |
| R14 | Native delegation disabled across runtimes; `backend_codex.py:393-483`, Claude config | **Mixed** | Codex command содержит `features.multi_agent=false`; Claude worker видит Task; Grok/OpenCode policy иной | Один cross-runtime contract, проверяемый свежим init catalog/launch probe |
| R15 | Task/payment transitions only after verified merge; `task-management.md:14-20`, `orchestration.md:77-87` | **Mostly procedure** | Caller может отправить разрешённое schema-status в неверной последовательности | Server transition/actor checks, если неверный status финансово/операционно запрещён |
| R16 | External mutation requires current-user authorization; `CLAUDE.md:61-64`, `vps-deploy.md:10-15` | **Text-only** | Bash/MCP не несут signed/current-turn authorization; полномочия ОС есть | Runtime capability grant with expiry/scope; hook без auth state недостаточен |
| R17 | Parent должен узнать о result/denial; `base.md:4-17`, report-format | **Result partial, denial gap** | Worker auto-report существует; measured `can_use_tool` denial persisted, `_did_report=false`, parent не notified | Server event delivery for denied/high-risk actions; agent narration не канал аудита |
| R18 | Provider/credential policy (subscription only, no API keys); `CLAUDE.md:82-92` | **Text/config convention** | Модель/launcher могут принять зарегистрированный runtime/env без policy verdict | Runtime allowlist and secret transport; текст нужен только для объяснения |

## 3B. Процесс и качество — 15 честных рекомендаций, не «блокировки»

Для этих правил LLM действительно нужна: сервер не может доказать смысл источника,
качество гипотезы, уместность текста или полноту рассуждения. Они могут оставаться в
prompt, но интерфейс и документация не должны утверждать, что платформа их
**блокирует**. Автоматизировать можно delivery/telemetry, не semantic verdict.

| ID | Группа и источники | Сейчас и физический исход | Честная формулировка |
|---|---|---|---|
| A1 | Research framing, hypotheses, counter-evidence, evidence tiers; `research-method.md:8-132`, `full-cycle.md:14-46` | Text; можно написать слабый/ложный research без runtime refusal | «Методика/критерий ревью», не запрет |
| A2 | Mandatory memory search/pre-work order; `memory-search.md:2-18`, `roles/worker.md:24-35` | Text; пропуск не создаёт standard policy event | Автоматически доставлять контекст/логировать вызов; качество запроса остаётся LLM |
| A3 | Десятки cheap-before-work checks из `CLAUDE.md:147-169` | Text; агент может начать с неверной предпосылки | Считать cultural playbook; выносить повторяемые проверки в команды |
| A4 | Test/mutation methodology; `CLAUDE.md:207-209,267-277`, `roles/worker.md:60-70` | Text; тест может быть ложно-зелёным | Линтеры/CI как evidence, но выбор мутации — LLM |
| A5 | Minimal/simple code and no speculative refactor; `roles/worker.md:36-59`, `full-cycle.md:206-228` | Text; code review видит постфактум | Quality rubric, не platform guarantee |
| A6 | Same language, brevity, no user name, no acknowledgements; `base.md:47-68`, `roles/orchestrator.md:11-26` | Text; сообщение физически отправляется | Communication policy/review |
| A7 | Context economy, grep before read, no noisy polling; `base.md:47-55` | Text; tool calls исполняются | Optimization recommendation; telemetry может измерять |
| A8 | Классификация и полнота bug report; `CLAUDE.md:129-135`, `orchestration.md:245-249` | `report_bug` schema проверяет поля, но выбор «platform vs project» делает LLM | Semantic classifier + schema, не blanket deny |
| A9 | Self-improvement, trigger test, personal memory; `self-improvement.md:2-89` | Text; можно не записать/не triage | Workflow recommendation; delivery check возможен |
| A10 | Branch/commit/report conventions без safety-команд; `git-workflow.md:4-31`, `report-format.md:2-27` | Git допускает иной message/order; merge имеет отдельные guards | Convention/CI; опасные команды вынесены в P3/P4 |
| A11 | Task decomposition, delegation, parallelism, worker reuse; `orchestration.md:7-44,136-181,208-259`, `full-cycle.md:230-235` | Text; выбор может быть дорогим/слабым | Router может рекомендовать/логировать; смысл задачи остаётся LLM |
| A12 | Выбор типа background job/timer/cron/run/command; `background-jobs.md:2-23` | Tool schema исполняет выбранный тип, но не проверяет уместность | Recommendation; запрет detached Bash отдельно P1 |
| A13 | Web/source/image/HTML/Grill skill selection and presentation constraints; skill prompts | Text; артефакт может быть хуже или дороже, но tool не обязан отказать | Skill rubric, не authorization boundary |
| A14 | Fail loud/error interpretation/verify artifact not narrative; `CLAUDE.md:114-125,171-209,249-263` | Частные handlers hard; общий смысл text | Набор проверок/review; каждую повторяемую ошибку автоматизировать отдельно |
| A15 | Session notes, handoff, hot-reload/deploy operational knowledge; `orchestration.md:215-225`, `CLAUDE.md:258-286,300-319` | Text; нарушение видно в потерянном контексте/неверной процедуре | Runbook/recommendation; destructive authorization отдельно R16/P3 |

## Количественный итог по audit bundles

| Класс | Backlog bundles | Уже полностью enforced |
|---|---:|---:|
| NAME | 6 | 1 (N5); N1 частично |
| PAYLOAD | 9 | 0; production `PreToolUse` не используется |
| RUNTIME, unsafe if forgotten | 18 | 3 узких guard (R1 known roles, R4 quota, R12 cwd admission); остальные partial/text |
| Semantic/culture | 15 | Не применимо; это рекомендации |
| **Всего NAME+PAYLOAD** | **15 конкретных bundles** | Не точная доля правил |

Главный вывод группировки: «перенести всё в hooks» неверно. Найдены 15 конкретных
NAME/PAYLOAD bundles и 33 non-tool bundles; последние дополнительно схлопывают целые
наборы process checks (особенно A3/A4/A13), поэтому точный процент без построчного
ledger был бы ложной точностью. Девять payload-кандидатов — готовый backlog, но у
восьми кроме `run_in_background` есть обход через другой tool/сырой shell, поэтому
hook является слоем, а не полной capability security. Qualitative verdict
«tool-layer rules — меньшинство» остаётся **LIKELY**, не количественно доказанным.
