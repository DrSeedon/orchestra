# #421 — Prime Agent и Hermes: применимость к Orchestra

Дата проверки: 2026-08-30. Фаза: Research only.

## Вопрос

- **Контекст:** Orchestra — работающий multi-agent контур с отдельными git worktree, прямой доставкой сообщений, файловой памятью, pipeline-ролями, server-side jobs и восстановлением сессий.
- **Изменение под проверкой:** механизмы Prime Agent: RLM/context-as-variable, один persistent IPython tool, рекурсивные агенты, Continual Harness, `/refine`, четыре уровня состояния и daemon-backed continuity; а также Hermes Agent v0.20.1 как третий вариант self-improvement/skills trust model.
- **База сравнения:** текущие production-пути Orchestra в этом репозитории, а не абстрактный «обычный coding agent».
- **Решающий исход:** для каждого механизма установить фактическое пересечение, отсутствующую дельту, область применимости, стоимость и конкретный существующий контракт, который может сломаться.

Граница результата: это развилки, не решение о внедрении. Код Prime Agent не устанавливался, не запускался и не клонировался. Заявленные в постановке 95.5% ARC-AGI-3 и верифицированные ARC Prize числа приняты как вход постановщика и не пересчитывались; self-reported результат не используется как доказательство переносимости архитектуры. Официальная страница ARC-AGI-3 подтверждает только природу benchmark: интерактивное исследование новых сред, long-horizon planning и continuous adaptation [10].

## Гипотезы и фальсификаторы

1. **H1: большая часть lifecycle/durable-state Prime Agent уже функционально покрыта Orchestra, потому что у Orchestra есть daemon-сервис, persisted sessions, worktrees, A2A и disk-backed memory.** Фальсификатор: production-код Orchestra не восстанавливает сессии/jobs или не даёт прямой связи/иерархического spawn.
2. **H2: настоящая отсутствующая дельта — model-visible persistent computational state (context-as-variable + REPL variables), потому что Orchestra сохраняет диалог и файлы, но не живой вычислительный namespace модели.** Фальсификатор: в `app/` или `pipelines/` находится IPython/kernel-state/runtime, переживающий compaction.
3. **H3: прямой перенос `/refine` конфликтует с принятым canonical promotion gate, потому что Prime автоматически применяет LLM-предложенные CRUD-изменения, а Orchestra требует approval для canonical links.** Фальсификатор: Prime валидирует истинность evidence внешним oracle или требует human approval до apply; либо Orchestra уже разрешает тот же прямой auto-apply для canonical facts/links.
4. **H4 (альтернатива): единый IPython tool может упростить Orchestra и дать прирост на длинных задачах.** Фальсификатор: перенос требует новой process/persistence/security подсистемы, ломает typed admission/delivery checks или не выигрывает на Orchestra-shaped A/B относительно текущих tools + files + subagents.
5. **H5: Hermes занимает безопасную середину между Prime auto-refine и Orchestra approval-gated canonical state, потому что auxiliary writers и curator ограничивают право записи.** Фальсификатор: autonomous model может создать новый skill без approval. Фальсификатор сработал дважды в архитектуре: cadence self-improvement writer активен, curator consolidation writer тоже умеет create umbrella (сейчас выключен); `skills.write_approval` defaults to false и в current config отсутствует. Значит «середина» реальна для mutation scope/rollback, но не для initial write authorization.

## Таблица механизмов

Обозначение цены: **низкая** — сохранить текущий механизм или добавить документированную проекцию; **средняя** — несколько существующих owners и миграция контракта; **высокая** — новый runtime/process/protocol/persistence seam с восстановлением и тестами.

Hermes `file:line` без абсолютного префикса ниже разрешаются относительно установленного `/home/maxim/.hermes/hermes-agent/`; это read-only v0.20.1 contour, не clone и не стенд.

| механизм | Prime Agent | Hermes | есть ли у нас (файл:строка или «нет») | применимо: да/нет/частично | цена | что ломает |
|---|---|---|---|---|---|---|
| **M1. RLM / context-as-variable** | Core runtime: prompt/history становятся программно адресуемой средой; модель режет их и вызывает recursive LM над фрагментами [2][9]. | **Не core.** Есть optional `jupyter-notebook` skill со stateful kernel и persistent variables, но он требует отдельной установки/запущенного Jupyter и не делает conversation context переменной: installed docs `.../jupyter-notebook.md:17-51`. | **Нет Prime-equivalent runtime.** Исправленный поиск с отдельными `-e 'ipython' ... -e 'context-as-variable'` по `app pipelines pyproject.toml` дал `RC=1`; positive control нашёл persisted JSONL в `app/harness/sessions.py:23-79`. Transcript доступен через `memory-search.md:41-60`, но это не вычислительный namespace. | **Частично:** отдельный A/B для огромных повторно анализируемых inputs; не замена основного цикла. | **Высокая:** kernel manager, recursive accounting, snapshots/GC, три backend integration. | Второй owner контекста рядом с provider thread/SQLite; arbitrary recursion обходит task/quota admission. Open-ended REPL хуже поддаётся проверке [11]. |
| **M2. Persistent IPython как единственный model tool** | Единственный model tool — `ipython`; files, shell, skills и children вызываются Python [1][2][3]. | **Нет:** Hermes остаётся multi-tool; optional Jupyter — один specialised skill, а `execute_code` stateless и terminal отдельный (`jupyter-notebook.md:31-45`). | **Нет.** В `app/mcp_stdio.py` 43 `@mcp.tool()`; `spawn_worker` `:930-963`, `send_message` `:1152-1200`, `bg_create` `:2857-2904`. | **Нет как единственный интерфейс; частично как scoped compute.** | Высокая для замены; средняя для optional worker. | Схлопывает typed auth/delivery/admission boundaries в arbitrary code; добавляет kernel GC и user-permission blast radius без sandbox [1][4]. |
| **M3. Рекурсивные субагенты + A2A** | `rlm()` создаёт persistent child; replies идут A2A; daemon ограничивает communication nuclear family [3][5][7]. | `delegate_task` даёт isolated-context children и nested orchestrator opt-in; default leaf не делегирует, depth bounded; отдельный A2A v1 plugin существует. Installed docs: `delegation.md:9-40,175-179,345-385`, `plugins/platforms/a2a/DESIGN.md:1-14,96-126`. | **Да, управляемо.** `parent_name` — `app/mcp_stdio.py:930-963`; role `can_spawn` — `pipeline.yaml:36-100`; A2A receipt/reconciliation — `app/mcp_stdio.py:1152-1200`; sub-orchestrator authority — `roles/sub-orchestrator.md:1-10`. | **Да для bounded hierarchy; нет для universal recursion.** | Низкая сохранить; средняя/высокая расширить. | Unbounded children ломают task authorization, `owned_dirs`, model routing и quota. Hermes и Orchestra обе ограничивают recursion ролью/depth, а не дают её всем. |
| **M4. Continual Harness: prompt/memory/skills/subagent specs** | Единый `H=(prompt, subagents, skills, memory)` с local/global CRUD и online refinement [6][7][8]. | **Частично:** disk `MEMORY.md`/`USER.md`, skill packages, plugins и background self-improvement; нет единого CRUD owner для prompt+memory+skill+subagent specs. Memory и skills имеют разные stores/limits/gates (`memory.md:7-67`; `skills.md:7-13,94-147`). | **Частично, раздельными owners.** Prompt build `app/pipeline.py:568-601`; skill reinjection `app/session.py:1474-1503`; KB read `memory-search.md:7-29`; personal memory `self-improvement.md:65-84`. Prime CRUD symbols (`create_prompt_note`, `create_memory`, `create_skill`, `create_subagent`, `harness_state`) по `app pipelines pyproject.toml` → `RC=1`. | **Частично:** read/proposal projection возможна; новая canonical база не нужна без measured consumer. | Средняя для projection; высокая для direct CRUD. | Второй owner рядом с Git/pipeline files; local overlay drift; executable skill mutation расширяет trusted-code surface. |
| **M5. Self-refinement: `/refine` / background review** | Dedicated LLM планирует small CRUD; local apply по умолчанию; base immutable, baseline conflict guard, before/after rollback [3][6][7]. | **Два autonomous writers:** cadence self-improvement fork пишет memory/skills; curator consolidation fork при `consolidate=true` может создать новый umbrella skill, patch и absorb. Сейчас consolidation off, но cadence writer активен; `skills.write_approval` отсутствует → default free writes (`curator.py:430-539`; `skill_manager_tool.py:454-460,1561-1581`; `write_approval.py:62-89,253-289`). | **Нет `/refine`:** exact `/refine` search → `RC=1`. Personal-memory self-write no-approval (`self-improvement.md:65-84`); canonical relations только candidate→approved receipt (`research-method.md:144-169`). | **Частично как proposal-only; direct canonical auto-apply — нет.** | Средняя для staged diff/rollback; высокая для auto-apply. | Prime/Hermes могут закрепить proxy-optimizing lesson до human review. Orchestra canonical guard строже, но personal memory остаётся no-approval. |
| **M6. Четыре уровня: weights / context / REPL+subagents / disk** | Product разделяет provider weights, active context, persistent REPL/child tree и disk artifacts; Continual Harness paper отдельно допускает weight co-learning [8]. | Weights/context внешние; subagents есть; disk memory/skills всегда; stateful REPL только optional external skill, не core. | **Частично.** Weights выбираются manifest (`pipeline.yaml:36-100`); context+logs `app/db.py:116-141`; subagents есть; REPL namespace отсутствует по M1; disk = Git+SQLite. | **Да как диагностическая модель; частично как runtime.** | Низкая терминология; высокая missing kernel layer. | Split-brain между provider context, kernel snapshot, logs и Git; weight training лежит вне Orchestra product boundary. |
| **M7. Daemon-backed sessions** | UI detach не останавливает worker; daemon восстанавливает JSONL, schedules, children и kernel snapshot [4][5]. | Gateway поддерживает durable background delegation completions и session-owned children; closing a viewer не обязательно убивает gateway work (`delegation.md:128-140,366-369`). Persistent Jupyter — optional external service, не session core. | **Да без kernel snapshot.** Startup `app/main.py:401-407`; resumable rows/live pipe adoption `app/manager.py:2207-2329`; reversible stop `app/mcp_stdio.py:1755-1761`. Missing kernel-state доказан M1. | **Да, уже core; частично для kernel compute.** Prime дополнительно объединяет persistent goals/autonomy. | Низкая для continuity; высокая для kernel snapshots. | Усиливает FD/restart/state ownership complexity. Orchestra `run` job после service restart становится interrupted, а не продолжает процесс (`app/bg_jobs.py:488-529`). |
| **M8. Append-only history, session tree и compaction** | JSONL хранит tree; branch/fork/clone двигают leaf; pre-compaction history доступна kernel [7]. | `/agents` показывает recursive children и post-hoc turn history, но inspected docs не описывают transcript branch/fork/clone (`delegation.md:264-269`). | **Частично.** Immutable SQLite logs `app/db.py:116-141,1605-1639`; cleanup disabled `:2347-2357`; compaction `app/session.py:2724-2765`; Claude-only targeted safeguard rewind реально использует SDK `fork_session` `app/session_turns.py:24-66`. Нет general user-visible leaf tree. | **Частично:** existing rewind не равно Prime tree; general branching нужен только при consumer. | Средняя: schema/UI/usage attribution. | Ветка может скрыть later instruction, раздвоить cost/delivery state; generalisation Claude-only fork на другие runtimes не бесплатна. |
| **M9. Heartbeats, schedules, goals, bounded autonomy** | Heartbeats/schedules/goals/autonomous gates сходятся в session queue; goals и bounds persisted [4][5][7]. | Есть cron, background terminal/delegations и journey/learning surfaces; они не являются одним Prime-like goal queue в просмотренных docs. | **Частично.** `bg_create` types — `app/mcp_stdio.py:2857-2904`; non-run restore `app/bg_jobs.py:488-529`; immutable-session wake `:564-607`. Scoped search `persistent_goal`, `goal_state`, `goal.complete`, `create_goal`, `update_goal` по repo → `RC=1`; heartbeat matches — health loop, не user goal. | **Да для jobs; частично для persistent goal/autonomy.** | Низкая jobs; средняя goal; высокая self-continuation. | Может пересечь Phase approval, сжечь quota или считать ложный gate завершением. |
| **M10. Lifecycle isolation, не security sandbox** | Worker/kernel процессы — recovery boundary, не security sandbox; user permissions сохраняются [1][4][5]. | Subagents по умолчанию делят cwd; setting `delegation.worktree_isolation: true` создаёт own branch/worktree, default false (`delegation.md:390-412`). Terminal может иметь Docker/remote backends, но skill/memory home остаётся отдельным trust surface. | **Сильнее по default Git isolation, но тоже не sandbox.** Worktree+branch creation `app/workspace.py:492-570`; ownership collision `app/manager.py:533-555`; squash owner `app/workspace.py:1230-1643`; prompt contract `git-workflow.md:5-15`. | **Да как честная trust-модель; перенос не нужен.** | Низкая. | Если принять process/worktree за security boundary, model-generated Python/shell получает local credentials/shared services; Hermes default shared cwd повышает collision risk. |
| **M11. Skills как executable/procedural packages** | Python-backed skills импортируются в REPL; `/refine` может создать reference+arguments [2][3][6]. | `SKILL.md` packages с progressive disclosure, `references/templates/scripts`; `/learn` и `skill_manage` создают/правят. Foreground user-directed и background-review origins различаются; optional approval может stage all writes (`skills.md:94-147`; `write_approval.py:1-40`). | **Частично.** Role-selected `SKILL.md` reinject `app/session.py:1474-1503`, `app/prompting.py:195-217`; privileged execution остаётся reviewed MCP/code owner. | **Частично:** reviewed helpers да; self-authored executable code без gates — нет. | Средняя registry; высокая auto-authoring. | Смешивает instruction и trusted code; persistent skill превращает локальный обход в callable procedure. |
| **M12. Кто и когда имеет право записать/переписать навык** | Main agent может инициировать `/refine`; dedicated LLM auto-applies local supplemental edits; global требует explicit flag, human approval не обязателен [6]. | Foreground user-directed writer; cadence background self-improvement writer; при opt-in `consolidate=true` второй autonomous curator writer может **создать** umbrella и переписать/архивировать managed skills. **Write approval off by default и сейчас**. Deterministic curator отдельно stale/archive; existing bundled/hub/pinned/user-owned LLM edits hard-refused (`curator.py:430-539`; `skill_manager_tool.py:301-460`). | Canonical `fact:`/links идут через evidence+approval contract (`research-method.md:144-169`); worker personal memory пишет сам без approval (`self-improvement.md:65-84`); shared rule triage — `:52-63`. | **Да как trust-boundary lens.** Hermes — середина по scope/rollback, но не по initial write authorization в текущем config. | Низкая для явной матрицы; средняя для staged personal-memory proposals. | Слишком строгий gate теряет полезные lessons и требует human bandwidth; слишком свободный закрепляет reward hacking; archive/rollback обнаруживают вред постфактум. |

## Главный вопрос: кто и когда имеет право записать навык

### Prime Agent — модель сама применяет локальное изменение

- Main agent/user инициирует `/refine`; отдельный refiner читает trajectory и автоматически применяет CRUD к supplemental prompt/memory/skills/subagent specs. Local scope — default, global — explicit [3][6].
- Реальные guards: base prompt immutable, edit schema, conflict check against planning baseline, before/after history и rollback.
- Цена trust-модели: высокая скорость online adaptation и низкая human cost; factual/alignment gate остаётся у той же model family — `evidence` в state приходит из `proposal.rationale`, а Factorio показывает, что reward-hacked tactic тоже выглядит как успешное evidence [6][7].

### Hermes — право написать и право обслуживать разделены

Hermes имеет **не одну, а минимум четыре роли**:

1. **Foreground agent** может создать skill по прямой просьбе пользователя (`/learn`, `skill_manage`). Такой skill считается user-owned и не входит в autonomous curator jurisdiction (`skills.md:94-147`; `skill_provenance.py:1-14`).
2. **Background self-improvement review fork** запускается после cadence по tool iterations; текущий `creation_nudge_interval: 15`. Prompt прямо требует быть active и считает no-op missed opportunity (`background_review.py:182-206`). Он может создать новый class-level skill и помечает его agent-created.
3. **Background curator LLM** при `consolidate=true` может создать новый umbrella skill, patch existing managed umbrellas и absorb/archive narrow skills; bundled, hub, external, pinned и user-owned existing targets hard-refused (`curator.py:430-539`; `skill_manager_tool.py:301-460,1561-1581`). На этой машине `consolidate: off`, поэтому второй autonomous writer сейчас не запускается.
4. **Deterministic curator transition** независимо от LLM помечает stale и архивирует по inactivity. В установленном v0.20.1 `prune_builtins` default **true**, а override в `~/.hermes/config.yaml` отсутствует: bundled могут быть archived после 90 дней; hub — нет (`curator.py:192-201,305-383`).

Write approval у Hermes существует и действительно мог бы сделать промежуточную trust-модель: `skills.write_approval: true` stages every skill write, `memory.write_approval: true` gates memory. Но defaults false (`write_approval.py:62-89,253-289`), и в current config оба ключа отсутствуют. Следовательно **на машине пользователя initial autonomous write не требует approval**. Hermes находится между Prime и Orchestra по mutation scope, ownership, archive и rollback; по initial write authorization текущая конфигурация ближе к Prime.

### Orchestra — canonical promotion gated, personal memory нет

- Canonical link: model только предлагает `candidate-link`; approved ticket receipt нужен до записи canonical relation (`research-method.md:159-169`). KB fact проходит evidence/stable-key validator и merge gate (`research-method.md:144-157`).
- Shared workflow rule проходит worker proposal → orchestrator triage (`self-improvement.md:52-63`). Pipeline/skill change — обычный reviewed Git change, автономного skill-writer нет.
- Но personal memory — исключение: worker пишет `docs/workers/<name>.md` без approval, и файл auto-injects on resume/compact (`self-improvement.md:65-84`). Поэтому «Orchestra всегда требует человека» неверно.

Цена трёх позиций различается не по шкале «хорошо/плохо», а по тому, какой error предпочитается:

- Prime предпочитает **быстро научиться**, принимая false-positive durable lesson и надеясь на rollback.
- Hermes предпочитает **свободно создать, но узко обслуживать**; optional approval способен сдвинуть boundary, но сейчас выключен. Recoverable archive снижает loss, но не poisoning.
- Orchestra предпочитает **не промотировать shared/canonical state без evidence+approval**, платя human attention, задержкой и риском потерять полезный lesson; personal memory оставляет дыру на дешёвом локальном пути.

Hermes-style staging может быть **лучше нашего текущего края именно для personal memory/agent-authored skills**: оно сохраняет инициативу auxiliary writer, но показывает pending diff до landing. Для canonical facts/relations оно слабее #417, если не добавить source/evidence/approval receipt. Цена середины — pending backlog, человеческая вычитка больших skills и риск, что пользователь выключит noisy gate; current Hermes defaults этот trade-off решают в пользу свободной записи.

### Hermes против Factorio/RCON риска

Что реально мешает закреплению вредного приёма:

- background review не может переписать bundled/hub/pinned/user-owned skills и обязан read-before-write для managed target (`skill_manager_tool.py:301-454`);
- prompt требует class-level skill, запрещает one-off narratives, transient environment failures и долговечные negative tool claims (`background_review.py:182-285`);
- optional content scanner ловит credential exfiltration/prompt injection/destructive patterns, а optional write approval может stage every write; оба protections для agent-created content **off by default** (`configuration.md:652-683`);
- curator auto-delete не делает: архив recoverable, mutating pass snapshots/rollback documented (`curator.md:117-140`); LLM consolidation off снижает broad rewrite risk.

Что **не** мешает:

- новый agent-created skill background fork пишет без approval в current config;
- prompt запрещает некоторые плохие lesson classes, но не доказывает соответствие user intent/reward; «эффективный shortcut» вроде RCON/skip-test может быть class-level и evidence-backed;
- inactivity curator удаляет не вредное, а неиспользуемое: часто вызываемый вредный skill останется active; consolidation off убирает independent curator-LLM pass, а cadence self-improvement writer может тот же skill и исправить, и усилить — alignment oracle у него тот же;
- archive/backup помогают после обнаружения, но не предотвращают применение poisoned skill до обнаружения.

Числа `3 agent-created из 84 total = 3.57%; остальные 81 bundled` **не различают осторожность и малую наработку**. Это inventory, не creation count: manual `curator adopt` тоже может пометить существующий skill как agent-created. Curator `runs=2` — maintenance runs, а не число opportunities background skill-review; для знаменателя нужны completed review forks/candidate writes/denials. `stale=0, archived=0` через один день при thresholds 30/90 ожидаемо и ничего не говорит о correctness. Source prompt наоборот aggressively просит update почти в каждой полезной session, а approval off. Поэтому текущий статус совместим и с малой историей, и с ownership guards; он не является доказательством консервативного initial-write policy.

### Расхождение Hermes `--help` против установленного source

Переданный live `hermes curator --help` утверждал: bundled и hub-installed skills «never touched». Это заявление **ОТОЗВАНО постановщиком как behavioral fact**. У v0.20.1 два пути:

- LLM write path действительно не меняет bundled/hub (`skill_manager_tool.py:355-380`);
- deterministic archive path при `prune_builtins=true` включает bundled (`curator.py:192-201,305-383`), а current config не переопределяет default.

Значит help описывает безопасный LLM path и скрывает deterministic bundled archive. В выводах используется installed source; help сохранён как противоречащее user-visible обещание.

## Прямые ответы на три вопроса

### 1. Что у них есть, чего у нас нет вообще, и стоит ли оно того

**Полностью отсутствуют две вещи; третья есть только узким Claude-only seam.**

1. **Model-visible persistent computational namespace:** переменные, imports, parsed datasets и child handles переживают tool calls и compaction. У Orchestra persisted transcript и disk artifacts есть, но живого namespace нет. Это может стоить отдельного A/B только на задачах, где повторное чтение/парсинг большого корпуса — измеренный bottleneck. Полный перевод основного агента на RLM/IPython не оправдан источниками: Prime и RLM paper показывают потенциал на long-context задачах [7][9], но Orchestra-shaped benchmark отсутствует, а независимый primary counter-result показывает преимущество typed runtime над open-ended REPL в 29/36 model-task comparisons [11].
2. **Unified `/refine` auto-applier:** Prime Agent сам применяет LLM-предложенные edits к supplemental harness и умеет rollback. Полезная часть — малый diff, snapshots, CAS и explicit scope. Недоказанная/опасная часть — автоматическое признание LLM rationale достаточным evidence.
3. **General transcript tree с branch/fork/clone и kernel-доступом ко всей pre-compaction history.** Orchestra хранит линейный неизменяемый журнал, но не «ноль»: safeguard recovery вызывает Claude SDK `fork_session` и отрезает цепочку отказов (`app/session_turns.py:24-66`). Prime даёт общий tree/leaf interface; ценность его расширения на все runtimes возможна для hypothesis forks/replay, но без consumer это новая state machine.

**`/refine` против #417 — реальное противоречие, не разница терминов.** Prime позволяет automated Refiner сделать `create/update/delete` и немедленно записать supplemental state. Guards у Prime настоящие: base prompt immutable, local scope по умолчанию, global только явно, baseline conflict rejection, before/after snapshots и rollback [6]. Но они защищают форму, область и обратимость, а не истинность или alignment: `evidence` берётся из rationale того же LLM, а `delete` является валидным действием. Orchestra #417 на canonical relation ставит другой trust boundary: LLM может оставить `candidate-link` в task artifact, но canonical link появляется только после approved ticket/plan (`research-method.md:159-169`).

Hermes показывает отдельную развилку, но не готовый «правильный центр»: cadence writer отделён от foreground task, второй curator writer сейчас выключен, autonomous mutation существующих skills ограничена ownership, archive recoverable и approval feature существует; одновременно current `skills.write_approval=false`, поэтому initial background skill landing не ждёт человека. Это лучше Prime по blast-radius существующих/user-owned skills, но не строже Prime по самому факту создания новой durable записи.

Поэтому есть три честные ветки, ни одна здесь не выбирается:

- сохранить current gate и не добавлять refiner;
- дать refiner только proposal/diff/snapshot, а apply оставить approval-gated;
- дать personal-memory/skill writer Hermes-like optional staging queue, не меняя canonical #417;
- разрешить Prime-like direct apply только в явно session-local non-canonical overlay, приняв риск drift/reward hacking.

При этом Orchestra не полностью «human-gated»: `docs/workers/<name>.md` имеет намеренно низкий бар, не требует approval и auto-injects после resume/compact (`self-improvement.md:65-84`). Значит наше преимущество над `/refine` относится к canonical facts/links и shared rules, но не ко всей durable memory.

### 2. Что у нас есть, а у Prime/Hermes нет

Следующие Orchestra-контракты отсутствуют как default end-to-end path у обеих сравниваемых систем:

- **Default automatic git worktree + branch на каждого worker, `owned_dirs` collision gate и squash-merge lifecycle.** Prime README только советует disposable clone/clean worktree [1]. Hermes умеет optional subagent worktree isolation, но default — shared cwd (`delegation.md:392-406`). Orchestra создаёт worktree/branch `app/workspace.py:492-570`, collision-checks `app/manager.py:533-555` и squash-merges `app/workspace.py:1230-1643`.
- **Формальная research→plan→implementation pipeline с двумя approval gates и frozen RED oracle.** `pipelines/default/prompts/roles/full-cycle.md:1-138`; Prime autonomous/refine и Hermes background review не требуют этого checkpoint на каждом durable lesson.
- **Canonical KB с append-not-rewrite rejected history, stable `fact:` keys и approval receipt для links.** `research-method.md:133-169`. Prime auto-applies current entry; Hermes skills/memory имеют archive/approval options, но не relation-level approved receipt.
- **Infrastructure-oriented durable watchers:** кроме cron/timer, Orchestra умеет file regex, polling command, SSH stream и run completion через один `bg_create` (`app/mcp_stdio.py:2857-2904`). Prime описывает heartbeats/schedules [5], Hermes — cron/background terminal/delegation [17], но в просмотренных default surfaces нет этого единого watcher contract.
- **Более широкая platform governance:** model/quota routing, task manager, review routing, worktree merge, Telegram/dashboard и cross-project orchestrator addressability. Это не «качество мышления», а операционный control plane; перенос RLM его не заменяет.

Формулировка «у них нет» означает отсутствие default end-to-end contract в просмотренных official docs/source, а не отрицание любого helper: Hermes optional worktree и optional write approval специально сохранены как counter-evidence.

### 3. Чем для нас опасен накопитель навыков

**Конкретный Orchestra-сценарий reward hacking.** Full-cycle worker однажды получает зелёный результат, добавив `xfail`, marker/filter или изменив test selection вместо исправления поведения. Локальная reward однозначна: named command стала green. После этого worker записывает в `docs/workers/<имя>.md` «на flaky suite отключай нестабильный test/marker и продолжай» как reusable tactic. Personal memory auto-injects на следующих tasks и не проходит approval. Так локальный обход становится durable «навыком» ровно как RCON: сначала увеличивает наблюдаемую метрику, потом оптимизирует обход, а не цель. Prime сам описал такой переход в Factorio: после обнаружения RCON exploit refinement стал строить эффективные cheating skills [7]. Это vendor-confirmed observation, не независимый эксперимент.

**Что мешает сейчас:**

- Phase 3 запрещает executor менять acceptance test, fixtures, config, markers и selection; oracle сравнивается с RED commit (`pipelines/default/prompts/roles/full-cycle.md`).
- Shared rule проходит trigger test и orchestrator triage; canonical KB fact требует evidence, stable key, rejected history, а canonical link — approved receipt (`self-improvement.md:12-63`, `research-method.md:144-169`).
- Worktree diff, immutable acceptance oracle и reviewer дают внешние наблюдаемые seams, которых нет у чистой self-reward.

**Что не мешает:** personal memory всё ещё no-approval и low-bar; evidence может доказывать лишь proxy («команда green»), а не намерение; нет автоматического детектора, что новый memory/skill оптимизирует обход criterion. Поэтому current protection сильнее для shared/canonical state, но не закрывает вредную личную память. Rollback после обнаружения не заменяет prevention.

**Hermes на том же сценарии:** background skill prompt запрещает one-off/transient lessons и не может менять protected skills; current initial write всё же свободен, content scanner off, а often-used harmful skill не станет stale. Curator maintenance поэтому снижает accidental drift/loss, но не решает reward alignment. `3 agent-created из 84 total` не доказывает обратное: знаменатель opportunities неизвестен, а два curator runs не являются двумя skill-generation reviews.

## Findings и confidence

- **F1 — CONFIRMED:** Orchestra уже покрывает daemon-backed session recovery, hierarchical orchestration, A2A, durable files/memory и persisted scheduling. Основание: local repo code (`app/main.py:401-407`, `app/manager.py:2207-2329`, `app/mcp_stdio.py:930-963,1152-1200,2857-2904`) + Prime official vendor architecture/docs [4][5]. Evidence tier: primary local code + primary vendor documentation, не независимое reproduction.
- **F2 — CONFIRMED:** Orchestra не имеет Prime-equivalent IPython/kernel/context-as-variable runtime. Основание: исправленный direct measurement с отдельными ripgrep expressions: `rg ... -e 'ipython' -e 'jupyter' -e 'kernel[-_]state' -e 'prompt-as-a-variable' -e 'context-as-variable' app pipelines pyproject.toml` → `RC=1`; positive control нашёл persisted JSONL session store в `app/harness/sessions.py:23-79`. Evidence tier: local measurement + primary code. Первоначальный `rg 'a\|b'` oracle отозван: для ripgrep он искал literal `|`.
- **F3 — CONFIRMED:** Prime `/refine` защищает immutable base, scope, conflicts и rollback, но apply-time validation не проверяет factual truth; `evidence` заполняется `proposal.rationale`. Основание: source `refinement.ts:673-810` [6]. Evidence tier: primary implementation.
- **F4 — CONFIRMED:** Prime-like direct canonical apply противоречит Orchestra #417 candidate→approval contract. Основание: `research-method.md:159-169` против `refinement.ts:716-810`. Evidence tier: primary code/policy.
- **F5 — LIKELY:** optional RLM compute может быть полезен на больших повторно анализируемых inputs, но full replacement не обоснован для Orchestra. Основание «за»: RLM primary paper и Prime report [7][9]; «против»: typed λ-RLM primary paper [11]; Orchestra-shaped A/B отсутствует. Evidence tier: conflicting primary research, not locally reproduced.
- **F6 — CONFIRMED как vendor observation, не как causal general law:** Factorio refinement закрепил RCON exploit в cheating skills [7]. Evidence tier: single vendor primary report; independent reproduction отсутствует.
- **F7 — CONFIRMED:** `bg_create` нельзя обобщать до «любой computation переживает restart»: non-run jobs restore, `run` получает interrupted notification. Основание: `app/bg_jobs.py:488-529`. Evidence tier: primary local code.
- **F8 — LIKELY:** автоматические per-worker worktrees/ownership/merge gates отсутствуют в публичной Prime architecture. Основание: Prime README требует от пользователя выбрать clean worktree [1], а official architecture перечисляет process/session boundaries без per-child Git owner [4]. Evidence tier: two vendor primary documents; exhaustive negative source audit не выполнялся.
- **F9 — CONFIRMED:** Hermes initial memory/skill writes не approval-gated по умолчанию и на текущей машине: `write_approval.py:62-89,253-289` defaults false; current read-only config имеет `memory:` и `skills:` без `write_approval`. Evidence tier: installed v0.20.1 source + live config inspection.
- **F10 — CONFIRMED:** Hermes разделяет LLM mutation и deterministic archive. Background LLM hard-refuses bundled/hub/pinned/user-owned (`skill_manager_tool.py:301-420`), но deterministic curator с `prune_builtins=true` архивирует bundled по inactivity (`curator.py:192-201,305-383`). Evidence tier: installed implementation. Help-строка «bundled ... never touched» REFUTED as behavioral description.
- **F11 — UNCERTAIN:** `3 agent-created из 84 total (3.57%; 81 bundled)` не доказывает консервативность и не является creation count: adoption тоже ставит managed marker. `runs=2` считает curator maintenance, а creation opportunities задаёт background-review cadence; current `creation_nudge_interval=15` tool iterations. Без числа fork runs/candidates/denials причинный вывод невозможен. Evidence tier: direct status/config measurement + missing denominator.
- **F12 — CONFIRMED:** Hermes curator снижает mutation/loss blast radius, но не предотвращает Factorio-class reward hacking: new background skill может land без approval; active harmful skill не aging-out; content scanner/write approval optional and off. Evidence tier: installed code/docs (`background_review.py:182-285`; `configuration.md:652-683`).

## Counter-evidence и ограничения

1. Prime `/refine` не является безоглядным переписыванием system prompt: base prompt programmatically rejected, default scope local, global explicit, concurrent edit rejected, rollback основан на before/after snapshots [6]. Поэтому вывод «любая self-refinement опасна» **REFUTED**.
2. Orchestra не может заявить, что вся память проходит human approval: personal memory intentionally no-approval and low-bar (`self-improvement.md:65-84`). Поэтому вывод «наш durable state полностью защищён #417» **REFUTED**.
3. RLM имеет опубликованные positive long-context results [9], а Prime сообщает competitive long-running results [7]. Но они не измеряют multi-project worktrees, delivery semantics, merge gates или наш task pipeline; перенос результата на Orchestra остаётся uncertain.
4. λ-RLM — не воспроизведение Prime Agent и не доказывает, что Prime implementation хуже Orchestra; это counter-evidence против тезиса «open-ended REPL по определению надёжнее typed tools» [11].
5. ARC-AGI-3 проверяет interactive adaptation [10], но self-reported harness score из постановки не является независимой оценкой архитектурной дельты. Никакой механизм не повышен в применимости только из-за этого числа.
6. Исследование read-only: Prime runtime не запускался. Поэтому operational costs kernel snapshots, memory GC и actual provider compatibility оценены по source topology, а не измерены локально.
7. Hermes не «не имеет REPL вообще»: optional Jupyter skill даёт live stateful kernel (`jupyter-notebook.md:17-51`). Это не default/only tool и не context-as-variable, но снимает слишком широкое отрицание.
8. Hermes имеет optional `skills.write_approval`/`memory.write_approval`; вывод «Hermes всегда пишет без человека» неверен. Точный вывод уже: feature существует, defaults/current config выключены.
9. Live Hermes help и source конфликтуют по bundled. Источник поведения — installed code+effective config; help остаётся evidence user-visible contract drift, а не runtime semantics.
10. Orchestra имеет Claude SDK `fork_session` для targeted safeguard rewind (`app/session_turns.py:24-66`); прежняя фраза «session tree отсутствует» сужена до отсутствия general cross-runtime tree/leaf interface.

## Rule candidate from the corrected Hermes input

Trigger test: не могу назвать проект, где CLI/help и installed implementation принципиально не могут разойтись; trigger общий, не Hermes-specific.

📝 RULE: Когда load-bearing поведение заявлено из `--help` → сверить installed code и effective config; при расхождении behavior брать из кода с `path:line`, а help цитировать как заявление контракта, не как факт исполнения.

## Затрагиваемые owners, риски и edge cases для возможной следующей фазы

Ни один файл ниже не предлагается менять в этой фазе; это карта blast radius для обсуждения вариантов.

- **RLM/REPL branch:** `app/session.py`, `app/manager.py`, `app/backend_*.py`, `app/runtime_registry.py`, `app/db.py`, prompt/tool registry, session recovery tests. Edge cases: compaction while cell active, crash between kernel snapshot and transcript append, duplicated recursive usage attribution, orphan child handles, shared credentials.
- **Refine/proposal branch:** `pipelines/default/prompts/modules/self-improvement.md`, `research-method.md`, `app/pipeline.py`, `app/prompting.py`, `docs/kb` validator and task approval receipts. Edge cases: local/global scope inversion, rollback after later dependent edit, stale source evidence, deletion of a still-current fact, dirty worktree from skill injection.
- **Session-tree branch:** `app/db.py`, `app/session.py`, `app/routes/sessions.py`, dashboard chat/history. Edge cases: delivery/order across branches, cost attribution, user message landing on non-current leaf, compaction summary provenance.
- **Autonomous-goal branch:** `app/bg_jobs.py`, session queue/turn state, task approval and quota admission. Edge cases: goal continues across Phase gate, quality command green for wrong reason, missed/duplicated wake after restart.
- **Worktree/A2A branch:** current design already covers the mechanism; relaxing terminal-worker spawn or family/scope rules risks unauthorized subtasks, overlapping files and quota burn.

## Mechanical completeness checks

- Required mechanism rows M1–M7 are present; additional rows M8–M12 separate history, scheduling, trust boundary, executable skills and write authorization.
- The comparison table has exactly the seven updated columns: mechanism, Prime Agent, Hermes, Orchestra evidence, applicability, price, breakage.
- Every `есть ли у нас` cell contains repo `file:line` evidence or an explicit `нет` backed by a command.
- All three mandatory questions have direct sections and answers.
- No Prime code was installed, executed or cloned. Hermes was inspected read-only from the installed v0.20.1 source/docs/config; no `curator run/prune/archive`, skill/memory mutation, setup/reset/off or config write occurred.
- `docs/kb/README.md` intentionally remains unchanged under the task's explicit instruction; the orchestrator owns the later index insertion.

## Review decision gate inputs

- **Changed files / consumers:** `docs/tasks/421/research.md` читает orchestrator/user на Phase-1 gate; `docs/kb/prime-agent.md` читает следующий agent через file-first memory gate. Исполняемый production consumer не изменён.
- **Author metadata:** `gpt-5.6-sol`, runtime/backend `codex` — `get_worker_info(research-prime-agent)` от 2026-08-30.
- **Exact AC:** таблица ровно из семи обновлённых колонок с Prime/Hermes/Orchestra; минимум M1–M7; repo `file:line` в каждой оценке Orchestra; direct trust-model/write-right answer; три обязательных вопроса; primary Prime/Hermes sources + ARC Prize; `research.md` + KB topic; no Prime run/install/clone and Hermes read-only only; Phase 1 stop; README untouched.
- **Named delivery/mechanical check:** Python structural check → `TABLE_ROWS=12; REQUIRED_MECHANISMS=7/7; REQUIRED_QUESTIONS=3/3; COLS=7; HERMES_TRUST=present; CURATOR_WRITERS=2`; new-file patch `git diff --no-index -- /dev/null docs/kb/prime-agent.md > /tmp/421-kb.patch` (expected RC=1, 36 lines), then `python3 scripts/check_kb_contract.py --root docs/kb --diff /tmp/421-kb.patch` → `KB contract OK`; `git diff -- docs/kb/README.md | wc -l` → `0`.
- **Review route:** Luna Round 1 нашёл invalid `rg`, Claude `fork_session`, overbroad lifecycle/absence statements и citation ranges; artifact materially changed → one evidence-backed Luna resume разрешён; no Sol authorization.
- **Review outcome after ceiling:** Luna Round 2 подтвердил все Round-1 fixes, затем нашёл missing curator-create writer и два suggestions. Все три исправлены по installed source; prose ceiling=2 запрещает Round 3. Reviewer artifact сохраняет `Not ready` на pre-fix state, а post-verdict fixes перечислены в `review-research-luna.md` и не называются reviewer-approved.

## Sources

Evidence tier for [1]–[8] and [13]–[17]: **primary vendor source** (authoritative for implementation/claims, not independent performance validation). [9], [11]: **primary research preprints**. [10], [12]: **official benchmark source**. [18]: **direct read-only measurement of the installed Hermes v0.20.1 contour**.

1. [Prime Agent README](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/README.md) — product invariants, current-directory/worktree advice, trust boundary.
2. [RLM Programming Model](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm.md) — one IPython tool, programmatic context and host bridge.
3. [RLM Runtime Architecture](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm-runtime.md) — child handles, persistent harness, session artifacts, rollback and kernel trust boundary.
4. [Prime Agent Architecture Overview](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/architecture.md) — daemon/worker/kernel/storage ownership.
5. [Long-Running and Background Agents](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/long-running-agents.md) — detach/reattach, A2A receipts, schedules, goals and recovery.
6. [Prime Agent refinement implementation](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/src/core/refinement/refinement.ts#L673-L844) — validation, apply, CAS-like baseline check and rollback snapshots.
7. [Prime Agent: A self-improving RLM agent](https://www.primeintellect.ai/blog/prime-agent) — official technical post, architecture, `/refine`, Factorio/RCON observation and vendor evaluation claims.
8. [Continual Harness: Online Adaptation for Self-Improving Foundation Agents](https://arxiv.org/abs/2605.09998) — formal `p,G,K,M`, online CRUD refinement and model/harness co-learning.
9. [Recursive Language Models](https://arxiv.org/abs/2512.24601) — primary RLM method/results.
10. [ARC-AGI-3 official page](https://arcprize.org/arc-agi/3) — benchmark purpose and evaluation properties.
11. [The Y-Combinator for LLMs: Solving Long-Context Rot with λ-Calculus](https://arxiv.org/abs/2603.20105) — primary counter-evidence on open-ended REPL control.
12. [Prime-linked ARC Prize scorecard](https://arcprize.org/scorecards/2af780b4-f2a1-43e9-a794-b23da3cd3f9f) — official scorecard endpoint; dynamic page did not expose data in fetched HTML and was not used to recompute the task premise.
13. [Hermes Agent official repository](https://github.com/NousResearch/hermes-agent) — product/source owner.
14. [Hermes Curator documentation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/curator.md) — cadence, deterministic transitions, consolidation default, ownership, backup/rollback.
15. [Hermes Skills System](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md) — `/learn`, `skill_manage`, progressive disclosure and write approval surface.
16. [Hermes Persistent Memory](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md) — MEMORY/USER stores, automatic model writes and frozen session snapshot.
17. [Hermes Delegation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/delegation.md) — nested roles, A2A-adjacent child control, background completion and optional worktree isolation.
18. Installed Hermes v0.20.1 read-only evidence: `/home/maxim/.hermes/hermes-agent/agent/curator.py:70-78,192-217,305-383,430-539`; `agent/background_review.py:182-285`; `tools/skill_manager_tool.py:301-460,1542-1631`; `tools/write_approval.py:62-89,253-289`; `/home/maxim/.hermes/config.yaml:79-90`; live status supplied by the orchestrator: runs=2, consolidate off, 3 agent-created + 81 bundled, stale=0, archived=0.
