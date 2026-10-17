# Context for item-05

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/docs/tasks/203/codex-review-move.md b/docs/tasks/203/codex-review-move.md
new file mode 100644
index 000000000..f556a8fe7
--- /dev/null
+++ b/docs/tasks/203/codex-review-move.md
@@ -0,0 +1,44 @@
+The single shared module is preferable to two copies and reaches exactly the currently declared spawn-capable roles without changing the moved text's ordering relative to `orchestration`. However, the escalation criterion is not fully machine-decidable, and the regression test can miss routing leakage that omits the XML wrapper.
+
+Full review comments:
+
+- [P2] Require acceptance criteria to have machine-verifiable outcomes — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/modules/model-routing.md:7-7
+  The escalation trigger is not decidable from machine evidence alone: CLOSED only requires that acceptance criteria can be named, so a criterion such as “the wording is clear” can be judged unmet without any objective signal. The red-test branch is deterministic, and the wording clearly forbids a second Luna attempt, but the AC branch needs to require an explicit machine-checkable verification command or result.
+
+- [P2] Test routing content rather than only its wrapper tag — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/tests/test_default_pipeline.py:147-147
+  This test stays green if routing silently reaches `worker` without the exact `<model-routing>` wrapper—for example, copying the Luna bullet or the whole block minus its tags into `base.md` makes the worker receive the rule while this negative assertion still passes. Since the test claims routing reaches only spawn-capable roles, assert a stable routing-content anchor is absent from `worker` (and ideally that its source is the dedicated module), not only the opening tag.
+
+## Round (2026-08-12T03:21:23Z)
+
+Re-review status:
+
+1. **AC finding: FIXED, but NEW BUG in another escalation branch.** Luna now requires command evidence: “**the named test command stays red, or an acceptance criterion is not shown met by the output of a command**” and rejects unverifiable ACs: “**A criterion nobody can check by running something is not an AC**”.
+
+   However, Spark still says: “**Escalate to Sol if a test fails or scope grows.**” An agent can assert that “scope grows” without machine-checkable evidence. So yes, one escalation branch remains non-decidable.
+
+2. **Routing-test finding: STILL BROKEN.** Mutation: copy only this Opus routing instruction into `base.md`:
+
+   > “**Opus 5 (`claude-opus-5[1m]`) — DEFAULT for OPEN work: implementation with unknowns, fixes, review, general multi-step work; strongest for ambiguity/dialogue, reading between the lines, creative prose, images, and 1M-context synthesis. A closed task goes to Luna instead.**”
+
+   Worker then receives real model-routing content, while none of the tested anchors—“`<model-routing>`”, “`gpt-5.6-luna`”, or “`ahead of the Opus default`”—is present. `out.count(module) == 1` also remains true for spawn-capable roles.
+
+Verdict: **STILL BROKEN**—both requested properties retain a counterexample.
+
+## Round (2026-08-12T03:23:07Z)
+
+Re-review status: both prior findings **FIXED**.
+
+The test requires each spawn-capable prompt to contain the complete module exactly once:
+
+> `assert out.count(module) == 1, f"{role}: маршрутизация должна прийти ровно из модуля"`
+
+It also rejects every verbatim routing bullet in `worker`:
+
+> `for anchor in ["<model-routing>", *bullets]:`  
+> `    assert anchor not in worker_out, f"маршрутизация протекла воркеру: {anchor[:40]}"`
+
+I cannot construct a mutation that stays green while a listed spawn-capable role loses routing or `worker` receives a verbatim bullet. The remaining counterexample requires manually rewording routing content; the docstring explicitly records that accepted limitation.
+
+New findings: none.
+
+Verdict: **APPROVED**.
diff --git a/docs/tasks/203/report.md b/docs/tasks/203/report.md
index 81a61484c..5326424f7 100644
--- a/docs/tasks/203/report.md
+++ b/docs/tasks/203/report.md
@@ -60,20 +60,110 @@ bulk-правка подходили и под Luna, и под Sol («also …»
 Третьего раунда нет — потолок для прозы 2 раунда, безусловный.
 
 ## Приёмка — сборкой промпта, не чтением
 ```
 build_system_prompt(DEFAULT_PIPELINE, role), прогон из своей воркти:
 role              luna_id terra old_pilot closed_ahead effort_both sol_closed_exc spark_pool  bytes
 orchestrator      True    False False     True         True        True           True        42481
 sub-orchestrator  True    False False     True         True        True           True        42832
 worker            True    False False     True         True        True           True        25211
 full-cycle        True    False False     True         True        True           True        41493
 ```
 `terra=False` по всем ролям — старая строка не осталась нигде; `old_pilot=False` — формулировка
 «только по пилотной команде» исчезла. Тесты не запускал: правка текстовая, кода не касается.
 
 ## Найденное попутно (не чинил — не мой мандат)
 `<model-routing>` лежит в `base.md`, то есть в промпте ВСЕХ ролей, но действовать по нему может
 только тот, кто умеет спавнить. У роли `worker` `can_spawn: []` (`pipeline.yaml:58`), а сессий с
 этой ролью 75 из 121 (62%, свежий счёт по `sessions`, read-only). Эти 75 платят +877 Б за блок,
 которым не могут воспользоваться, и платили за него и раньше — 2126 Б. Кандидат на переезд блока
 из `base.md` в модуль `orchestration` + роль `full-cycle`; это решение оркестратора, не моё.
+
+---
+
+# Продолжение #203: эскалация Luna + переезд блока к исполнителям
+
+Коммит второй. Файлы: `pipelines/default/prompts/modules/model-routing.md` (новый),
+`pipelines/default/prompts/base.md` (−12 строк), `pipelines/default/pipeline.yaml` (3 роли),
+`tests/test_default_pipeline.py` (+1 тест, обновлены списки модулей).
+
+## Правка A — путь эскалации у Luna
+
+Было: у Spark путь провала прописан, у Luna нет — агент мог законно переспросить Luna на той же
+задаче и потратить экономию 20× на круги. Стало (в пункте Luna):
+
+> **On failure escalate, never retry: the named test command stays red, or an acceptance criterion
+> is not shown met by the output of a command → hand that ticket to Sol, do not send it back to
+> Luna.** A criterion nobody can check by running something is not an AC, and its task was never
+> closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at
+> Sol's price.
+
+Вторая фраза появилась после ревью: Codex показал дыру — «критерий приёмки не выполнен» решается
+на глаз, если сам критерий вида «формулировка ясная». Теперь такой критерий выводит задачу из
+класса закрытых, то есть до Luna не доходит вовсе.
+
+**Сверх мандата, называю явно:** у Spark триггер `scope grows` страдал тем же — заменён на
+`the ticket needs a file outside the ones you named → Sol`. Одна фраза, тот же дефект, тот же
+блок; если считаешь это лишним — откатывается одной строкой.
+
+## Правка B — блок переехал к тем, кто может его исполнить
+
+Новый модуль `modules/model-routing.md`, подключён в `pipeline.yaml` первым в списке `modules`
+у `orchestrator`, `sub-orchestrator`, `full-cycle` (все `can_spawn: ["*"]`), из `base.md` удалён.
+
+**Отступление от буквы поручения, обоснование.** Было сказано «`orchestration` + роль
+`full-cycle`». Это две копии одного правила: `orchestration` не грузится ролью `full-cycle`
+(`pipeline.yaml:73`), поэтому пришлось бы дублировать текст в `roles/full-cycle.md` — ровно тот
+дрейф, который мы вычищаем. Отдельный модуль отдаёт блок тем же трём ролям одной копией.
+Первым в списке — потому что `modules/orchestration.md:175` говорит «Use the single
+`<model-routing>` block above»; порядок проверен на собранном промпте.
+
+`pipeline.yaml` правится руками: генератор `scripts/extract-manifest.py` мёртв — его источник
+`app/prompts/` удалён, `--check` не гоняет ни один тест и ни один workflow.
+
+## Приёмка
+
+```
+role              routing escalate above_ok bytes
+orchestrator      yes     True     True     42739 → +258 к #203
+sub-orchestrator  yes     True     True     43090
+full-cycle        yes     True     True     41751
+worker            NO      False    True     23083  (−2128 Б, блок ушёл)
+```
+
+Тесты: `tests/test_default_pipeline.py tests/test_pipeline.py tests/test_manager.py` — **288
+passed** (`/tmp/pytest-203c.log`).
+
+Новый тест `test_model_routing_reaches_only_spawn_capable_roles` держит обе стороны: блок ровно
+один раз у каждой спавн-способной роли (`out.count(module) == 1`) и ни одного дословного пункта
+у `worker`. Якоря берутся ИЗ модуля (`ln.startswith("- **")`), а не выписаны руками.
+
+Мутации — 6, все красные:
+1. `model-routing` добавлен воркеру;
+2. убран у `full-cycle`;
+3. **составная**: убран у `full-cycle` И блок возвращён в `base.md`;
+4. модуль указан дважды у оркестратора (проверяет `count == 1`);
+5. пункт **Luna** скопирован в `base.md` без тегов;
+6. пункт **Opus** скопирован в `base.md` без тегов (это контрпример Codex к первой версии теста —
+   она была на нём зелёной).
+
+Предел теста записан в докстринге честно: дословную копию пункта он ловит, переписанную своими
+словами — нет.
+
+## Codex — 3 раунда (исполняемый артефакт), `docs/tasks/203/codex-review-move.md`
+
+- Р1: два P2 — (а) ветка «AC не выполнен» не машинная; (б) тест зелен на копии без тегов. Приняты.
+- Р2: обе исправленными не признаны до конца — нашёл, что немашинный триггер остался у Spark, и
+  привёл рабочий контрпример к тесту (копия пункта Opus). Обе приняты и закрыты.
+- Р3: **APPROVED**, дословные цитаты текущего файла в вердикте, новых находок нет.
+
+## Что ещё в `base.md` воркер исполнить не может (перечислил, не трогал)
+
+- `:10` `**Auto-report.**` — половина абзаца про то, что у оркестраторов авто-репорта нет.
+- `:16` `**Cross-project.**` — «если ты оркестратор, можешь писать чужим оркестраторам».
+- `:23` `list_orchestrators()` в списке тулов — с оговоркой «workers should NOT use this».
+- `:39` критическое правило про `Agent tool` — ветка «Spawn-capable roles use `spawn_worker`».
+- `:53` context economy — ветка «spawn-capable roles may delegate a bounded slice».
+
+Общая форма у всех одна: правило с развилкой «ты оркестратор → …; ты воркер → …». В отличие от
+`<model-routing>`, у каждого есть и вторая половина, адресованная воркеру, поэтому механический
+перенос их сломает — нужно резать надвое. Не трогаю без твоего слова.
diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index ad5981922..29afc4803 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -176,40 +176,48 @@ DONE WHEN: наблюдаемое условие завершения.
   нового списка нормализованных строк: исчезло ровно то, что удалял осознанно. Оркестратор
   зачёл это отдельно — «доказал, а не заявил».
 
 ## Правишь модуль — сперва проверь, КТО его грузит (2026-08-04, #148)
 
 - **`pipelines/default/pipeline.yaml`, поле `modules:` — карта адресатов. Читать ДО правки текста.**
   `research-method` грузит ТОЛЬКО `full-cycle`. Роль `worker` (207 сессий против 161 у full-cycle)
   не видит ни Step 0-5, ни строк про prior art. Задача звучала «поправь research-method», и
   правка там на целевом кейсе не изменила бы НИЧЕГО — тот воркер этот модуль не читает.
 - Порядок: `grep -n 'modules:' pipeline.yaml` + `SELECT role, COUNT(*) FROM sessions GROUP BY role`
   → и только потом решай, куда класть. Иначе чинишь текст для роли, которой проблема не касается.
 - Массовой роли не отдавать тяжёлый модуль целиком ради одного абзаца: owner — в модуле,
   в роль — строка-гейт со ссылкой (иначе +100 строк промпта на 207 сессий).
 - **Правило про эффорт исполнимо только как выбор РОЛИ: у `spawn_worker` нет параметра эффорта**
   (`app/mcp_stdio.py:711-720`), он приходит из манифеста — `pipeline.yaml`: orchestrator/sub `medium`,
   `worker` `high`, `full-cycle` `xhigh` (строки 23/39/55/71). Прежде чем писать «не ставь X»,
   проверь, есть ли у адресата рычаг: иначе это инструкция, которую некому выполнить (#203).
 - **`base.md` платят ВСЕ роли, а спавнить умеют не все.** `<model-routing>` живёт в `base.md`, но
   `worker` (`can_spawn: []`) действовать по нему не может, а это 75 сессий из 121 (62%, #203).
   Прежде чем расширять общий слой, спроси: этот текст кому-то из читателей вообще исполним?
+- **`pipeline.yaml` правится РУКАМИ: `scripts/extract-manifest.py` мёртв** — его источник
+  `app/prompts/` удалён, `--check` не гоняют ни тесты, ни CI (#203). Но `tests/test_default_pipeline.py`
+  прибит к спискам `modules` дословно — меняешь манифест, правь и его в том же коммите.
+- **Тест «текст НЕ протёк в чужой промпт»: якоря брать ИЗ файла-источника, а не выписывать руками.**
+  Мои три ручных якоря (тег + две фразы про Luna) остались зелёными, когда Codex скопировал в общий
+  слой СОСЕДНИЙ пункт того же блока — про Opus. Рабочая форма: вытащить все пункты модуля
+  (`ln.startswith("- **")`), потребовать их отсутствия у чужой роли и `out.count(module) == 1`
+  у своих. Плюс гард на непустоту списка якорей: пустой список красит тест зелёным (#203).
 - **Приёмка правки модуля — `build_system_prompt(DEFAULT_PIPELINE, role)` по всем ролям сразу**
   (`app/pipeline.py:427`): печатает, у кого новый текст есть и у кого исчез старый, за один прогон.
   `role_prompt_file()` (`app/prompting.py:132`) для этого НЕ годится — роли теперь frontmatter-free,
   модули приходят из `pipeline.yaml`, и функция вернёт голый файл роли (#196: 578 Б у оркестратора).
 - **Тот же вопрос на уровень ниже (#149): мало знать, какая роль подписана на контент —
   проверь, ДОСТИГАЕТ ли её код доставки.** `inject_skills_to_worktree` живёт под
   `if use_worktree and repo_path:` (`manager.py:669`), а 16 из 17 оркестраторов работают
   БЕЗ worktree → скиллы, прописанные им в `pipeline.yaml`, не доезжали никогда, а не
   «протухали». Замер, разделивший гипотезы за одну команду:
   `find worktrees -path "*/.claude/skills/<new-skill>/SKILL.md" | wc -l` → 0.
   Формулировка «обнови старые копии» увела бы мимо: чинить надо было отсутствие доставки.
 - Порядок дополняется: `pipeline.yaml` (кто подписан) → grep вызова (кто реально получает)
   → `SELECT role, ... FROM sessions` (сколько таких живых). Расхождение 1-го и 2-го = баг.
 - **Прежде чем изобретать механизм обновления — грепни, нет ли в репо той же задачи уже
   решённой.** `sync_agents_md` (`workspace.py:400`) чинит ровно этот класс («snapshot from
   the day it was spawned») и стоит на `_ensure_backend`; мне осталось назвать точку, а не
   проектировать её. Ключевые слова для поиска: `reconnect`, `stale`, `mirror`, `refresh`.
 - Асимметрия рантаймов, которую легко проглядеть: Claude читает КОПИЮ в worktree, Codex —
   ОРИГИНАЛ по абсолютному пути (`build_codex_skills_index` на каждом коннекте). Протухает
   только Claude. Перед «покрыть оба рантайма» проверь, не покрыт ли второй уже.
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 77918b055..c44b17da1 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -5,80 +5,80 @@ defaults:
   model: opus
   skills: []
   mcp_servers: []
   inherit_claude_md: true
   prompt_layers:
     orchestrator: [base.md, "roles/{role}.md"]
     worker:       [base.md, "roles/{role}.md"]
   worktree:
     symlinks: []
     copies:   [CLAUDE.md, .mcp.json, .env, .worktreeinclude]
   base_branch_strategy: main
   docs_scaffold: false
 roles:
   orchestrator:
     kind: orchestrator
     label: Orchestrator
     order: 0
     model: claude-opus-5[1m]
     effort: medium
     skills: [html-artifacts, vps-deploy, codex-debate, grill-me, orchestra-agents]
-    modules: [git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
+    modules: [model-routing, git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "👑"}
     when: Managing a team of workers, decomposing tasks, approving plans
     not_for: Direct implementation — delegate to workers
     description: >
       Manages worker agents. Decomposes tasks, spawns workers, reviews results.
       Available worker roles are injected automatically from roles/ directory.
   sub-orchestrator:
     kind: orchestrator
     label: Sub-Orchestrator
     order: 1
     model: claude-opus-5[1m]
     effort: medium
     skills: [orchestra-agents]
-    modules: [git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
+    modules: [model-routing, git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "🎯"}
     when: Managing a sub-team within a larger hierarchy (department lead, tech lead, team lead)
     not_for: Direct implementation — delegate to workers
     description: >
       Manages a subset of workers under a parent orchestrator.
       Reports up to parent, delegates down to workers.
   worker:
     kind: worker
     label: Worker
     order: 2
     model: claude-opus-5[1m]
     effort: high
     skills: [html-artifacts, codex-debate]
     modules: [git-workflow, report-format, self-improvement, memory-search]
     can_spawn: []
     allow_unrouted_workers: false
     tg: {emoji: "⚙️"}
     when: Clear task for a known module, implementation from detailed spec, bug fix with known repro
     not_for: Tasks needing research or unknown scope — use full-cycle
     description: >
       General-purpose worker. Implements tasks directly, no pipeline gates.
       For system workers (permanent, module-scoped) and disposable one-shots.
   full-cycle:
     kind: worker
     label: Full-Cycle
     order: 3
     model: claude-opus-5[1m]
     effort: xhigh
     skills: [html-artifacts, codex-debate]
-    modules: [research-method, git-workflow, worker-lifecycle, report-format, self-improvement, memory-search]
+    modules: [model-routing, research-method, git-workflow, worker-lifecycle, report-format, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: false
     tg: {emoji: "🔄"}
     when: New feature with unknowns, large refactoring (5+ files), external integration, deep research (find out everything about X), empirical measurement / benchmarks, anything where wrong approach = wasted day
     not_for: Trivial bug fixes, config changes, one-line implementation from a clear spec
     description: >
       Research+Experiment (truth from sources and/or measurements) → Plan sliced into
       tickets with acceptance criteria → Implement ticket-by-ticket. Strict 3-phase
       pipeline, 2 orchestrator approval gates, Codex review at plan + impl. For a
       research-only task the orchestrator simply stops after Phase 1. All artifacts
       in docs/tasks/<id>/.
diff --git a/pipelines/default/prompts/base.md b/pipelines/default/prompts/base.md
index a0bad8ae9..5473782a8 100644
--- a/pipelines/default/prompts/base.md
+++ b/pipelines/default/prompts/base.md
@@ -56,32 +56,20 @@ manage them; the available types and their parameters are in the `bg_create` too
 
 <communication-style>
 ## Communication style (all agents)
 Applies to working comms — reports, status, agent↔agent. NOT to `docs/tasks/*.md` (research/plans stay full), NOT to the orchestrator's user-facing chat voice.
 - Brevity. Don't narrate your tool calls — they're visible in the logs. Did it → one line (what + result).
 - Don't repeat the same status 2-3 times. Don't explain the obvious.
 - Intermediate updates ("waiting for Codex", "worker is running") are noise. Speak when there's a RESULT or a DECISION is needed.
 - **Never send acknowledgement-only messages** such as "OK", "Принято", "Зафиксировано", or "additional actions are not required". If an agent message contains only acknowledgement/confirmation and no new task, question, blocker, or fact, do not reply and end the turn silently. This rule prevents agent-to-agent acknowledgement loops.
 - Causality as `X → Y`, not "because X, this leads to Y".
 - No pleasantries agent↔agent ("great!", "thanks for..."). Straight to the point.
 - Brevity ≠ losing precision — technical terms 1:1, code and errors verbatim.
 
 **Written artifacts (`docs/tasks/*.md`, reports, docs you write to disk) are exempt from brevity,
 not from calibration.** Length is earned by NEW facts: a quote you fetched, a number you measured,
 a file:line, a decision and its basis. Evidence is never the thing you cut — a long document made
 of measurements is correctly long. What comes out regardless of total length: a section that
 restates an earlier one, a summary of the summary, boilerplate framing, and a table that repeats
 the paragraph above it. If a section contains no fact absent from the rest of the document, it is
 padding whether the file is 5 KB or 50 KB.
 </communication-style>
-
-<model-routing>
-## Model routing — which model to pass to `spawn_worker`
-Pick deterministically by task class and current quota runway. Quota is a first-order routing
-factor: protect whichever weekly pool will exhaust first; route tasks suitable for either model
-to the healthier pool. If current telemetry is unavailable, use the manifest default.
-- **Opus 5** (`claude-opus-5[1m]`) — DEFAULT for OPEN work: implementation with unknowns, fixes, review, general multi-step work; strongest for ambiguity/dialogue, reading between the lines, creative prose, images, and 1M-context synthesis. A closed task goes to Luna instead.
-- **Luna** (`gpt-5.6-luna`) — CLOSED task, ahead of the Opus default: before spawning you can name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is open, route it above. Measured on 3 closed single-turn tasks (N=1 per cell): same work as Sol, 20.5× cheaper. Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at 164K); never for resolving references between similar fragments (vendor MRCR: Luna 41.3% vs Sol 91.5%, untested here).
-- **Sol medium** (`gpt-5.6-sol`) — OPEN task on the Codex pool: research, arguing with a review, architecture; also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters — these two take Sol even when the task is closed. Measured: Sol falsified bad hypotheses from live data and had 0 printed-tool-call failures versus 9 on Opus. Closed work goes to the `worker` role (manifest effort `high`), never to `full-cycle` (`xhigh`): on the two closed tasks measured, xhigh cost ×2.04 and ×1.13 without changing the verdict.
-- **Spark** (`gpt-5.3-codex-spark`) — closed task on its OWN pool: take it over Luna when the Codex pool is the binding constraint AND all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Escalate to Sol if a test fails or scope grows. NOT for research, architecture, vision, security.
-- **Orchestrators** — always Opus 5.
-</model-routing>
diff --git a/pipelines/default/prompts/modules/model-routing.md b/pipelines/default/prompts/modules/model-routing.md
new file mode 100644
index 000000000..f9b8eb03a
--- /dev/null
+++ b/pipelines/default/prompts/modules/model-routing.md
@@ -0,0 +1,11 @@
+<model-routing>
+## Model routing — which model to pass to `spawn_worker`
+Pick deterministically by task class and current quota runway. Quota is a first-order routing
+factor: protect whichever weekly pool will exhaust first; route tasks suitable for either model
+to the healthier pool. If current telemetry is unavailable, use the manifest default.
+- **Opus 5** (`claude-opus-5[1m]`) — DEFAULT for OPEN work: implementation with unknowns, fixes, review, general multi-step work; strongest for ambiguity/dialogue, reading between the lines, creative prose, images, and 1M-context synthesis. A closed task goes to Luna instead.
+- **Luna** (`gpt-5.6-luna`) — CLOSED task, ahead of the Opus default: before spawning you can name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is open, route it above. Measured on 3 closed single-turn tasks (N=1 per cell): same work as Sol, 20.5× cheaper. **On failure escalate, never retry: the named test command stays red, or an acceptance criterion is not shown met by the output of a command → hand that ticket to Sol, do not send it back to Luna.** A criterion nobody can check by running something is not an AC, and its task was never closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at Sol's price. Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at 164K); never for resolving references between similar fragments (vendor MRCR: Luna 41.3% vs Sol 91.5%, untested here).
+- **Sol medium** (`gpt-5.6-sol`) — OPEN task on the Codex pool: research, arguing with a review, architecture; also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters — these two take Sol even when the task is closed. Measured: Sol falsified bad hypotheses from live data and had 0 printed-tool-call failures versus 9 on Opus. Closed work goes to the `worker` role (manifest effort `high`), never to `full-cycle` (`xhigh`): on the two closed tasks measured, xhigh cost ×2.04 and ×1.13 without changing the verdict.
+- **Spark** (`gpt-5.3-codex-spark`) — closed task on its OWN pool: take it over Luna when the Codex pool is the binding constraint AND all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Same escalation as Luna, plus: the ticket needs a file outside the ones you named → Sol. NOT for research, architecture, vision, security.
+- **Orchestrators** — always Opus 5.
+</model-routing>
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 31be4f816..8138379ee 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -105,55 +105,75 @@ class TestDefaultRolesResolve:
         assert P.get_role(PIPELINE, "worker").can_spawn == []
         assert P.get_role(PIPELINE, "full-cycle").can_spawn == ["*"]
 
     def test_full_cycle_model_opus5(self):
         rr = P.get_role(PIPELINE, "full-cycle")
         assert rr is not None
         assert rr.model == "claude-opus-5[1m]"
 
     def test_sub_orchestrator_is_orchestrator_opus5(self):
         """sub-orchestrator — kind:orchestrator, Opus 5, can_spawn=['*']."""
         rr = P.get_role(PIPELINE, "sub-orchestrator")
         assert rr is not None
         assert rr.is_orchestrator is True
         assert rr.model == "claude-opus-5[1m]"
         assert rr.can_spawn == ["*"]
         assert rr.allow_unrouted_workers is True
 
     def test_modules_resolve_from_manifest(self):
         """modules пробрасываются из манифеста в ResolvedRole без слияния с defaults."""
         assert P.get_role(PIPELINE, "orchestrator").modules == [
-            "git-workflow", "orchestration", "worker-lifecycle", "background-jobs",
-            "task-management", "self-improvement", "memory-search",
+            "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
+            "background-jobs", "task-management", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "sub-orchestrator").modules == [
-            "git-workflow", "orchestration", "worker-lifecycle", "background-jobs",
-            "task-management", "self-improvement", "memory-search",
+            "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
+            "background-jobs", "task-management", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "worker").modules == [
             "git-workflow", "report-format", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "full-cycle").modules == [
-            "research-method", "git-workflow", "worker-lifecycle",
+            "model-routing", "research-method", "git-workflow", "worker-lifecycle",
             "report-format", "self-improvement", "memory-search",
         ]
 
+    def test_model_routing_reaches_only_spawn_capable_roles(self):
+        """Маршрутизация инлайнится ровно тем, кто умеет спавнить, и ровно из модуля (#203).
+
+        Якоря берутся ИЗ САМОГО модуля, а не выписаны руками: проверка по тегу-обёртке
+        и по паре фраз про Luna оставалась зелёной, когда в `base.md` копировали пункт
+        про Opus без тегов (Codex, раунд 2). Предел честно: дословную копию любого
+        пункта тест ловит, переписанную своими словами — нет.
+        """
+        module = P.prompt_path(PIPELINE, "modules/model-routing.md").read_text().strip()
+        bullets = [ln.strip() for ln in module.splitlines() if ln.startswith("- **")]
+        assert len(bullets) >= 5, "модуль потерял пункты — якоря стали слабее"
+        for role in ("orchestrator", "sub-orchestrator", "full-cycle"):
+            out = P.build_system_prompt(PIPELINE, role)
+            assert P.get_role(PIPELINE, role).can_spawn == ["*"]
+            assert out.count(module) == 1, f"{role}: маршрутизация должна прийти ровно из модуля"
+        worker_out = P.build_system_prompt(PIPELINE, "worker")
+        assert P.get_role(PIPELINE, "worker").can_spawn == []
+        for anchor in ["<model-routing>", *bullets]:
+            assert anchor not in worker_out, f"маршрутизация протекла воркеру: {anchor[:40]}"
+
     def test_tg_emoji_for_v216_roles(self):
         assert P.get_role(PIPELINE, "sub-orchestrator").tg.emoji == "🎯"
 
     def test_orchestrator_skills_from_manifest(self):
         rr = P.get_role(PIPELINE, "orchestrator")
         assert set(rr.skills) == {
             "html-artifacts", "vps-deploy", "codex-debate", "grill-me", "orchestra-agents",
         }
 
     def test_orchestrator_can_spawn_wildcard_and_unrouted(self):
         """Апстрим не ограничивает оркестратора: can_spawn=['*'], дефолтный
         role='worker'/пустая роль допустима."""
         rr = P.get_role(PIPELINE, "orchestrator")
         assert rr.can_spawn == ["*"]
         assert rr.allow_unrouted_workers is True
 
     def test_orchestrator_layers_substituted_no_pipeline(self):
         """Резолвнутые слои оркестратора: base + roles/orchestrator.md, БЕЗ _pipeline.md."""
         rr = P.get_role(PIPELINE, "orchestrator")
         assert rr.prompt_layers == ["base.md", "roles/orchestrator.md"]


## Later history of the touched files on main (after this commit)

72 later commits touch these paths; the first 40 (oldest first):
8b7860a81 2026-08-12 #207: #207: drop unattributed MRCR number, full-cycle effort xhigh->high
7ba8728be 2026-08-12 #213: #213: record per-model effort constraint, no discount route through Sol
0a665a832 2026-08-12 #210: #210: план Фазы 2 — план заканчивается красным тестом; оракул схемы закоммичен КРАСНЫМ
6b2249c59 2026-08-12 #214: #214: эффорт по модели — карта модель→ступень в манифесте
100cc871b 2026-08-12 #221: #221: add Telegram formatting rules to orchestrator prompt
9442bc38b 2026-08-12 #221: #221: add model routing priority oracle
45d761005 2026-08-12 #223: #223: correct barrier conclusion
bf5de05e2 2026-08-12 #222: #222: add Spark admission delivery oracle
6712fdcf4 2026-08-12 #219, #223: #219 T2: контракт делегирования «таблица, а не область» в worker-lifecycle + тесты на происхождение якорей (первая редакция теста была ложно-зелёной на составной мутации)
9fc4534e5 2026-08-12 #231: #231: предрегистрация эксперимента (стенд, критерий, все четыре исхода) — ДО спавна плеч
000927f30 2026-08-13 #223: #223: research explicit test-layer authorization
5c346ffd5 2026-08-13 #227: #227: enforce worker model policy at spawn
6163944bb 2026-08-13 #227: временно отключить worker_model_policy в манифесте — живой процесс со старой схемой роняет загрузку целиком; вернуть при рестарте
59ee1b11c 2026-08-13 #227: #227: gate Opus by Claude weekly pace
31011b1bc 2026-08-13 #247: #247: audit model catalog and dead prompt surfaces
9ad087342 2026-08-13 #247: #247: plan model readiness and prompt rollout
c26af1c3e 2026-08-13 #257: маркер тихого хода — в base.md для всех агентов, в CLAUDE.md только указатель
96192b400 2026-08-14 #36: #36: unknown roles fail closed in validate_spawn
580c425d3 2026-08-14 #209: #209: stop quoting manifest model ids in prompts; check catches copies
d38f8785a 2026-08-16 #283: #283: attribute measured prompt claims
0015743d7 2026-08-16 #296: #296: implement risk-based review routing
bd4f6e61a 2026-08-16 #304: #304: select codex review model explicitly
1fe3cf1d7 2026-08-18 #329: один владелец логики пулов — квотная арифметика вырезана из манифеста, блок выключен до рестарта
8c5ea3647 2026-08-18 #329: включён worker_model_policy — рестарт 18.08 17:31 UTC загрузил новую схему
937b513e6 2026-08-19 #314: аудит правил: противоречия, воркфлоу под апрув, база знаний по темам, сокращение CLAUDE.md
98ae5885b 2026-08-19 ревью не обязательно и без замены ревьюера; code-quality вынесен в модуль; оба контракта закрыты тестами
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
af58227ee 2026-08-19 #346: #346: правило формата ответа юзеру — блок <user-answer-format> в роли оркестратора
eac83b8aa 2026-08-19 #348: #348: шесть правил про поведение агентов перенесены из CLAUDE.md к владельцам в pipelines/
eb9d6ce28 2026-08-19 #349: #349: check_pipeline_manifest — якоря нового контракта ревью + числа внутри примера
8b6c8b50f 2026-08-19 #352: #352: block bounded regex blowup in Bash hook
0a00e9d2b 2026-08-22 скилл eli5 — только оркестраторам
9936efa4a 2026-08-23 #217: keep bounded local rule edits in orchestrator
7dd0b3419 2026-08-23 fix: require approval for auxiliary Sol runs
71374ea56 2026-08-23 #385: #385: research deferred turn control and provenance
9d2627281 2026-08-24 Merge origin/main into main (2026-08-24 sync)
6f874ace5 2026-08-24 #248: make task state platform-owned and restart-safe
c2ea45fa0 2026-08-25 #358: #358: complete typed document cutover
12d7554a9 2026-08-25 #362: restore file-backed memory prompts
fc9ce825e 2026-08-26 #361: deliver optional knowledge prompt capability

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 8b7860a81 #207: #207: drop unattributed MRCR number, full-cycle effort xhigh->high

diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index 29afc4803..6d93e001e 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -191,10 +191,15 @@ DONE WHEN: наблюдаемое условие завершения.
   `worker` `high`, `full-cycle` `xhigh` (строки 23/39/55/71). Прежде чем писать «не ставь X»,
   проверь, есть ли у адресата рычаг: иначе это инструкция, которую некому выполнить (#203).
 - **`base.md` платят ВСЕ роли, а спавнить умеют не все.** `<model-routing>` живёт в `base.md`, но
   `worker` (`can_spawn: []`) действовать по нему не может, а это 75 сессий из 121 (62%, #203).
   Прежде чем расширять общий слой, спроси: этот текст кому-то из читателей вообще исполним?
+- **Не цитируй в промпте значения, живущие в манифесте** (эффорт, модель, пул). Скобка
+  «`never to full-cycle (xhigh)`», написанная мной в #203, стала ложной в #207 — через сутки, тем
+  же диффом, которым меняли манифест. Ссылайся на смысл роли, а не на её настройку. То же и с
+  эффортом сессии: манифест читается ТОЛЬКО при спавне (`app/manager.py:660`), при восстановлении
+  берётся строка БД (`:1202`, `:1518`) — живые сессии старое значение сохраняют.
 - **`pipeline.yaml` правится РУКАМИ: `scripts/extract-manifest.py` мёртв** — его источник
   `app/prompts/` удалён, `--check` не гоняют ни тесты, ни CI (#203). Но `tests/test_default_pipeline.py`
   прибит к спискам `modules` дословно — меняешь манифест, правь и его в том же коммите.
 - **Тест «текст НЕ протёк в чужой промпт»: якоря брать ИЗ файла-источника, а не выписывать руками.**
   Мои три ручных якоря (тег + две фразы про Luna) остались зелёными, когда Codex скопировал в общий
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index c44b17da1..b2029c09f 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -66,11 +66,17 @@ roles:
   full-cycle:
     kind: worker
     label: Full-Cycle
     order: 3
     model: claude-opus-5[1m]
-    effort: xhigh
+    # xhigh → high (#207). Anthropic для Opus 5 велит начинать с high и НЕ переносить настройки
+    # прошлого поколения — унаследованный xhigh оттуда и пришёл; на девяти чужих бенчмарках
+    # high→xhigh даёт +47% цены без значимого прироста, наш #199 на Sol — ×2.04 при том же вердикте.
+    # НЕ ЗАКРЫТО: вендор оправдывает xhigh длиной горизонта задачи, а все опубликованные замеры
+    # короче наших сессий. Правка обратимая и наблюдаемая: пошли разваливающиеся длинные ходы →
+    # вернуть xhigh, и это будет данными, а не спором.
+    effort: high
     skills: [html-artifacts, codex-debate]
     modules: [model-routing, research-method, git-workflow, worker-lifecycle, report-format, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: false
     tg: {emoji: "🔄"}
diff --git a/pipelines/default/prompts/modules/model-routing.md b/pipelines/default/prompts/modules/model-routing.md
index f9b8eb03a..768655d90 100644
--- a/pipelines/default/prompts/modules/model-routing.md
+++ b/pipelines/default/prompts/modules/model-routing.md
@@ -2,10 +2,10 @@
 ## Model routing — which model to pass to `spawn_worker`
 Pick deterministically by task class and current quota runway. Quota is a first-order routing
 factor: protect whichever weekly pool will exhaust first; route tasks suitable for either model
 to the healthier pool. If current telemetry is unavailable, use the manifest default.
 - **Opus 5** (`claude-opus-5[1m]`) — DEFAULT for OPEN work: implementation with unknowns, fixes, review, general multi-step work; strongest for ambiguity/dialogue, reading between the lines, creative prose, images, and 1M-context synthesis. A closed task goes to Luna instead.
-- **Luna** (`gpt-5.6-luna`) — CLOSED task, ahead of the Opus default: before spawning you can name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is open, route it above. Measured on 3 closed single-turn tasks (N=1 per cell): same work as Sol, 20.5× cheaper. **On failure escalate, never retry: the named test command stays red, or an acceptance criterion is not shown met by the output of a command → hand that ticket to Sol, do not send it back to Luna.** A criterion nobody can check by running something is not an AC, and its task was never closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at Sol's price. Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at 164K); never for resolving references between similar fragments (vendor MRCR: Luna 41.3% vs Sol 91.5%, untested here).
-- **Sol medium** (`gpt-5.6-sol`) — OPEN task on the Codex pool: research, arguing with a review, architecture; also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters — these two take Sol even when the task is closed. Measured: Sol falsified bad hypotheses from live data and had 0 printed-tool-call failures versus 9 on Opus. Closed work goes to the `worker` role (manifest effort `high`), never to `full-cycle` (`xhigh`): on the two closed tasks measured, xhigh cost ×2.04 and ×1.13 without changing the verdict.
+- **Luna** (`gpt-5.6-luna`) — CLOSED task, ahead of the Opus default: before spawning you can name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is open, route it above. Measured on 3 closed single-turn tasks (N=1 per cell): same work as Sol, 20.5× cheaper. **On failure escalate, never retry: the named test command stays red, or an acceptance criterion is not shown met by the output of a command → hand that ticket to Sol, do not send it back to Luna.** A criterion nobody can check by running something is not an AC, and its task was never closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at Sol's price. Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at 164K). Resolving references across similar fragments we have never measured → that one goes to Sol. This is caution, not a known cliff: the third-party number once quoted here failed attribution, and an independent long-context benchmark shows no gap at any working effort.
+- **Sol medium** (`gpt-5.6-sol`) — OPEN task on the Codex pool: research, arguing with a review, architecture; also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters — these two take Sol even when the task is closed. Measured: Sol falsified bad hypotheses from live data and had 0 printed-tool-call failures versus 9 on Opus. Closed work goes to the `worker` role, never to `full-cycle`: phases and gates buy nothing on a task that is already specified, and raising effort bought nothing either — on the two closed tasks measured it cost ×2.04 and ×1.13 without changing the verdict.
 - **Spark** (`gpt-5.3-codex-spark`) — closed task on its OWN pool: take it over Luna when the Codex pool is the binding constraint AND all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Same escalation as Luna, plus: the ticket needs a file outside the ones you named → Sol. NOT for research, architecture, vision, security.
 - **Orchestrators** — always Opus 5.
 </model-routing>
### 7ba8728be #213: #213: record per-model effort constraint, no discount route through Sol

diff --git a/docs/workers/prompt-engineer.md b/docs/workers/prompt-engineer.md
index 6d93e001e..2f97020e8 100644
--- a/docs/workers/prompt-engineer.md
+++ b/docs/workers/prompt-engineer.md
@@ -191,10 +191,17 @@ DONE WHEN: наблюдаемое условие завершения.
   `worker` `high`, `full-cycle` `xhigh` (строки 23/39/55/71). Прежде чем писать «не ставь X»,
   проверь, есть ли у адресата рычаг: иначе это инструкция, которую некому выполнить (#203).
 - **`base.md` платят ВСЕ роли, а спавнить умеют не все.** `<model-routing>` живёт в `base.md`, но
   `worker` (`can_spawn: []`) действовать по нему не может, а это 75 сессий из 121 (62%, #203).
   Прежде чем расширять общий слой, спроси: этот текст кому-то из читателей вообще исполним?
+- **«Развести по рантайму» ≠ «развести по модели»: `backend_for_model` склеивает Sol, Luna, Terra
+  и Spark в один `codex`** (`app/models.py:623`). Прежде чем проектировать ключ конфига под
+  «разные рантаймы», прогони маппинг: в #213 целевые значения различались ВНУТРИ одного рантайма,
+  и правка по букве задания не сделала бы ничего.
+- **Числа из постановки проверять по первоисточнику, даже когда переносишь их дословно.**
+  «5.0/5.0» из задания в #208 оказалось «5.0 из 6.0 у обоих» — в промпте это читалось бы как
+  безупречный результат. Проверка стоила одной команды `sed` по `research.md`.
 - **Не цитируй в промпте значения, живущие в манифесте** (эффорт, модель, пул). Скобка
   «`never to full-cycle (xhigh)`», написанная мной в #203, стала ложной в #207 — через сутки, тем
   же диффом, которым меняли манифест. Ссылайся на смысл роли, а не на её настройку. То же и с
   эффортом сессии: манифест читается ТОЛЬКО при спавне (`app/manager.py:660`), при восстановлении
   берётся строка БД (`:1202`, `:1518`) — живые сессии старое значение сохраняют.
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index b2029c09f..28fbf8537 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -12,10 +12,18 @@ defaults:
   worktree:
     symlinks: []
     copies:   [CLAUDE.md, .mcp.json, .env, .worktreeinclude]
   base_branch_strategy: main
   docs_scaffold: false
+# Про `effort` у РАБОЧИХ ролей (`worker`, `full-cycle`), #213. Оркестраторских `medium` ниже это
+# не касается: их эффорт этой правкой не рассматривался (#208 Q2 — отдельной аномалии у них нет).
+# Поле скалярное, одно на роль, а модель роли переопределяется при спавне — поэтому `high` у
+# рабочих ролей верен для их дефолтного Opus и НЕ подходит остальным. Замер #208: перегиб отдачи
+# у Opus на `high` (дальше +1.0 пункта за +47% цены), у Sol перегиба в пределах лестницы нет
+# (+1.7/+1.7/+1.9) — ему нужен `xhigh`, у Luna хватает `high`. Развести нельзя ни здесь, ни по
+# рантайму: Sol и Luna — оба `codex` (`backend_for_model`), ключом должна быть МОДЕЛЬ.
+# Ждёт правки в коде; до неё Sol-воркеры недополучают ступень. Это запись ограничения, не задание.
 roles:
   orchestrator:
     kind: orchestrator
     label: Orchestrator
     order: 0
diff --git a/pipelines/default/prompts/modules/model-routing.md b/pipelines/default/prompts/modules/model-routing.md
index 768655d90..66dba3872 100644
--- a/pipelines/default/prompts/modules/model-routing.md
+++ b/pipelines/default/prompts/modules/model-routing.md
@@ -2,10 +2,10 @@
 ## Model routing — which model to pass to `spawn_worker`
 Pick deterministically by task class and current quota runway. Quota is a first-order routing
 factor: protect whichever weekly pool will exhaust first; route tasks suitable for either model
 to the healthier pool. If current telemetry is unavailable, use the manifest default.
 - **Opus 5** (`claude-opus-5[1m]`) — DEFAULT for OPEN work: implementation with unknowns, fixes, review, general multi-step work; strongest for ambiguity/dialogue, reading between the lines, creative prose, images, and 1M-context synthesis. A closed task goes to Luna instead.
-- **Luna** (`gpt-5.6-luna`) — CLOSED task, ahead of the Opus default: before spawning you can name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is open, route it above. Measured on 3 closed single-turn tasks (N=1 per cell): same work as Sol, 20.5× cheaper. **On failure escalate, never retry: the named test command stays red, or an acceptance criterion is not shown met by the output of a command → hand that ticket to Sol, do not send it back to Luna.** A criterion nobody can check by running something is not an AC, and its task was never closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at Sol's price. Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at 164K). Resolving references across similar fragments we have never measured → that one goes to Sol. This is caution, not a known cliff: the third-party number once quoted here failed attribution, and an independent long-context benchmark shows no gap at any working effort.
-- **Sol medium** (`gpt-5.6-sol`) — OPEN task on the Codex pool: research, arguing with a review, architecture; also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters — these two take Sol even when the task is closed. Measured: Sol falsified bad hypotheses from live data and had 0 printed-tool-call failures versus 9 on Opus. Closed work goes to the `worker` role, never to `full-cycle`: phases and gates buy nothing on a task that is already specified, and raising effort bought nothing either — on the two closed tasks measured it cost ×2.04 and ×1.13 without changing the verdict.
+- **Luna** (`gpt-5.6-luna`) — CLOSED task, ahead of the Opus default: before spawning you can name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is open, route it above. Measured: on 3 closed single-turn tasks (N=1 per cell) it did the same work as Sol at 20.5× less (#199), and on one real bug both scored 5.0 of 6.0 against pre-registered checks, Luna at 13.2× less (#208). One closed ticket at a time — long multi-turn work on Luna we have never measured, so do not stretch a ticket into a session there. **On failure escalate, never retry: the named test command stays red, or an acceptance criterion is not shown met by the output of a command → hand that ticket to Sol, do not send it back to Luna.** A criterion nobody can check by running something is not an AC, and its task was never closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at Sol's price. Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at 164K). Resolving references across similar fragments we have never measured → that one goes to Sol. This is caution, not a known cliff: the third-party number once quoted here failed attribution, and an independent long-context benchmark shows no gap at any working effort.
+- **Sol medium** (`gpt-5.6-sol`) — OPEN task on the Codex pool: research, arguing with a review, architecture; also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters — these two take Sol even when the task is closed. Measured: Sol falsified bad hypotheses from live data and had 0 printed-tool-call failures versus 9 on Opus. **There is no discount route through Sol**: its returns keep climbing to the top of the effort ladder with no inflection (+1.7 / +1.7 / +1.9 index points per step, #208), so cheapness is not available here at all — a task you would only fund at a discount goes to Luna, not to Sol. Closed work goes to the `worker` role, never to `full-cycle`: phases and gates buy nothing on a task that is already specified, and raising effort bought nothing either — on the two closed tasks measured it cost ×2.04 and ×1.13 without changing the verdict.
 - **Spark** (`gpt-5.3-codex-spark`) — closed task on its OWN pool: take it over Luna when the Codex pool is the binding constraint AND all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Same escalation as Luna, plus: the ticket needs a file outside the ones you named → Sol. NOT for research, architecture, vision, security.
 - **Orchestrators** — always Opus 5.
 </model-routing>
### 0a665a832 #210: #210: план Фазы 2 — план заканчивается красным тестом; оракул схемы закоммичен КРАСНЫМ

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 8138379ee..60ab94a37 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -440,5 +440,145 @@ class TestPremortemReachesWorkingRolesOnly:
         for role in self.ORCHESTRATOR_ROLES:
             out = P.build_system_prompt(PIPELINE, role)
             assert self.ANCHOR not in out, (
                 f"{role}: шаг исполнителя протёк в промпт оркестратора"
             )
+
+
+class TestOracleGate:
+    """#210: фаза плана заканчивается КРАСНЫМ тестом, а исполнитель не пишет себе оракул сам.
+
+    Форма проверки скопирована с `TestPremortemReachesWorkingRolesOnly` (#198) намеренно:
+    один способ решения одной задачи. Тройка «источник / доставка / не-утечка» и ловит
+    составную мутацию «шаг удалён из роли + слова посажены в base.md» — доставка её
+    переживает, источник и не-утечка нет.
+    """
+
+    # Шаг нарезки тикетов есть только у full-cycle: worker планов не режет.
+    PLAN_ANCHOR = "commit it FAILING"
+    PLAN_ROLES = ("full-cycle",)
+    # Контрправило нужно ОБЕИМ рабочим ролям: дешёвый исполнитель — это роль worker.
+    EXEC_ANCHOR = "Never author the acceptance test"
+    EXEC_ROLES = ("worker", "full-cycle")
+    ORCHESTRATOR_ROLES = ("orchestrator", "sub-orchestrator")
+
+    def _src(self, role: str) -> str:
+        return P.prompt_path(PIPELINE, f"roles/{role}.md").read_text(encoding="utf-8")
+
+    # ── источник ───────────────────────────────────────────────────────────
+    def test_plan_step_is_owned_by_the_full_cycle_file(self):
+        for role in self.PLAN_ROLES:
+            assert self.PLAN_ANCHOR in self._src(role), (
+                f"roles/{role}.md: шаг «план заканчивается красным тестом» должен жить в "
+                "файле САМОЙ роли, иначе он потеряется при перекомпоновке слоёв"
+            )
+
+    def test_executor_rule_is_owned_by_both_working_role_files(self):
+        for role in self.EXEC_ROLES:
+            assert self.EXEC_ANCHOR in self._src(role), (
+                f"roles/{role}.md: без этой строки исполнитель напишет оракул себе сам "
+                "(замер #210: 2 прогона из 2)"
+            )
+
+    # ── полнота шага: якоря берутся ИЗ ИСТОЧНИКА, а не выписаны руками (#203) ──
+    def test_every_clause_of_the_plan_step_survives_assembly(self):
+        src = self._src("full-cycle")
+        start = src.find(self.PLAN_ANCHOR)
+        assert start != -1, "шага нет в roles/full-cycle.md — проверять нечего"
+        block_start = src.rfind("\n3. ", 0, start)
+        block_end = src.find("\n4. ", start)
+        assert block_start != -1 and block_end != -1, (
+            "блок шага не ограничен соседними пунктами 3 и 4 — нумерация фазы 2 разъехалась"
+        )
+        clauses = [ln.strip() for ln in src[block_start:block_end].splitlines() if ln.strip()]
+        assert len(clauses) >= 8, f"блок подозрительно короткий: {len(clauses)} строк"
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        for clause in clauses:
+            assert clause in out, f"пункт шага не доехал до собранного промпта: {clause[:70]!r}"
+
+    def test_ticket_template_carries_the_test_field_and_a_REASONED_none_marker(self):
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        assert "- Test: <path>::<test name> — committed RED in <commit>" in out, (
+            "шаблон тикета обязан называть поле Test целиком, вместе с требованием RED"
+        )
+        # Метка проверяется В САМОМ ШАБЛОНЕ, а не «где-то в промпте»: ассерт на голую строку
+        # проходил бы, пока причина упомянута в соседнем абзаце, а шаблон показывал бы
+        # безпричинную форму — её агент и скопирует (blocking раунда 2 Codex-ревью плана).
+        assert "| oracle: none — <why" in out, (
+            "шаблон обязан показывать метку ТОЛЬКО с причиной; голая `oracle: none` — "
+            "невалидный тикет и в шаблоне встречаться не должна"
+        )
+
+    def test_phase_3_selects_the_ticket_before_it_implements(self):
+        """Шаг 1 фазы 3 обязан ВЫБИРАТЬ тикет, а не начинать реализацию: иначе буквальный
+        исполнитель начнёт править код на шаге 1 и дойдёт до гейта уже после
+        (blocking Codex-ревью реализации). Порядок шагов и есть здесь предохранитель."""
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        assert "implementation starts only after step 2 passes" in out, (
+            "шаг 1 фазы 3 обязан явно откладывать реализацию до прохождения гейта"
+        )
+
+    def test_own_phase_2_test_may_not_be_weakened(self):
+        """Клауза без якоря удаляется молча: до этого теста её можно было вырезать, и все
+        девять оставались зелёными (blocking Codex-ревью реализации). Опаснее прочего именно
+        она — это единственный запрет подгонять СВОЙ красный тест под написанный код."""
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        assert "never weaken it to fit the code you wrote" in out, (
+            "запрет ослаблять собственный тест фазы 2 обязан быть в промпте full-cycle"
+        )
+        assert "never weaken it to fit the code you wrote" not in P.build_system_prompt(
+            PIPELINE, "worker"
+        ), "клауза про СВОЙ тест фазы 2 относится только к full-cycle: worker планов не пишет"
+
+    def test_phase_3_names_the_only_exception_for_oracle_none(self):
+        """Без исключения шаг «увидеть красным ДО правки» делает тикеты `oracle: none`
+        невыполнимыми: команды у них нет, значит «missing» → вечный STOP
+        (blocking раунда 2 Codex-ревью плана)."""
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        assert "The only exception:" in out and "verify it against its AC by hand" in out, (
+            "фаза 3 обязана назвать единственное исключение для `oracle: none`"
+        )
+
+    def test_the_step_has_teeth_in_phase_3_and_in_the_codex_gate(self):
+        """Потребители шага обязаны быть В ТЕКСТЕ РОЛИ, а не в прозе плана.
+
+        Без этих двух строк исполнителю достаточно один раз запустить финальную зелёную
+        команду, и он формально соблюдёт правило — красный артефакт станет церемонией
+        (blocking раунда 1 Codex-ревью плана)."""
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        assert "see it red before you change" in out, (
+            "фаза 3 обязана требовать увидеть тест красным ДО правки"
+        )
+        assert "already green at review time is a blocking finding" in out, (
+            "Codex-ревью плана обязано ревьюить сам тест, иначе у шага нет проверяющего"
+        )
+
+    def test_plan_ready_report_quotes_the_failing_run(self):
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        assert "→ exit 1:" in out, (
+            "отчёт PLAN READY обязан цитировать ненулевой exit и падающую строку — "
+            "это потребитель шага, без него он станет ритуалом"
+        )
+
+    # ── доставка ───────────────────────────────────────────────────────────
+    def test_working_roles_receive_their_anchors(self):
+        for role in self.PLAN_ROLES:
+            assert self.PLAN_ANCHOR in P.build_system_prompt(PIPELINE, role), (
+                f"{role}: наличия строки в roles/*.md недостаточно, шаг обязан доехать "
+                "до СОБРАННОГО промпта"
+            )
+        for role in self.EXEC_ROLES:
+            assert self.EXEC_ANCHOR in P.build_system_prompt(PIPELINE, role), (
+                f"{role}: контрправило не доехало до собранного промпта"
+            )
+
+    # ── не-утечка (она же ловушка на составную мутацию) ────────────────────
+    def test_orchestrator_roles_receive_neither(self):
+        for role in self.ORCHESTRATOR_ROLES:
+            out = P.build_system_prompt(PIPELINE, role)
+            assert self.PLAN_ANCHOR not in out, (
+                f"{role}: шаг исполнителя протёк в промпт оркестратора — либо утечка, "
+                "либо слова посажены в общий слой вместо роли"
+            )
+            assert self.EXEC_ANCHOR not in out, (
### 6b2249c59 #214: #214: эффорт по модели — карта модель→ступень в манифесте

diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 28fbf8537..cb4472c66 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -12,25 +12,35 @@ defaults:
   worktree:
     symlinks: []
     copies:   [CLAUDE.md, .mcp.json, .env, .worktreeinclude]
   base_branch_strategy: main
   docs_scaffold: false
-# Про `effort` у РАБОЧИХ ролей (`worker`, `full-cycle`), #213. Оркестраторских `medium` ниже это
-# не касается: их эффорт этой правкой не рассматривался (#208 Q2 — отдельной аномалии у них нет).
-# Поле скалярное, одно на роль, а модель роли переопределяется при спавне — поэтому `high` у
-# рабочих ролей верен для их дефолтного Opus и НЕ подходит остальным. Замер #208: перегиб отдачи
-# у Opus на `high` (дальше +1.0 пункта за +47% цены), у Sol перегиба в пределах лестницы нет
-# (+1.7/+1.7/+1.9) — ему нужен `xhigh`, у Luna хватает `high`. Развести нельзя ни здесь, ни по
-# рантайму: Sol и Luna — оба `codex` (`backend_for_model`), ключом должна быть МОДЕЛЬ.
-# Ждёт правки в коде; до неё Sol-воркеры недополучают ступень. Это запись ограничения, не задание.
+# `effort` у ВСЕХ четырёх ролей задан одной и той же КАРТОЙ модель→ступень (#214): роль одна, а
+# модель выбирается при спавне, и оптимум у моделей разный. Ключом обязана быть МОДЕЛЬ, а не
+# рантайм: Sol и Luna оба `codex` (`backend_for_model`) и требуют разных ступеней.
+# Разрешение (`pipeline.resolve_effort`): точный id модели → рантайм → `default` → нет эффорта.
+# Скаляр остаётся валидным — просто здесь он больше не используется.
+# Оркестраторы подняты с `medium` до `high` по прямому указанию юзера (#214): #208 меряло только
+# рабочие роли, но medium→high — САМЫЙ крупный шаг лестницы Opus (+2.9 пункта), и переносить его
+# на оркестраторов дешевле, чем оставлять их на ступени, выбранной до этого замера. Откат — правка
+# одного ключа `claude-opus-5[1m]` в двух ролях ниже; живые агенты подхватят её на следующем ходе.
+# Основания значений:
+#   claude-opus-5[1m] → high  — #208: перегиб отдачи на `high` (medium→high +2.9, дальше high→xhigh
+#                               всего +1.0 пункта при +47% цены)
+#   gpt-5.6-sol       → xhigh — #208: перегиба в пределах лестницы НЕТ, +1.7/+1.7/+1.9 на каждый шаг;
+#                               дешёвого оптимума у Sol не существует, ступень честно окупается
+#   gpt-5.6-luna      → high  — #204, AA-LCR low 0.653 / medium 0.720 / high 0.740 / xhigh 0.733 /
+#                               max 0.783: `high` и `xhigh` неразличимы, `max` даёт +2 пункта за
+#                               +45% цены. Колено на `high`
+#   default           → high  — остальные модели (Spark, Terra, Grok) не мерились
 roles:
   orchestrator:
     kind: orchestrator
     label: Orchestrator
     order: 0
     model: claude-opus-5[1m]
-    effort: medium
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, vps-deploy, codex-debate, grill-me, orchestra-agents]
     modules: [model-routing, git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "👑"}
@@ -42,11 +52,11 @@ roles:
   sub-orchestrator:
     kind: orchestrator
     label: Sub-Orchestrator
     order: 1
     model: claude-opus-5[1m]
-    effort: medium
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [orchestra-agents]
     modules: [model-routing, git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "🎯"}
@@ -58,11 +68,11 @@ roles:
   worker:
     kind: worker
     label: Worker
     order: 2
     model: claude-opus-5[1m]
-    effort: high
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, codex-debate]
     modules: [git-workflow, report-format, self-improvement, memory-search]
     can_spawn: []
     allow_unrouted_workers: false
     tg: {emoji: "⚙️"}
@@ -79,12 +89,13 @@ roles:
     # xhigh → high (#207). Anthropic для Opus 5 велит начинать с high и НЕ переносить настройки
     # прошлого поколения — унаследованный xhigh оттуда и пришёл; на девяти чужих бенчмарках
     # high→xhigh даёт +47% цены без значимого прироста, наш #199 на Sol — ×2.04 при том же вердикте.
     # НЕ ЗАКРЫТО: вендор оправдывает xhigh длиной горизонта задачи, а все опубликованные замеры
     # короче наших сессий. Правка обратимая и наблюдаемая: пошли разваливающиеся длинные ходы →
-    # вернуть xhigh, и это будет данными, а не спором.
-    effort: high
+    # вернуть xhigh, и это будет данными, а не спором. Относится к ключу Opus; у Sol ступень
+    # своя (#214, основания — в комментарии над `roles:`).
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, codex-debate]
     modules: [model-routing, research-method, git-workflow, worker-lifecycle, report-format, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: false
     tg: {emoji: "🔄"}
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 60ab94a37..5d452247d 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -117,10 +117,29 @@ class TestDefaultRolesResolve:
         assert rr.is_orchestrator is True
         assert rr.model == "claude-opus-5[1m]"
         assert rr.can_spawn == ["*"]
         assert rr.allow_unrouted_workers is True
 
+    @pytest.mark.parametrize(
+        "role", ["worker", "full-cycle", "orchestrator", "sub-orchestrator"])
+    @pytest.mark.parametrize("model,runtime,expected", [
+        ("claude-opus-5[1m]", "claude", "high"),    # #208: перегиб отдачи на high
+        ("gpt-5.6-sol", "codex", "xhigh"),          # #208: перегиба в лестнице нет
+        ("gpt-5.6-luna", "codex", "high"),          # #204: колено на high
+        ("gpt-5.3-codex-spark", "codex", "high"),   # не мерился → default
+    ])
+    def test_every_role_resolves_effort_by_model(self, role, model, runtime, expected):
+        """Все четыре роли — одна карта. Оркестраторы подняты medium→high (#214)."""
+        rr = P.get_role(PIPELINE, role)
+        assert P.resolve_effort(rr.effort, model, runtime) == expected
+
+    def test_no_role_is_left_on_a_scalar_effort(self):
+        """Скаляр остаётся ВАЛИДНЫМ (тесты в test_pipeline.py), но в дефолтном
+        манифесте его больше нет — иначе роль снова обслуживала бы одну модель."""
+        for role in P.known_roles(PIPELINE):
+            assert isinstance(P.get_role(PIPELINE, role).effort, dict), role
+
     def test_modules_resolve_from_manifest(self):
         """modules пробрасываются из манифеста в ResolvedRole без слияния с defaults."""
         assert P.get_role(PIPELINE, "orchestrator").modules == [
             "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
             "background-jobs", "task-management", "self-improvement", "memory-search",
### 100cc871b #221: #221: add Telegram formatting rules to orchestrator prompt

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 5d452247d..1ab4ac075 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -280,10 +280,44 @@ class TestDefaultBuildSystemPrompt:
         out = P.build_system_prompt(PIPELINE, "orchestrator")
         assert "## Role: Worker" not in out
         assert "## Role: Full-Cycle Worker" not in out
 
 
+class TestTelegramFormattingOwnership:
+    """#221: Telegram presentation rules belong only to the user-facing role."""
+
+    OPEN = "<telegram-formatting>"
+    CLOSE = "</telegram-formatting>"
+    USER_ROLE = "orchestrator"
+    OTHER_ROLES = ("sub-orchestrator", "worker", "full-cycle")
+
+    def _source_block(self) -> tuple[str, list[str]]:
+        source = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text(encoding="utf-8")
+        start = source.find(self.OPEN)
+        end = source.find(self.CLOSE, start)
+        assert start != -1 and end != -1, "Telegram formatting section is missing from its owner"
+        block = source[start:end + len(self.CLOSE)]
+        clauses = [line.strip() for line in block.splitlines() if line.strip()]
+        assert len(clauses) >= 10, "Telegram formatting section is unexpectedly short"
+        return block, clauses
+
+    def test_every_source_clause_reaches_the_assembled_user_prompt(self):
+        """The source file, not hand-written test phrases, supplies the delivery anchors."""
+        _block, clauses = self._source_block()
+        assembled = P.build_system_prompt(PIPELINE, self.USER_ROLE)
+        for clause in clauses:
+            assert clause in assembled, f"Telegram formatting clause did not assemble: {clause!r}"
+
+    def test_telegram_formatting_does_not_leak_to_non_user_roles(self):
+        block, _clauses = self._source_block()
+        assert self.OPEN in P.build_system_prompt(PIPELINE, self.USER_ROLE)
+        for role in self.OTHER_ROLES:
+            assembled = P.build_system_prompt(PIPELINE, role)
+            assert self.OPEN not in assembled, f"Telegram rules leaked into {role}"
+            assert block not in assembled, f"Telegram rules leaked into {role}"
+
+
 # ── modules: инлайн переиспользуемых блоков после слоёв роли ────────────────
 
 class TestDefaultModulesInline:
     GIT_MARKER = "Each worker runs in an isolated"
     ORCH_MARKER = "## Role: Orchestrator"
### 9442bc38b #221: #221: add model routing priority oracle

diff --git a/pipelines/default/prompts/modules/model-routing.md b/pipelines/default/prompts/modules/model-routing.md
index 66dba3872..020593476 100644
--- a/pipelines/default/prompts/modules/model-routing.md
+++ b/pipelines/default/prompts/modules/model-routing.md
@@ -1,11 +1,17 @@
 <model-routing>
 ## Model routing — which model to pass to `spawn_worker`
-Pick deterministically by task class and current quota runway. Quota is a first-order routing
-factor: protect whichever weekly pool will exhaust first; route tasks suitable for either model
-to the healthier pool. If current telemetry is unavailable, use the manifest default.
-- **Opus 5** (`claude-opus-5[1m]`) — DEFAULT for OPEN work: implementation with unknowns, fixes, review, general multi-step work; strongest for ambiguity/dialogue, reading between the lines, creative prose, images, and 1M-context synthesis. A closed task goes to Luna instead.
-- **Luna** (`gpt-5.6-luna`) — CLOSED task, ahead of the Opus default: before spawning you can name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is open, route it above. Measured: on 3 closed single-turn tasks (N=1 per cell) it did the same work as Sol at 20.5× less (#199), and on one real bug both scored 5.0 of 6.0 against pre-registered checks, Luna at 13.2× less (#208). One closed ticket at a time — long multi-turn work on Luna we have never measured, so do not stretch a ticket into a session there. **On failure escalate, never retry: the named test command stays red, or an acceptance criterion is not shown met by the output of a command → hand that ticket to Sol, do not send it back to Luna.** A criterion nobody can check by running something is not an AC, and its task was never closed. A second Luna pass on the same failure is what turns a 20× saving into three rounds at Sol's price. Long context ONLY for EXTRACTION — finding explicitly marked places in a big input (9/9 at 164K). Resolving references across similar fragments we have never measured → that one goes to Sol. This is caution, not a known cliff: the third-party number once quoted here failed attribution, and an independent long-context benchmark shows no gap at any working effort.
-- **Sol medium** (`gpt-5.6-sol`) — OPEN task on the Codex pool: research, arguing with a review, architecture; also empirical measurements/benchmarks and long mechanical protocols or bulk edits where exact tool execution matters — these two take Sol even when the task is closed. Measured: Sol falsified bad hypotheses from live data and had 0 printed-tool-call failures versus 9 on Opus. **There is no discount route through Sol**: its returns keep climbing to the top of the effort ladder with no inflection (+1.7 / +1.7 / +1.9 index points per step, #208), so cheapness is not available here at all — a task you would only fund at a discount goes to Luna, not to Sol. Closed work goes to the `worker` role, never to `full-cycle`: phases and gates buy nothing on a task that is already specified, and raising effort bought nothing either — on the two closed tasks measured it cost ×2.04 and ×1.13 without changing the verdict.
-- **Spark** (`gpt-5.3-codex-spark`) — closed task on its OWN pool: take it over Luna when the Codex pool is the binding constraint AND all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Same escalation as Luna, plus: the ticket needs a file outside the ones you named → Sol. NOT for research, architecture, vision, security.
-- **Orchestrators** — always Opus 5.
+Choose in this order; quota arithmetic must not reverse the priority. **Luna is the DEFAULT**: use
+it for everything that is not covered by the Sol or Opus exceptions below. **Sol when the task is complex and Luna will not manage it**: complexity and Luna's expected inability are both required.
+**Opus only for special complex tasks** in normal routing. If the Codex pool is exhausted, falling
+back to Opus is the operational exception that keeps work moving.
+
+This policy is driven by the asymmetry of consequences, not by price. **the Codex pool is meant to be burned** deliberately and to exhaustion: hitting Claude's weekly limit is painful because work stops, while hitting Codex is tolerable because we can fall back to Opus and continue. The calculation that a dollar of Codex consumes 4.8× more of its own pool than a dollar of Claude ($5.39 versus $25.67 per percentage point) is correct, but it does not imply moving work to Claude: it compares the **cost of exhaustion, not the cost of spend**. Reconsider this policy only with evidence about consequences, never with arithmetic about spend price.
+
+- **Luna** (`gpt-5.6-luna`) — default for all work and the required choice for a CLOSED task. Before spawning, you must be able to name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is not closed. **On failure escalate, never retry:** if the named test command stays red or a criterion is not shown met by command output, hand the ticket to Sol and do not send it back to Luna. One closed ticket at a time; do not stretch it into a long multi-turn session. Long context ONLY for EXTRACTION — finding explicitly marked places in a large input. Resolving references across similar fragments goes to Sol.
+- **Sol medium** (`gpt-5.6-sol`) — use only for a complex task that Luna will not manage: research, arguing with a review, architecture, empirical measurements/benchmarks, or long mechanical protocols and bulk edits where exact tool execution matters. A closed task that meets the Luna definition remains with Luna unless this complexity exception applies. Closed work goes to the `worker` role, never to `full-cycle`.
+- **Opus 5** (`claude-opus-5[1m]`) — use only for special complex tasks, or as the fallback after Codex exhaustion described above. It is the specialist for exceptional ambiguity, creative prose, images, or unusually demanding synthesis; it is not the default worker route.
+- **Spark** (`gpt-5.3-codex-spark`) — optional narrow leaf route only when the Codex pool is the binding constraint and all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Spark never takes review work. It is not for research, architecture, vision, or security; a ticket needing a file outside the named ones goes to Sol.
+- **Terra** — do not use.
+- **Fable** — do not use.
+- **Orchestrators** — when selecting a worker, apply the same priority above; the orchestrator role does not override it.
 </model-routing>
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 1ab4ac075..6fa8aebd8 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -633,5 +633,39 @@ class TestOracleGate:
                 "либо слова посажены в общий слой вместо роли"
             )
             assert self.EXEC_ANCHOR not in out, (
                 f"{role}: контрправило исполнителя протекло в промпт оркестратора"
             )
+
+POOL_PRIORITY_ANCHORS = (
+    "Luna is the DEFAULT",
+    "Sol when the task is complex and Luna will not manage it",
+    "Opus only for special complex tasks",
+    "the Codex pool is meant to be burned",
+    "cost of exhaustion, not the cost of spend",
+)
+OBSOLETE_PRIORITY_ANCHOR = "— DEFAULT worker"
+
+
+def _roles_receiving_model_routing():
+    from app.pipeline import build_system_prompt
+    roles = []
+    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
+        if "model-routing" in build_system_prompt("default", role) or "Spark" in build_system_prompt("default", role):
+            roles.append(role)
+    assert roles, "ни одна роль не получает model-routing — проверка выродилась"
+    return roles
+
+
+def test_pool_priority_rule_reaches_roles_that_receive_model_routing():
+    from app.pipeline import build_system_prompt
+    for role in _roles_receiving_model_routing():
+        out = build_system_prompt("default", role)
+        for anchor in POOL_PRIORITY_ANCHORS:
+            assert anchor in out, f"{role}: нет якоря {anchor!r}"
+
+
+def test_obsolete_priority_formulation_is_gone_everywhere():
+    from app.pipeline import build_system_prompt
+    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
+        out = build_system_prompt("default", role)
+        assert OBSOLETE_PRIORITY_ANCHOR not in out, f"{role}: осталась старая формулировка приоритета"
### 45d761005 #223: #223: correct barrier conclusion

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 6fa8aebd8..f69034f49 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -634,10 +634,125 @@ class TestOracleGate:
             )
             assert self.EXEC_ANCHOR not in out, (
                 f"{role}: контрправило исполнителя протекло в промпт оркестратора"
             )
 
+class TestTicketDelegationGate:
+    """#223: закрытый тикет уходит исполнителю, а оракул остаётся у full-cycle."""
+
+    IMMUTABLE_ANCHOR = (
+        "The received acceptance test is immutable: NEVER edit, delete, rename, skip, "
+        "xfail, or weaken it."
+    )
+    WORKER_FAILURE_ANCHOR = (
+        "If the command cannot be made green without changing that test, report `WIP/STOP`; "
+        "do not replace it or create a different check."
+    )
+    TEST_INFRA_ANCHOR = (
+        "Do not modify any test, fixture, test helper, `conftest.py`, test configuration, "
+        "marker, or test-selection setting; if the implementation requires one, report "
+        "`WIP/STOP`."
+    )
+    FULL_CYCLE_ANCHORS = (
+        "Only a ticket with a reviewed, committed RED command that just failed for the "
+        "missing behavior is delegable.",
+        "A ticket marked `oracle: none` is NEVER delegated; implement it yourself on the "
+        "expensive side.",
+        "Send `Files`, `Test`, `AC`, `blocked-by`, the RED commit, the exact command, its "
+        "non-zero exit and failing assertion, plus these sentences verbatim:",
+        "The worker sends exactly one message: its terminal `DONE` report, or one terminal "
+        "exception report instead.",
+        "The terminal report contains the executor commit, the exact test command and output, "
+        "and evidence for every remaining AC.",
+        "Before merge, compare every oracle path byte-for-byte with the RED commit.",
+        "Reject any executor diff that changes a test, fixture, test helper, `conftest.py`, "
+        "test configuration, marker, or test-selection setting relative to the RED commit.",
+        "A clarification request, a `WIP/STOP` report, or any oracle mutation is a failed "
+        "executor attempt.",
+        "Luna gets exactly one attempt.",
+        "On failure, send the same unchanged ticket once to a Sol `worker`; do not answer "
+        "Luna's question, rewrite its oracle, or return the ticket to Luna.",
+        "A Sol `worker` gets exactly one attempt.",
+        "If the premise, scope, Test, or AC must change, take it back immediately and re-close "
+        "it before any future delegation.",
+        "A child's green report is evidence, not acceptance. Merge only a clean committed "
+        "result, then rerun the exact command and the ticket's focused regression check "
+        "yourself.",
+        "Independent tickets whose files and lines do not overlap may run concurrently; "
+        "serialize only dependency chains and overlapping changes.",
+        "Never split one implementation ticket across agents.",
+    )
+    ORCHESTRATOR_ROLES = ("orchestrator", "sub-orchestrator")
+
+    def _src(self, role: str) -> str:
+        return P.prompt_path(PIPELINE, f"roles/{role}.md").read_text(encoding="utf-8")
+
+    def test_t1_delegation_full_cycle_source_owns_the_complete_contract(self):
+        src = self._src("full-cycle")
+        missing = [anchor for anchor in self.FULL_CYCLE_ANCHORS if anchor not in src]
+        assert not missing, f"roles/full-cycle.md is missing delegation clauses: {missing}"
+
+    def test_t1_delegation_immutable_rule_is_owned_by_both_sources(self):
+        for role in ("full-cycle", "worker"):
+            assert self.IMMUTABLE_ANCHOR in self._src(role), (
+                f"roles/{role}.md must own the immutable-oracle rule"
+            )
+            assert self.TEST_INFRA_ANCHOR in self._src(role), (
+                f"roles/{role}.md must own the oracle-infrastructure rule"
+            )
+        assert self.WORKER_FAILURE_ANCHOR in self._src("worker"), (
+            "roles/worker.md must turn an oracle-dependent implementation into WIP/STOP"
+        )
+
+    def test_t1_delegation_contract_reaches_working_roles(self):
+        full_cycle = P.build_system_prompt(PIPELINE, "full-cycle")
+        for anchor in (
+            *self.FULL_CYCLE_ANCHORS,
+            self.IMMUTABLE_ANCHOR,
+            self.TEST_INFRA_ANCHOR,
+        ):
+            assert anchor in full_cycle, f"full-cycle prompt lost clause: {anchor!r}"
+        assert self.IMMUTABLE_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
+            "worker prompt lost the immutable-oracle rule"
+        )
+        assert self.WORKER_FAILURE_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
+            "worker prompt lost the WIP/STOP consequence of oracle immutability"
+        )
+        assert self.TEST_INFRA_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
+            "worker prompt lost the oracle-infrastructure rule"
+        )
+
+    def test_t1_delegation_does_not_leak_into_orchestrators(self):
+        anchors = (
+            *self.FULL_CYCLE_ANCHORS,
+            self.IMMUTABLE_ANCHOR,
+            self.WORKER_FAILURE_ANCHOR,
+            self.TEST_INFRA_ANCHOR,
+        )
+        for role in self.ORCHESTRATOR_ROLES:
+            out = P.build_system_prompt(PIPELINE, role)
+            leaked = [anchor for anchor in anchors if anchor in out]
+            assert not leaked, f"{role} received executor-only delegation clauses: {leaked}"
+
+    def test_t1_delegation_worker_does_not_receive_parent_policy(self):
+        out = P.build_system_prompt(PIPELINE, "worker")
+        leaked = [anchor for anchor in self.FULL_CYCLE_ANCHORS if anchor in out]
+        assert not leaked, f"worker received parent-only routing policy: {leaked}"
+        assert self.WORKER_FAILURE_ANCHOR not in P.build_system_prompt(
+            PIPELINE, "full-cycle"
+        ), "full-cycle received the worker-only WIP/STOP instruction"
+
+    def test_t1_delegation_gate_precedes_implementation_work(self):
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        phase_3 = out.find("### Phase 3: IMPLEMENT")
+        gate = out.find(self.FULL_CYCLE_ANCHORS[0], phase_3)
+        premortem = out.find("**Pre-mortem — what breaks for the next consumer.**", phase_3)
+        assert -1 not in (phase_3, gate, premortem) and phase_3 < gate < premortem, (
+            "the delegation gate must run after Phase 3 starts and before implementation work"
+        )
+
+
 POOL_PRIORITY_ANCHORS = (
     "Luna is the DEFAULT",
     "Sol when the task is complex and Luna will not manage it",
     "Opus only for special complex tasks",
     "the Codex pool is meant to be burned",
### bf5de05e2 #222: #222: add Spark admission delivery oracle

diff --git a/pipelines/default/prompts/modules/model-routing.md b/pipelines/default/prompts/modules/model-routing.md
index 020593476..f081944ea 100644
--- a/pipelines/default/prompts/modules/model-routing.md
+++ b/pipelines/default/prompts/modules/model-routing.md
@@ -8,10 +8,10 @@ back to Opus is the operational exception that keeps work moving.
 This policy is driven by the asymmetry of consequences, not by price. **the Codex pool is meant to be burned** deliberately and to exhaustion: hitting Claude's weekly limit is painful because work stops, while hitting Codex is tolerable because we can fall back to Opus and continue. The calculation that a dollar of Codex consumes 4.8× more of its own pool than a dollar of Claude ($5.39 versus $25.67 per percentage point) is correct, but it does not imply moving work to Claude: it compares the **cost of exhaustion, not the cost of spend**. Reconsider this policy only with evidence about consequences, never with arithmetic about spend price.
 
 - **Luna** (`gpt-5.6-luna`) — default for all work and the required choice for a CLOSED task. Before spawning, you must be able to name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is not closed. **On failure escalate, never retry:** if the named test command stays red or a criterion is not shown met by command output, hand the ticket to Sol and do not send it back to Luna. One closed ticket at a time; do not stretch it into a long multi-turn session. Long context ONLY for EXTRACTION — finding explicitly marked places in a large input. Resolving references across similar fragments goes to Sol.
 - **Sol medium** (`gpt-5.6-sol`) — use only for a complex task that Luna will not manage: research, arguing with a review, architecture, empirical measurements/benchmarks, or long mechanical protocols and bulk edits where exact tool execution matters. A closed task that meets the Luna definition remains with Luna unless this complexity exception applies. Closed work goes to the `worker` role, never to `full-cycle`.
 - **Opus 5** (`claude-opus-5[1m]`) — use only for special complex tasks, or as the fallback after Codex exhaustion described above. It is the specialist for exceptional ambiguity, creative prose, images, or unusually demanding synthesis; it is not the default worker route.
-- **Spark** (`gpt-5.3-codex-spark`) — optional narrow leaf route only when the Codex pool is the binding constraint and all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Spark never takes review work. It is not for research, architecture, vision, or security; a ticket needing a file outside the named ones goes to Sol.
+- **Spark** (`gpt-5.3-codex-spark`) — optional narrow fast/overflow leaf route with a separate but small quota wallet, not free capacity. At the current preview limit, #222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS). Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete. Use Spark only when the Codex pool is the binding constraint and all hold: text-only; ≤2 named files; ≤100K total initial context (system prompt + task + supplied files); every correctness-critical decision and value is explicit; an independent pre-existing oracle mechanically covers every correctness-critical criterion. Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route. At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption. The excluded classes are explicit: semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden. After any failed or incomplete Spark attempt, never retry Spark; hand the ticket to Luna or Sol by task class.
 - **Terra** — do not use.
 - **Fable** — do not use.
 - **Orchestrators** — when selecting a worker, apply the same priority above; the orchestrator role does not override it.
 </model-routing>
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index f69034f49..5ca7c7204 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -174,10 +174,40 @@ class TestDefaultRolesResolve:
         worker_out = P.build_system_prompt(PIPELINE, "worker")
         assert P.get_role(PIPELINE, "worker").can_spawn == []
         for anchor in ["<model-routing>", *bullets]:
             assert anchor not in worker_out, f"маршрутизация протекла воркеру: {anchor[:40]}"
 
+    def test_t1_spark_admission_rule_is_delivered_without_leaking(self):
+        anchors = (
+            "separate but small quota wallet, not free capacity",
+            "#222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS)",
+            "Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete",
+            "text-only; ≤2 named files",
+            "≤100K total initial context (system prompt + task + supplied files)",
+            "every correctness-critical decision and value is explicit",
+            "an independent pre-existing oracle mechanically covers every correctness-critical criterion",
+            "Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route",
+            "At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption",
+            "semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden",
+            "After any failed or incomplete Spark attempt, never retry Spark",
+        )
+        module = P.prompt_path(PIPELINE, "modules/model-routing.md").read_text()
+        spark_rules = [line for line in module.splitlines() if line.startswith("- **Spark**")]
+        assert len(spark_rules) == 1, "Spark admission must have exactly one owner rule"
+        spark_rule = spark_rules[0]
+        for anchor in anchors:
+            assert anchor in spark_rule, f"Spark admission rule lacks {anchor!r}"
+
+        for role in ("orchestrator", "sub-orchestrator", "full-cycle"):
+            out = P.build_system_prompt(PIPELINE, role)
+            for anchor in anchors:
+                assert out.count(anchor) == 1, f"{role}: Spark rule is missing or duplicated: {anchor!r}"
+
+        worker_out = P.build_system_prompt(PIPELINE, "worker")
+        for anchor in anchors:
+            assert anchor not in worker_out, f"Spark admission leaked to terminal worker: {anchor!r}"
+
     def test_tg_emoji_for_v216_roles(self):
         assert P.get_role(PIPELINE, "sub-orchestrator").tg.emoji == "🎯"
 
     def test_orchestrator_skills_from_manifest(self):
         rr = P.get_role(PIPELINE, "orchestrator")