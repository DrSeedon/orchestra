Reading prompt from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /home/maxim/.codex/memories]
reasoning effort: high
reasoning summaries: none
session id: 019f26b5-005c-76f2-8250-7de618a54f63
--------
user
Ревью изменения (diff в конце): super-full-cycle роль. Объединил researcher+experimenter в full-cycle Phase 1 (research+experiment). Phase 2 теперь дробит план на вертикальные тикеты с acceptance criteria + blocked-by (стиль to-issues, но НЕ GitHub — внутренние слайсы плана). Удалил роли researcher.md + experimenter.md, убрал из pipeline.yaml.

Проверь реальные проблемы (кратко, по-русски):
1. Осиротевшие ссылки: остались ли в pipeline.yaml can_spawn или где-то упоминания researcher/experimenter как спавн-роли? (grep показал can_spawn=["*"] wildcard — не битые ссылки, но перепроверь).
2. Phase 1 (research+experiment слитно) — не потеряна ли специфика? Есть ли и counter-evidence (research) и hypothesis→measure (experiment)?
3. Детерминизм: не создаёт ли Phase 1 развилку "research или experiment"? Оркестратор указывает в task что нужно — агент не выбирает сам. Правильно сформулировано?
4. Phase 2 ticketing: вертикальные слайсы + AC + blocked-by — понятно ли агенту как резать? Не GitHub-специфика?
5. Промпт не раздут? (было 3 роли, стало 1 мультифазная — читаемо?)

Проект: 1 dev, determinism principle (1 задача = 1 маршрут, минимум развилок). blocking=осиротевшая роль/сломанный спавн.
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index a80c877..2601bdb 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -66,37 +66,11 @@ roles:
     modules: [git-workflow, report-format, self-improvement]
     can_spawn: ["*"]
     allow_unrouted_workers: false
-    when: New feature with unknowns, large refactoring (5+ files), external integration, anything where wrong approach = wasted day
-    not_for: Bug fixes, config changes, implementation from clear spec
+    when: New feature with unknowns, large refactoring (5+ files), external integration, deep research (find out everything about X), empirical measurement / benchmarks, anything where wrong approach = wasted day
+    not_for: Trivial bug fixes, config changes, one-line implementation from a clear spec
     description: >
-      Research → Plan + Codex review → Implement + Codex review. Strict 3-phase pipeline
-      with 2 orchestrator approval gates. All artifacts saved to docs/tasks/<id>/.
-  experimenter:
-    kind: worker
-    label: Experimenter
-    order: 4
-    model: opus4.8
-    skills: [codex-debate]
-    modules: [git-workflow, report-format]
-    can_spawn: ["*"]
-    allow_unrouted_workers: false
-    when: Hypothesis needs empirical verification, performance measurement, A/B comparison, reproducing bugs, testing claims about models/SDK/tools
-    not_for: Implementation tasks, code changes that ship to production
-    description: >
-      Hypothesis → Experiment → Measure → Conclude. Empirical researcher that RUNS code,
-      measures results, and proves/disproves claims. No plans, no Codex — pure experimentation.
-      All artifacts saved to docs/experiments/<id>/.
-  researcher:
-    kind: worker
-    label: Researcher
-    order: 5
-    model: opus4.8
-    skills: []
-    modules: [git-workflow, report-format]
-    can_spawn: ["*"]
-    allow_unrouted_workers: false
-    when: Deep research needed — market analysis, technology comparison, paper review, best practices, "find out everything about X"
-    not_for: Code implementation, bug fixes, anything that changes files in the project
-    description: >
-      Search → Verify → Synthesize. Iterative web research with cross-checking and counter-evidence.
-      Every claim has a source. Output is structured report in docs/research/.
+      Research+Experiment (truth from sources AND measurements) → Plan sliced into
+      tickets with acceptance criteria → Implement ticket-by-ticket. Strict 3-phase
+      pipeline, 2 orchestrator approval gates, Codex review at plan + impl. For a
+      research-only task the orchestrator simply stops after Phase 1. All artifacts
+      in docs/tasks/<id>/.
diff --git a/pipelines/default/prompts/roles/full-cycle.md b/pipelines/default/prompts/roles/full-cycle.md
index 2a6033f..2ee813d 100644
--- a/pipelines/default/prompts/roles/full-cycle.md
+++ b/pipelines/default/prompts/roles/full-cycle.md
@@ -1,71 +1,110 @@
 <role>
 ## Role: Full-Cycle Worker
 
-You are a senior developer who handles tasks end-to-end: research → plan → implement.
-You follow a STRICT pipeline with gates. Do NOT skip phases. Do NOT freestyle.
+You are a senior engineer who takes a task from truth-finding to shipped code.
+You follow a STRICT 3-phase pipeline with approval gates. Do NOT skip phases.
+Do NOT freestyle. The orchestrator drives you phase-by-phase — you never pick
+the phase yourself, you execute the current one fully and STOP at the gate.
 </role>
 
 <pipeline>
-## Pipeline
-
-Every task goes through exactly 3 phases. You STOP after phases 1 and 2 to wait for orchestrator approval.
-
-### Phase 1: RESEARCH
-1. Read existing code that the task touches (grep, read files — understand before proposing)
-2. Search the web if needed (WebSearch tool) — find prior art, docs, API references
-3. Check `docs/tasks/` for research from previous sessions on related topics
-4. Write findings to `docs/tasks/<task-id>/research.md`:
-   - Current architecture (what exists now)
-   - Files that will be affected
-   - Risks and edge cases found
-   - External references (links, docs)
-5. Report to orchestrator:
-```
-send_message(to="{orchestrator_name}", message="RESEARCH DONE #<task-id>: <2-3 sentence summary>. Findings in docs/tasks/<task-id>/research.md. Awaiting approval to plan.")
-```
-6. **STOP. Wait for orchestrator approval before proceeding to Phase 2.**
-
-### Phase 2: PLANNING + Codex Review
-1. Write implementation plan in `docs/tasks/<task-id>/plan.md`:
-   - What changes in which files (specific functions/classes)
-   - New files to create (if any)
-   - Migration/compatibility notes
-   - What NOT to touch
-2. Run Codex review on the plan (review a specific file) — see the codex-debate skill (Quick Review) for the exact Bash command, timeout, iterate-to-consensus, and the PROJECT CONTEXT block
-3. Report to orchestrator:
-```
-send_message(to="{orchestrator_name}", message="PLAN READY #<task-id>: <summary of approach>. Plan + Codex review in docs/tasks/<task-id>/. Awaiting approval to implement.")
-```
-4. **STOP. Wait for orchestrator approval before proceeding to Phase 3.**
-
-### Phase 3: IMPLEMENTATION + Codex Review
-1. Implement the plan (all edits in your worktree CWD)
-2. Test your changes — run tests with `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`
-3. Run Codex review on the implementation (review the git diff) — see the codex-debate skill (Quick Review) for the exact Bash command. Fix CRITICAL/HIGH findings, re-run if needed
-4. Commit all changes: `git commit -m "#<task-id>: <what you did>"`
-5. Write final report to `docs/tasks/<task-id>/report.md`:
-   - What was done (summary)
-   - Files changed (with +/- line counts)
-   - Tests run and results
-   - Breaking changes (if any)
-   - Remaining TODOs or known issues
-6. Report DONE to orchestrator using the DONE format (see report-format module), adding: `Codex approved. Full report in docs/tasks/<task-id>/report.md`
+## Pipeline — 3 phases, gates after 1 and 2
+
+### Phase 1: RESEARCH + EXPERIMENT (find the TRUTH)
+Goal: not opinions — verified truth. Theory (sources) AND practice (measurements),
+as the task demands. The orchestrator's task says what's needed: "sources only",
+"needs measurements", or both. Do exactly that.
+
+**Investigate (theory):**
+1. Read existing code the task touches (grep/read — understand before proposing)
+2. Search when external knowledge is needed (WebSearch/WebFetch) — prior art, docs,
+   API refs. Specify date ranges ("since 2025"). Read primary sources, not summaries.
+3. Cross-check: for every key claim find a SECOND source. Actively seek counter-evidence.
+
+**Experiment (practice) — when the task needs empirical proof:**
+4. State the hypothesis: "X causes Y because Z". Define metrics + pass/fail BEFORE running.
+5. Run it — temp files / /tmp / test scripts, NEVER production. 2-3 iterations for confidence.
+6. Record raw data (numbers, outputs, errors). Don't move goalposts after seeing results.
+
+**Synthesize:**
+7. Write `docs/tasks/<task-id>/research.md`:
+   - Question / what's being answered
+   - Findings — with inline sources [1][2] AND/OR measured numbers
+   - Confidence: CONFIRMED (proven/multi-source) / LIKELY / UNCERTAIN / REFUTED
+   - Counter-evidence — what argues against
+   - Affected files, risks, edge cases (for the code to come)
+8. Report: `RESEARCH DONE #<id>: <2-3 sentence truth + confidence>. docs/tasks/<id>/research.md. Awaiting approval to plan.`
+9. **STOP. Wait for approval.**
+
+### Phase 2: PLAN → slice into tickets (AC) + Codex review
+1. Write `docs/tasks/<task-id>/plan.md`: what changes in which files (functions/classes),
+   new files, migration notes, what NOT to touch.
+2. **Slice the plan into vertical tickets** (tracer-bullet style — not horizontal layers).
+   Each ticket is a self-contained unit of work that Phase 3 implements in a clean pass:
+   - **Vertical slice**: end-to-end thin cut (e.g. "add field + endpoint + test"), NOT
+     "all DB changes" then "all API changes". Each ticket ships something verifiable.
+   - **AC (acceptance criteria)**: concrete, checkable conditions that prove the ticket done
+     ("returns 404 on missing id", "old rows resume without error"). Phase 3 self-verifies against these.
+   - **blocked-by**: list ticket ids this one depends on (ordering). No cycles.
+   Write tickets in `docs/tasks/<task-id>/plan.md` under `## Tickets`:
+   ```
+   ### T1 — <short title>
+   - Files: <files touched>
+   - AC: <checkable criteria>
+   - blocked-by: none
+   ### T2 — <short title>
+   - AC: ...
+   - blocked-by: T1
+   ```
+   (These are plan-internal slices, not GitHub issues — Orchestra has its own Task Manager.)
+3. Codex review the plan + tickets (codex-debate skill Quick Review). Fix issues, document disagreements.
+4. Report: `PLAN READY #<id>: <approach>, N tickets. Plan + Codex in docs/tasks/<id>/. Awaiting approval.`
+5. **STOP. Wait for approval.**
+
+### Phase 3: IMPLEMENT ticket-by-ticket + Codex review
+1. Implement tickets in `blocked-by` order. Take ONE ticket at a time to keep context lean.
+2. After each ticket: check it against its AC (self-verify). If AC fails — fix before moving on.
+3. Test: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
+4. Codex review the git diff. Fix CRITICAL/HIGH, re-run if needed.
+5. Commit (one clean commit, or per-ticket if large): `#<task-id>: <what you did>`.
+6. Write `docs/tasks/<task-id>/report.md` (what, files ±lines, tickets done, tests, breaking, TODOs).
+7. Report DONE (report-format module) + "Codex approved. Report in docs/tasks/<id>/report.md".
 </pipeline>
 
 <artifacts>
 ## Task documentation structure
-
-Every task creates this folder (create it at the start of Phase 1):
 ```
 docs/tasks/<task-id>/
-├── research.md          — Phase 1: what exists, what's affected, risks
-├── plan.md              — Phase 2: what to do, how, which files
-├── codex-review-plan.md — Phase 2: Codex review of the plan
-├── codex-review-impl.md — Phase 3: Codex review of implementation
-└── report.md            — Phase 3: final report (what was done, files, tests)
+├── research.md          — Phase 1: truth (sources + measurements), affected files, risks
+├── plan.md              — Phase 2: what/how/which files + ## Tickets (slices with AC + blocked-by)
+├── codex-review-plan.md — Phase 2: Codex on the plan
+├── codex-review-impl.md — Phase 3: Codex on the impl
+└── report.md            — Phase 3: final report
 ```
 </artifacts>
 
+<rules priority="critical">
+## Research+Experiment rules (Phase 1)
+- NEVER state a fact without a source OR a measurement — "I think" is not truth
+- NEVER stop at the first result — seek counter-evidence
+- NEVER change pass/fail criteria after seeing results (p-hacking)
+- NEVER experiment on production code — temp/tmp/test scripts only, clean up after
+- Flag stale info ("as of 2024, may have changed"); if sources conflict, present BOTH
+
+## Ticketing rules (Phase 2)
+- Slices are VERTICAL (thin end-to-end cuts), never horizontal layers — each ships something testable
+- Every ticket has concrete AC — vague AC ("works well") is useless; make it checkable
+- blocked-by must be acyclic; implement in dependency order
+
+## Pipeline rules
+- NEVER skip a phase. NEVER proceed without approval after Phase 1 and 2 — STOP and wait.
+  Exception: orchestrator says "don't wait" → skip the idle-gate but still do ALL phase work.
+- Codex review MANDATORY for complex tasks (5+ files, security, architecture, integrations).
+  Skip only on trivial (<50 lines, 1 function). Never claim a review ran without its output.
+- All findings → files (docs/tasks/<id>/), not just chat.
+- If research reveals the task is wrong/unnecessary — say so, don't proceed blindly.
+</rules>
+
 <code-quality>
 ## Code quality
 
@@ -91,15 +130,3 @@ docs/tasks/<task-id>/
 - Fail loud — crash > silent bug. Errors must be visible immediately
 - 3 duplicate lines > premature abstraction
 </code-quality>
-
-<rules priority="critical">
-## Critical rules
-- NEVER skip a phase. Even if the task seems simple — research first, plan second, implement third
-- NEVER proceed without approval after Phase 1 and Phase 2. Go idle and wait. Exception: if orchestrator says "don't wait for approval" — skip the GATE (idle+wait), but still do ALL work within each phase (research, plan, codex review, implement, codex review)
-- After writing a plan — send it to the orchestrator for approval. Do NOT self-approve and start implementation before the orchestrator approves
-- **Codex review is MANDATORY for complex tasks** (5+ files, security, architecture, external integrations). Skip Codex ONLY on trivial tasks (<50 lines changed, 1 function, no security implications). When in doubt — run Codex
-- Codex review via Bash (`timeout 300 codex exec ...`) — see codex-debate skill (Quick Review). Never claim a review ran without seeing its output
-- All findings go to files — not just chat. If you figured something out, it goes to docs/tasks/<task-id>/
-- If research reveals the task is wrong or unnecessary — say so in RESEARCH DONE. Don't proceed blindly
-- If Codex disagrees with your approach — seriously consider their point. If you still disagree, document WHY and let orchestrator decide
-</rules>
\ No newline at end of file

codex
Сначала проверю реальное состояние дерева, а не только присланный diff: найду оставшиеся упоминания ролей и посмотрю изменённые файлы целиком, чтобы оценить контекст вокруг промпта.
exec
/usr/bin/zsh -lc 'git diff -- pipelines/default/pipeline.yaml pipelines/default/prompts/roles/full-cycle.md' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
exec
/usr/bin/zsh -lc "sed -n '1,180p' pipelines/default/pipeline.yaml && sed -n '1,240p' pipelines/default/prompts/roles/full-cycle.md" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
name: default
description: Upstream pipeline v2.18 (orchestrator / sub-orchestrator / worker / full-cycle). Behaviour 1:1 with mccalpink/orchestra main.
validation: fail-open
defaults:
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
    model: opus
    skills: [html-artifacts, vps-deploy, codex-debate, grill-me]
    modules: [git-workflow, orchestration, background-jobs, task-management, self-improvement]
    can_spawn: ["*"]
    allow_unrouted_workers: true
    when: Managing a team of workers, decomposing tasks, approving plans
    not_for: Direct implementation — delegate to workers
    description: >
      Manages worker agents. Decomposes tasks, spawns workers, reviews results.
      Available worker roles are injected automatically from roles/ directory.
  sub-orchestrator:
    kind: orchestrator
    label: Sub-Orchestrator
    order: 1
    model: opus
    modules: [git-workflow, orchestration, background-jobs, task-management, self-improvement]
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
    model: sonnet
    skills: [codex-debate]
    modules: [git-workflow, report-format, self-improvement]
    can_spawn: ["*"]
    allow_unrouted_workers: false
    when: Clear task for a known module, implementation from detailed spec, bug fix with known repro
    not_for: Tasks needing research or unknown scope — use full-cycle
    description: >
      General-purpose worker. Implements tasks directly, no pipeline gates.
      For system workers (permanent, module-scoped) and disposable one-shots.
  full-cycle:
    kind: worker
    label: Full-Cycle
    order: 3
    model: opus4.8
    skills: [codex-debate]
    modules: [git-workflow, report-format, self-improvement]
    can_spawn: ["*"]
    allow_unrouted_workers: false
    when: New feature with unknowns, large refactoring (5+ files), external integration, deep research (find out everything about X), empirical measurement / benchmarks, anything where wrong approach = wasted day
    not_for: Trivial bug fixes, config changes, one-line implementation from a clear spec
    description: >
      Research+Experiment (truth from sources AND measurements) → Plan sliced into
      tickets with acceptance criteria → Implement ticket-by-ticket. Strict 3-phase
      pipeline, 2 orchestrator approval gates, Codex review at plan + impl. For a
      research-only task the orchestrator simply stops after Phase 1. All artifacts
      in docs/tasks/<id>/.
<role>
## Role: Full-Cycle Worker

You are a senior engineer who takes a task from truth-finding to shipped code.
You follow a STRICT 3-phase pipeline with approval gates. Do NOT skip phases.
Do NOT freestyle. The orchestrator drives you phase-by-phase — you never pick
the phase yourself, you execute the current one fully and STOP at the gate.
</role>

<pipeline>
## Pipeline — 3 phases, gates after 1 and 2

### Phase 1: RESEARCH + EXPERIMENT (find the TRUTH)
Goal: not opinions — verified truth. Theory (sources) AND practice (measurements),
as the task demands. The orchestrator's task says what's needed: "sources only",
"needs measurements", or both. Do exactly that.

**Investigate (theory):**
1. Read existing code the task touches (grep/read — understand before proposing)
2. Search when external knowledge is needed (WebSearch/WebFetch) — prior art, docs,
   API refs. Specify date ranges ("since 2025"). Read primary sources, not summaries.
3. Cross-check: for every key claim find a SECOND source. Actively seek counter-evidence.

**Experiment (practice) — when the task needs empirical proof:**
4. State the hypothesis: "X causes Y because Z". Define metrics + pass/fail BEFORE running.
5. Run it — temp files / /tmp / test scripts, NEVER production. 2-3 iterations for confidence.
6. Record raw data (numbers, outputs, errors). Don't move goalposts after seeing results.

**Synthesize:**
7. Write `docs/tasks/<task-id>/research.md`:
   - Question / what's being answered
   - Findings — with inline sources [1][2] AND/OR measured numbers
   - Confidence: CONFIRMED (proven/multi-source) / LIKELY / UNCERTAIN / REFUTED
   - Counter-evidence — what argues against
   - Affected files, risks, edge cases (for the code to come)
8. Report: `RESEARCH DONE #<id>: <2-3 sentence truth + confidence>. docs/tasks/<id>/research.md. Awaiting approval to plan.`
9. **STOP. Wait for approval.**

### Phase 2: PLAN → slice into tickets (AC) + Codex review
1. Write `docs/tasks/<task-id>/plan.md`: what changes in which files (functions/classes),
   new files, migration notes, what NOT to touch.
2. **Slice the plan into vertical tickets** (tracer-bullet style — not horizontal layers).
   Each ticket is a self-contained unit of work that Phase 3 implements in a clean pass:
   - **Vertical slice**: end-to-end thin cut (e.g. "add field + endpoint + test"), NOT
     "all DB changes" then "all API changes". Each ticket ships something verifiable.
   - **AC (acceptance criteria)**: concrete, checkable conditions that prove the ticket done
     ("returns 404 on missing id", "old rows resume without error"). Phase 3 self-verifies against these.
   - **blocked-by**: list ticket ids this one depends on (ordering). No cycles.
   Write tickets in `docs/tasks/<task-id>/plan.md` under `## Tickets`:
   ```
   ### T1 — <short title>
   - Files: <files touched>
   - AC: <checkable criteria>
   - blocked-by: none
   ### T2 — <short title>
   - AC: ...
   - blocked-by: T1
   ```
   (These are plan-internal slices, not GitHub issues — Orchestra has its own Task Manager.)
3. Codex review the plan + tickets (codex-debate skill Quick Review). Fix issues, document disagreements.
4. Report: `PLAN READY #<id>: <approach>, N tickets. Plan + Codex in docs/tasks/<id>/. Awaiting approval.`
5. **STOP. Wait for approval.**

### Phase 3: IMPLEMENT ticket-by-ticket + Codex review
1. Implement tickets in `blocked-by` order. Take ONE ticket at a time to keep context lean.
2. After each ticket: check it against its AC (self-verify). If AC fails — fix before moving on.
3. Test: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
4. Codex review the git diff. Fix CRITICAL/HIGH, re-run if needed.
5. Commit (one clean commit, or per-ticket if large): `#<task-id>: <what you did>`.
6. Write `docs/tasks/<task-id>/report.md` (what, files ±lines, tickets done, tests, breaking, TODOs).
7. Report DONE (report-format module) + "Codex approved. Report in docs/tasks/<id>/report.md".
</pipeline>

<artifacts>
## Task documentation structure
```
docs/tasks/<task-id>/
├── research.md          — Phase 1: truth (sources + measurements), affected files, risks
├── plan.md              — Phase 2: what/how/which files + ## Tickets (slices with AC + blocked-by)
├── codex-review-plan.md — Phase 2: Codex on the plan
├── codex-review-impl.md — Phase 3: Codex on the impl
└── report.md            — Phase 3: final report
```
</artifacts>

<rules priority="critical">
## Research+Experiment rules (Phase 1)
- NEVER state a fact without a source OR a measurement — "I think" is not truth
- NEVER stop at the first result — seek counter-evidence
- NEVER change pass/fail criteria after seeing results (p-hacking)
- NEVER experiment on production code — temp/tmp/test scripts only, clean up after
- Flag stale info ("as of 2024, may have changed"); if sources conflict, present BOTH

## Ticketing rules (Phase 2)
- Slices are VERTICAL (thin end-to-end cuts), never horizontal layers — each ships something testable
- Every ticket has concrete AC — vague AC ("works well") is useless; make it checkable
- blocked-by must be acyclic; implement in dependency order

## Pipeline rules
- NEVER skip a phase. NEVER proceed without approval after Phase 1 and 2 — STOP and wait.
  Exception: orchestrator says "don't wait" → skip the idle-gate but still do ALL phase work.
- Codex review MANDATORY for complex tasks (5+ files, security, architecture, integrations).
  Skip only on trivial (<50 lines, 1 function). Never claim a review ran without its output.
- All findings → files (docs/tasks/<id>/), not just chat.
- If research reveals the task is wrong/unnecessary — say so, don't proceed blindly.
</rules>

<code-quality>
## Code quality

**Think before coding.** State your assumptions. If multiple interpretations exist — ask, don't pick silently. If there's a simpler solution — say so. If the orchestrator's spec has a flaw — push back.

**Adversarial self-review.** Before committing, find 2-3 potential bugs or weak spots in your own code. Fix them or flag them in your report.

**Simplicity first.**
- Minimum code that solves the task. Nothing speculative
- No features beyond request. No abstractions for one-off code
- No comments except WHY (not WHAT), non-obvious decisions, docstrings on public API
- 200 lines where 50 suffice → rewrite

**Surgical changes.** Touch ONLY what the task requires.
- Don't "improve" neighboring code, formatting, comments
- Don't refactor what isn't broken. Follow existing style
- Noticed dead code → mention, don't delete unless your changes orphaned it

**Pit of success.** Code where screwing up is hard.
- Flat structure, minimal indirection. Reads top to bottom
- One task = one pattern. Not two helpers for the same thing
- Explicit > implicit. No magic, no hidden side effects
- Fail loud — crash > silent bug. Errors must be visible immediately
- 3 duplicate lines > premature abstraction
</code-quality>

exec
/usr/bin/zsh -lc "rg -n \"\\b(researcher|experimenter)\\b|can_spawn\" pipelines/default . --glob '"'!**/.git/**'"'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
pipelines/default/pipeline.yaml:25:    can_spawn: ["*"]
pipelines/default/pipeline.yaml:38:    can_spawn: ["*"]
pipelines/default/pipeline.yaml:53:    can_spawn: ["*"]
pipelines/default/pipeline.yaml:67:    can_spawn: ["*"]
pipelines/default/prompts/modules/orchestration.md:16:- **Content/research/writing** (playbook, spec, report, analysis) → ALWAYS delegate to a specialist worker. You are NOT a writer, researcher, or domain expert. You are a manager — decompose, assign, verify. Even if you "know" the answer, a dedicated worker with web search and full context will produce better results
./pipelines/tasks-pm/pipeline.yaml:18:  base-orchestrator: {kind: orchestrator, label: Хаб, order: 0, base_branch_strategy: main, can_spawn: [pm-glava, secretary], allow_unrouted_workers: true, tg: {emoji: "🧭", topic: "{project}"}}
./pipelines/tasks-pm/pipeline.yaml:19:  pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, base_branch_strategy: main, can_spawn: [pm-fichi, secretary], allow_unrouted_workers: false, docs_dir: {path: "_sprint", template: sprint.md}, tg: {emoji: "🎯", topic: "{project} · спринт"}}
./pipelines/tasks-pm/pipeline.yaml:20:  pm-fichi: {kind: orchestrator, label: Фича ПМ, order: 2, can_spawn: [analyst, coder, tester, secretary], allow_unrouted_workers: false, docs_dir: {path: "{feature}/_pm", template: pm.md, requires: feature}, tg: {emoji: "📋", topic: "{feature}"}}
./pipelines/tasks-pm/pipeline.yaml:21:  analyst: {kind: orchestrator, label: Аналитик, order: 3, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_analysis", template: analysis.md, requires: feature}, tg: {emoji: "🔬", topic: "{feature} · анализ"}}
./pipelines/tasks-pm/pipeline.yaml:22:  coder: {kind: orchestrator, label: Кодер, order: 4, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_impl", template: impl.md, requires: feature}, tg: {emoji: "🛠", topic: "{feature} · код"}}
./pipelines/tasks-pm/pipeline.yaml:23:  tester: {kind: orchestrator, label: Тестировщик, order: 5, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_testing", template: testing.md, requires: feature}, tg: {emoji: "🧪", topic: "{feature} · тест"}}
./pipelines/tasks-pm/pipeline.yaml:24:  secretary: {kind: worker, label: Секретарь, can_spawn: [], allow_unrouted_workers: false}
./pipelines/tasks-pm/pipeline.yaml:25:  worker: {kind: worker, label: Воркер, can_spawn: [], allow_unrouted_workers: false}
./tests/test_default_pipeline.py:119:        """sub-orchestrator — kind:orchestrator, opus, can_spawn=['*']."""
./tests/test_default_pipeline.py:124:        assert rr.can_spawn == ["*"]
./tests/test_default_pipeline.py:141:    def test_orchestrator_can_spawn_wildcard_and_unrouted(self):
./tests/test_default_pipeline.py:142:        """Апстрим не ограничивает оркестратора: can_spawn=['*'], дефолтный
./tests/test_default_pipeline.py:145:        assert rr.can_spawn == ["*"]
./tests/test_default_pipeline.py:302:# ── validate_spawn: fail-open + can_spawn=['*'] + allow_unrouted_workers ────
./tests/test_default_pipeline.py:306:        """orchestrator can_spawn=['*'] → спавн worker разрешён."""
./tests/test_default_pipeline.py:313:        """can_spawn=['*'] → новые роли v2.16 спавнятся оркестратором."""
./tests/test_default_pipeline.py:318:        """sub-orchestrator тоже can_spawn=['*'] — делегирует вниз."""
./tests/test_default_pipeline.py:331:        """fail-open: при can_spawn=['*'] и неизвестном child — пропуск (дух апстрима,
./pipelines/default/pipeline.yaml:25:    can_spawn: ["*"]
./pipelines/default/pipeline.yaml:38:    can_spawn: ["*"]
./pipelines/default/pipeline.yaml:53:    can_spawn: ["*"]
./pipelines/default/pipeline.yaml:67:    can_spawn: ["*"]
./tests/test_pipeline.py:57:        can_spawn: [hand]
./tests/test_pipeline.py:62:        can_spawn: []
./tests/test_pipeline.py:97:# ── Валидация схемы (extra=forbid, kind, model, can_spawn-граф) ─────────────
./tests/test_pipeline.py:168:    def test_can_spawn_unknown_role_rejected(self, pipelines_root):
./tests/test_pipeline.py:172:              a: {kind: orchestrator, label: A, can_spawn: [ghost]}
./tests/test_pipeline.py:178:    def test_can_spawn_wildcard_allowed(self, pipelines_root):
./tests/test_pipeline.py:182:              a: {kind: orchestrator, label: A, can_spawn: ["*"]}
./tests/test_pipeline.py:186:        assert cfg.roles["a"].can_spawn == ["*"]
./tests/test_pipeline.py:405:        can_spawn: [coder, secretary]
./tests/test_pipeline.py:413:        can_spawn: [secretary]
./tests/test_pipeline.py:419:        can_spawn: []
./tests/test_pipeline.py:615:      lead: {kind: orchestrator, label: Lead, can_spawn: [coder, secretary], allow_unrouted_workers: false}
./tests/test_pipeline.py:616:      coder: {kind: orchestrator, label: Coder, can_spawn: [secretary], allow_unrouted_workers: true}
./tests/test_pipeline.py:617:      secretary: {kind: worker, label: Secretary, can_spawn: []}
./tests/test_pipeline.py:624:      lead: {kind: orchestrator, label: Lead, can_spawn: [coder], allow_unrouted_workers: false}
./tests/test_pipeline.py:625:      coder: {kind: orchestrator, label: Coder, can_spawn: [], allow_unrouted_workers: false}
./tests/test_pipeline.py:642:        # coder.can_spawn=[secretary]; coder→coder запрещён
./tests/test_pipeline.py:681:        # известных ролях всё равно действует (coder.can_spawn=[] → terminal)
./tests/test_pipeline.py:694:    def test_wildcard_can_spawn_allows_any(self, pipelines_root):
./tests/test_pipeline.py:699:              boss: {kind: orchestrator, label: Boss, can_spawn: ["*"]}
./tests/test_pipeline.py:740:      base-orchestrator: {kind: orchestrator, label: Хаб, order: 0, base_branch_strategy: main, can_spawn: [pm-glava, secretary], allow_unrouted_workers: true, tg: {emoji: "🧭", topic: "{project}"}}
./tests/test_pipeline.py:741:      pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, base_branch_strategy: main, can_spawn: [pm-fichi, secretary], allow_unrouted_workers: false, docs_dir: {path: "_sprint", template: sprint.md}, tg: {emoji: "🎯", topic: "{project} · спринт"}}
./tests/test_pipeline.py:742:      pm-fichi: {kind: orchestrator, label: Фича ПМ, order: 2, can_spawn: [analyst, coder, tester, secretary], allow_unrouted_workers: false, docs_dir: {path: "{feature}/_pm", template: pm.md, requires: feature}, tg: {emoji: "📋", topic: "{feature}"}}
./tests/test_pipeline.py:743:      analyst: {kind: orchestrator, label: Аналитик, order: 3, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_analysis", template: analysis.md, requires: feature}, tg: {emoji: "🔬", topic: "{feature} · анализ"}}
./tests/test_pipeline.py:744:      coder: {kind: orchestrator, label: Кодер, order: 4, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_impl", template: impl.md, requires: feature}, tg: {emoji: "🛠", topic: "{feature} · код"}}
./tests/test_pipeline.py:745:      tester: {kind: orchestrator, label: Тестировщик, order: 5, can_spawn: [secretary], allow_unrouted_workers: true, docs_dir: {path: "{feature}/_testing", template: testing.md, requires: feature}, tg: {emoji: "🧪", topic: "{feature} · тест"}}
./tests/test_pipeline.py:746:      secretary: {kind: worker, label: Секретарь, can_spawn: [], allow_unrouted_workers: false}
./tests/test_pipeline.py:747:      worker: {kind: worker, label: Воркер, can_spawn: [], allow_unrouted_workers: false}
./tests/test_pipeline.py:783:        # pm-glava → pm-fichi OK; pm-glava → coder запрещён (не в can_spawn)
./tests/test_manager.py:414:        # can_spawn is read from temp frontmatter (_PROMPTS_DIR). The prompt build
./tests/test_manager.py:431:    def test_role_can_spawn_absent_is_none(self, roles_dir):
./tests/test_manager.py:432:        from app.prompting import role_can_spawn as _role_can_spawn
./tests/test_manager.py:434:        assert _role_can_spawn("boss") is None
./tests/test_manager.py:436:    def test_role_can_spawn_yaml_null_is_none(self, roles_dir):
./tests/test_manager.py:437:        from app.prompting import role_can_spawn as _role_can_spawn
./tests/test_manager.py:438:        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn:")
./tests/test_manager.py:439:        assert _role_can_spawn("boss") is None
./tests/test_manager.py:441:    def test_role_can_spawn_non_list_is_none(self, roles_dir):
./tests/test_manager.py:442:        from app.prompting import role_can_spawn as _role_can_spawn
./tests/test_manager.py:443:        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: worker")
./tests/test_manager.py:444:        assert _role_can_spawn("boss") is None
./tests/test_manager.py:446:    def test_role_can_spawn_empty_list_is_terminal(self, roles_dir):
./tests/test_manager.py:447:        from app.prompting import role_can_spawn as _role_can_spawn
./tests/test_manager.py:448:        self._write_role(roles_dir, "leaf", "name: leaf\ncan_spawn: []")
./tests/test_manager.py:449:        assert _role_can_spawn("leaf") == []
./tests/test_manager.py:451:    def test_role_can_spawn_whitelist(self, roles_dir):
./tests/test_manager.py:452:        from app.prompting import role_can_spawn as _role_can_spawn
./tests/test_manager.py:453:        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker, reviewer]")
./tests/test_manager.py:454:        assert _role_can_spawn("boss") == ["worker", "reviewer"]
./tests/test_manager.py:456:    def test_role_can_spawn_missing_file_is_none(self, roles_dir):
./tests/test_manager.py:457:        from app.prompting import role_can_spawn as _role_can_spawn
./tests/test_manager.py:458:        assert _role_can_spawn("ghost") is None
./tests/test_manager.py:464:        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker]")
./tests/test_manager.py:481:    # REMOVED: test_whitelist_blocks_unlisted + test_empty_can_spawn_blocks_all.
./tests/test_manager.py:482:    # They tested the legacy frontmatter can_spawn fallback (role_can_spawn reading
./tests/test_manager.py:605:  pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, can_spawn: [pm-fichi, secretary]}
./tests/test_manager.py:606:  pm-fichi: {kind: orchestrator, label: Фича ПМ, order: 2, can_spawn: [coder, secretary]}
./tests/test_manager.py:607:  coder: {kind: orchestrator, label: Кодер, order: 4, can_spawn: [secretary], allow_unrouted_workers: true}
./tests/test_manager.py:608:  secretary: {kind: worker, label: Секретарь, can_spawn: []}
./tests/test_manager.py:609:  worker: {kind: worker, label: Воркер, can_spawn: []}
./tests/test_manager.py:685:        """Оркестратор pm-glava видит каталог только pm-fichi+secretary (can_spawn)."""
./tests/test_manager.py:690:        # coder и worker НЕ в can_spawn pm-glava → нет их записей в каталоге
./tests/test_manager.py:719:    def test_star_can_spawn_shows_all(self, tmp_path, monkeypatch):
./tests/test_manager.py:720:        """can_spawn=['*'] → каталог показывает ВСЕ роли пайплайна."""
./tests/test_manager.py:727:            "  boss: {kind: orchestrator, label: Boss, order: 0, can_spawn: ['*']}\n"
./tests/test_manager.py:728:            "  a: {kind: worker, label: A, order: 1, can_spawn: []}\n"
./tests/test_manager.py:729:            "  b: {kind: worker, label: B, order: 2, can_spawn: []}\n"
./tests/test_manager.py:757:        """pm-glava НЕ может спавнить coder (нет в can_spawn) — ValueError ДО worktree."""
./tests/test_manager.py:798:        """pm-glava МОЖЕТ спавнить secretary (в can_spawn)."""
./tests/test_manager.py:816:    # REMOVED: test_fallback_when_no_manifest — tested the legacy _role_can_spawn
./pipelines/default/prompts/modules/orchestration.md:16:- **Content/research/writing** (playbook, spec, report, analysis) → ALWAYS delegate to a specialist worker. You are NOT a writer, researcher, or domain expert. You are a manager — decompose, assign, verify. Even if you "know" the answer, a dedicated worker with web search and full context will produce better results
./app/prompting.py:88:def role_can_spawn(role: str):
./app/prompting.py:89:    """Return the can_spawn whitelist for a role, or None if unrestricted."""
./app/prompting.py:94:    if "can_spawn" not in meta:
./app/prompting.py:96:    val = meta["can_spawn"]
./app/prompting.py:98:        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
./app/manager.py:143:    """Каталог ролей оркестратору из манифеста, отфильтрованный по ``can_spawn``.
./app/manager.py:145:    B2: показываем ВСЕ роли из ``can_spawn`` родителя (включая под-оркестраторов).
./app/manager.py:146:    ``can_spawn=['*']`` → все роли пайплайна. Сортировка по ``order``. Закрывает
./app/manager.py:153:    if "*" in parent.can_spawn:
./app/manager.py:158:        visible = list(parent.can_spawn)
./app/manager.py:175:    (фильтр ``can_spawn``) + блоки других оркестраторов/воркеров из БД.
./app/manager.py:482:        # манифест-путь (validate_spawn) — legacy frontmatter-fallback (role_can_spawn
./CLAUDE.md:167:- `experimenter` — hypothesis → experiment → measure → conclude. Opus 4.8
./CLAUDE.md:168:- `researcher` — search → verify → synthesize. Web research with counter-evidence. Opus 4.8
./app/pipeline.py:176:    can_spawn: list[str] = Field(default_factory=list)  # "*" = любая роль; [] = терминал
./app/pipeline.py:224:        """can_spawn ⊆ roles (кроме '*'): ссылка на несуществующую роль → ошибка."""
./app/pipeline.py:227:            for child in r.can_spawn:
./app/pipeline.py:230:                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
./app/pipeline.py:246:    can_spawn: list[str]
./app/pipeline.py:276:        граф can_spawn.
./app/pipeline.py:282:    cfg = PipelineConfig(**data)  # pydantic: схема + граф can_spawn
./app/pipeline.py:353:        order=spec.order, can_spawn=spec.can_spawn,
./app/pipeline.py:458:      ``can_spawn``-whitelist при ИЗВЕСТНЫХ ролях действует в обоих режимах.
./app/pipeline.py:482:                f"allowed: {parent.can_spawn or '(none)'}")
./app/pipeline.py:490:    if "*" in parent.can_spawn:
./app/pipeline.py:492:    if child_role not in parent.can_spawn:
./app/pipeline.py:495:            f"allowed: {parent.can_spawn or '(none — terminal)'}")
./CHANGELOG.md:341:- 🛡️ **validate_spawn** (#25) — `can_spawn: [worker, full-cycle]` in role YAML frontmatter. Parent role whitelist enforced in `create_session`. Absent/empty = allow all. `manager.py`, `mcp_stdio.py`
./docs/fork-analysis.md:66:- We have frontmatter parsing with `can_spawn`, `modules`, `icon`, `skills` support
./docs/fork-analysis.md:131:| `app/manager.py` | +568/-X: module system, role frontmatter, skills catalog, role icons, role_can_spawn, owned_dirs overlap check, description in workers_block | +114/-X: role prompt loading, parent hierarchy, doc scaffolding, simplified prompt building | 🔴 HIGH | Different prompt architecture |
./scripts/extract-manifest.py:18:  * ``can_spawn``: НЕТ во frontmatter → ``["*"]`` (unlimited, как upstream None);
./scripts/extract-manifest.py:101:    # can_spawn: поля нет → unlimited (["*"], как upstream None); иначе — как есть.
./scripts/extract-manifest.py:102:    if "can_spawn" in fm:
./scripts/extract-manifest.py:103:        can_spawn = list(fm["can_spawn"]) if isinstance(fm["can_spawn"], list) else ["*"]
./scripts/extract-manifest.py:105:        can_spawn = ["*"]
./scripts/extract-manifest.py:112:        "can_spawn": can_spawn,
./scripts/extract-manifest.py:155:    PipelineConfig(**data)  # pydantic: схема + граф can_spawn
./docs/reviews/fable-full-review.md:182:**Good:** Closest to flawless. `extra="forbid"` on every model; `_is_safe_rel` traversal validation on *every* user-controlled path (layers, modules, copies, symlinks, docs); can_spawn graph validated at load; fail-closed default with documented fail-open escape hatch; `list_pipelines` marks broken manifests instead of dying; defaults→role merge semantics documented per-field.
./docs/tasks/CODEX_REVIEW_PLANS.md:19:1. `app/manager.py:92` — предложенный `val = meta.get("can_spawn", None)` не различает “поля нет” и “поле есть, но YAML null”: `can_spawn:` через `yaml.safe_load` даст `{"can_spawn": None}`. Это прямо ломает заявленную absent-vs-empty/present семантику на краю формата. Fix: проверять наличие ключа отдельно: `if "can_spawn" not in meta: return None`; затем читать `val = meta["can_spawn"]`; `None`/не-list трактовать как malformed fail-open с warning.
./docs/tasks/CODEX_REVIEW_PLANS.md:21:2. `app/main.py:365`, `app/manager.py:305`, `app/mcp_stdio.py:67` — план валидирует parent role через `parent_name`, который приходит от клиента. Если это должно быть ограничение безопасности, а не подсказка для честного `spawn_worker`, API caller может указать permissive parent и обойти `can_spawn`. Fix: либо явно документировать как advisory guardrail, либо выводить parent identity server-side из доверенного контекста. Минимально: не считать `parent_name` из произвольного `/api/sessions` security boundary; для MCP-path можно передавать caller role/name из stdio env, но тогда это тоже доверие к локальному MCP процессу.
./docs/archive/CODEX_USAGE_REPORT.md:84:| victor-researcher | 15 | 1,023 | victor-audit, vad-quality, callback, calltrack, tg-html, voice-speed, nationwide-fallback, victoria-fsm, warm-transfer, groq-removal, squid, er-compact |
./docs/archive/CODEX_USAGE_REPORT.md:281:- Получал задачи от 5 разных агентов: Parsing-orchestrator, test-worker, victor-researcher, zahoron-worker, drevo-worker
./docs/experiments/85/results.json:1653:          "raw": "```json\n{\n  \"trigger\": \"когда оркестратор/агент должен написать что-то для пользователя (письмо клиенту, КП, сообщение, спецификацию)\",\n  \"action\": \"делегировать специализированному воркеру-профессионалу (manager/writer/researcher) который исследует лучшие практики, стиль юзера, контекст и пишет из знаний, не выдумывая; оркестратор только координирует и встраивает результат\",\n  \"avoid\": \"оркестратор сам придумывает текст, письма, рекомендации без исследования и без соответствия стилю клиента; импровизация вместо делегирования профессионалу\",\n  \"category\": \"delegation\",\n  \"confidence\": 0.92\n}\n`",
./docs/experiments/85/results.json:1656:            "action": "делегировать специализированному воркеру-профессионалу (manager/writer/researcher) который исследует лучшие практики, стиль юзера, контекст и пишет из знаний, не выдумывая; оркестратор только координирует и встраивает результат",
./docs/experiments/85/results.json:1666:          "raw": "```json\n{\n  \"trigger\": \"Когда агент должен выполнить задачу требующую специальных знаний, стиля или исследования (писать коммуникации, составлять гайды, искать best practices)\",\n  \"action\": \"Делегировать специализированному worker'у (researcher, writer, domain expert) вместо того чтобы делать это самому — worker получает задачу, ищет источники, составляет артефакт (инструкцию/гайд/стиль-гайд) который потом переиспользуется\",\n  \"avoid\": \"НЕ выдумывать от себя (hallucinate) контент, который требует реальных знаний. НЕ пытаться 'быстро решить' через импровизацию. НЕ копировать существующие инстру",
./docs/experiments/85/results.json:1669:            "action": "Делегировать специализированному worker'у (researcher, writer, domain expert) вместо того чтобы делать это самому — worker получает задачу, ищет источники, составляет артефакт (инструкцию/гайд/стиль-гайд) который потом переиспользуется",
./docs/experiments/85/results.jsonl:7:{"log_id": 195172, "session_id": "07233e67-502d-4c62-9f34-b37fbbdf8606", "source": "real", "agent_output": "Готово.\n\n**Root cause**: Bash command с heredoc (`python3 << 'PYEOF'\\nfrom PIL...\\n...`) приходит как одна строка с `\\n`. `_wrap_line(command)` не split'ила по переносам — видела одну строку в 500+ символов, резала по 90 char, но все куски рендерились с `$ ` префиксом как одна команда. Multiline heredoc body схлопывался в кашу.\n\n**Фикс**: `command.split('\\n')` перед `_wrap_line` — каждая строка heredoc'а обрабатывается отдельно. Рестарт нужен.", "correction": "--- message 1/21 ---\n[from TG: Максим Астраханцев] Смотри какой траьл. Раньше оркестра сам пытался сообщения писать типо че-то придумывал но он же тупой блять. И я попросил специалиста воркера сделать и он все сделал и все ахуенно теперь сразу кп просят. Типо можем ли мы сделать типо это в нашем промптах или как типо чтобы оркестра сам сука не выдумывал а тупо бы специалистов просил вся работа только специалистами воркерами которые профи блять либо они делают типо код либо они пишут ресерчи и спецификации что да как делать типо знания получают из инета ахуенные и инструкции пишут и потом любой агент может ими пользоваться. Че думаешь?\n--- message 2/21 ---\n[from TG: Максим Астраханцев] [Forwarded from Orchestra] 👤 крч воркера давай менеджера который общается как это человека называют воркера опуса создай спеицализированно по общению с клиентами чтобы он СУК АЛЧШИЕ БЕСТ ПРАКТИС НАУЧНЫЕ ДАННЫЕ И ВСЕ ВСЕ поискал поизучал и сука составил библию блять как общаться с клиентами и про наш случай расписал бы все сообщения как скрипт что как где что спрашиваем почему и тд и тп без ии хуйни только в моем стиле типо как тут [26.06.2026 14:17] Максим Астраханцев: Диля, здравствуйте! Увидел вашу ", "_key": "real:195172:51e89f8e", "runs": [{"run": 0, "raw": "```json\n{\n  \"trigger\": \"когда оркестратор/агент должен написать что-то для пользователя (письмо клиенту, КП, сообщение, спецификацию)\",\n  \"action\": \"делегировать специализированному воркеру-профессионалу (manager/writer/researcher) который исследует лучшие практики, стиль юзера, контекст и пишет из знаний, не выдумывая; оркестратор только координирует и встраивает результат\",\n  \"avoid\": \"оркестратор сам придумывает текст, письма, рекомендации без исследования и без соответствия стилю клиента; импровизация вместо делегирования профессионалу\",\n  \"category\": \"delegation\",\n  \"confidence\": 0.92\n}\n`", "parsed": {"trigger": "когда оркестратор/агент должен написать что-то для пользователя (письмо клиенту, КП, сообщение, спецификацию)", "action": "делегировать специализированному воркеру-профессионалу (manager/writer/researcher) который исследует лучшие практики, стиль юзера, контекст и пишет из знаний, не выдумывая; оркестратор только координирует и встраивает результат", "avoid": "оркестратор сам придумывает текст, письма, рекомендации без исследования и без соответствия стилю клиента; импровизация вместо делегирования профессионалу", "category": "delegation", "confidence": 0.92}, "status": "ok", "latency_s": 7.7}, {"run": 1, "raw": "```json\n{\n  \"trigger\": \"Когда агент должен выполнить задачу требующую специальных знаний, стиля или исследования (писать коммуникации, составлять гайды, искать best practices)\",\n  \"action\": \"Делегировать специализированному worker'у (researcher, writer, domain expert) вместо того чтобы делать это самому — worker получает задачу, ищет источники, составляет артефакт (инструкцию/гайд/стиль-гайд) который потом переиспользуется\",\n  \"avoid\": \"НЕ выдумывать от себя (hallucinate) контент, который требует реальных знаний. НЕ пытаться 'быстро решить' через импровизацию. НЕ копировать существующие инстру", "parsed": {"trigger": "Когда агент должен выполнить задачу требующую специальных знаний, стиля или исследования (писать коммуникации, составлять гайды, искать best practices)", "action": "Делегировать специализированному worker'у (researcher, writer, domain expert) вместо того чтобы делать это самому — worker получает задачу, ищет источники, составляет артефакт (инструкцию/гайд/стиль-гайд) который потом переиспользуется", "avoid": "НЕ выдумывать от себя (hallucinate) контент, который требует реальных знаний. НЕ пытаться 'быстро решить' через импровизацию. НЕ копировать существующие инструкции без глубокого анализа", "category": "delegation", "confidence": 0.95}, "status": "ok", "latency_s": 12.0}]}
./docs/tasks/pipeline-rebase/codex-review-impl.md:353:+    """Каталог ролей оркестратору из манифеста, отфильтрованный по ``can_spawn``.
./docs/tasks/pipeline-rebase/codex-review-impl.md:355:+    B2: показываем ВСЕ роли из ``can_spawn`` родителя (включая под-оркестраторов).
./docs/tasks/pipeline-rebase/codex-review-impl.md:356:+    ``can_spawn=['*']`` → все роли пайплайна. Сортировка по ``order``. Закрывает
./docs/tasks/pipeline-rebase/codex-review-impl.md:363:+    if "*" in parent.can_spawn:
./docs/tasks/pipeline-rebase/codex-review-impl.md:368:+        visible = list(parent.can_spawn)
./docs/tasks/pipeline-rebase/codex-review-impl.md:385:+    затем для оркестратора — каталог ролей (фильтр ``can_spawn``) + блоки других
./docs/tasks/pipeline-rebase/codex-review-impl.md:542:+        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
./docs/tasks/pipeline-rebase/codex-review-impl.md:548:                 whitelist = role_can_spawn(parent_role)
./docs/tasks/pipeline-rebase/codex-review-impl.md:589:/usr/bin/zsh -lc "rg -n \"from app\\.manager import|ROLE_SYSTEM_PROMPT|ORCHESTRATOR_SYSTEM_PROMPT|WORKER_SYSTEM_PROMPT|is_orchestrator_role|role_can_spawn|reviewer|watcher|app\\.prompting\" tests app -S" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
./docs/tasks/pipeline-rebase/codex-review-impl.md:592:tests/test_default_equals_upstream.py:11:    can_spawn/... + тело). Функции реконструкции: ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``,
./docs/tasks/pipeline-rebase/codex-review-impl.md:593:tests/test_default_equals_upstream.py:12:    ``_prompting.role_prompt_file``, ``manager._load_modules``, ``_prompting.role_can_spawn``,
./docs/tasks/pipeline-rebase/codex-review-impl.md:594:tests/test_default_equals_upstream.py:20:  2. validate_spawn для ВСЕХ пар (parent, child) совпадает с ``_role_can_spawn``.
./docs/tasks/pipeline-rebase/codex-review-impl.md:596:tests/test_default_equals_upstream.py:107:    """Решение upstream по ``_role_can_spawn`` (frontmatter can_spawn).
./docs/tasks/pipeline-rebase/codex-review-impl.md:597:tests/test_default_equals_upstream.py:109:    Семантика ``_role_can_spawn``:
./docs/tasks/pipeline-rebase/codex-review-impl.md:598:tests/test_default_equals_upstream.py:115:    wl = _prompting.role_can_spawn(parent)
./docs/tasks/pipeline-rebase/codex-review-impl.md:599:tests/test_default_equals_upstream.py:135:            assert _prompting.role_can_spawn(parent) is None  # upstream: поля нет
./docs/tasks/pipeline-rebase/codex-review-impl.md:606:app/manager.py:17:    role_prompt_file, role_can_spawn,
./docs/tasks/pipeline-rebase/codex-review-impl.md:620:app/manager.py:492:        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
./docs/tasks/pipeline-rebase/codex-review-impl.md:621:app/manager.py:498:                whitelist = role_can_spawn(parent_role)
./docs/tasks/pipeline-rebase/codex-review-impl.md:640:app/prompting.py:83:def role_can_spawn(role: str):
./docs/tasks/pipeline-rebase/codex-review-impl.md:647:tests/test_manager.py:401:    def test_role_can_spawn_absent_is_none(self, roles_dir):
./docs/tasks/pipeline-rebase/codex-review-impl.md:648:tests/test_manager.py:402:        from app.prompting import role_can_spawn as _role_can_spawn
./docs/tasks/pipeline-rebase/codex-review-impl.md:649:tests/test_manager.py:404:        assert _role_can_spawn("boss") is None
./docs/tasks/pipeline-rebase/codex-review-impl.md:650:tests/test_manager.py:406:    def test_role_can_spawn_yaml_null_is_none(self, roles_dir):
./docs/tasks/pipeline-rebase/codex-review-impl.md:651:tests/test_manager.py:407:        from app.prompting import role_can_spawn as _role_can_spawn
./docs/tasks/pipeline-rebase/codex-review-impl.md:652:tests/test_manager.py:409:        assert _role_can_spawn("boss") is None
./docs/tasks/pipeline-rebase/codex-review-impl.md:653:tests/test_manager.py:411:    def test_role_can_spawn_non_list_is_none(self, roles_dir):
./docs/tasks/pipeline-rebase/codex-review-impl.md:654:tests/test_manager.py:412:        from app.prompting import role_can_spawn as _role_can_spawn
./docs/tasks/pipeline-rebase/codex-review-impl.md:655:tests/test_manager.py:414:        assert _role_can_spawn("boss") is None
./docs/tasks/pipeline-rebase/codex-review-impl.md:656:tests/test_manager.py:416:    def test_role_can_spawn_empty_list_is_terminal(self, roles_dir):
./docs/tasks/pipeline-rebase/codex-review-impl.md:657:tests/test_manager.py:417:        from app.prompting import role_can_spawn as _role_can_spawn
./docs/tasks/pipeline-rebase/codex-review-impl.md:658:tests/test_manager.py:419:        assert _role_can_spawn("leaf") == []
./docs/tasks/pipeline-rebase/codex-review-impl.md:659:tests/test_manager.py:421:    def test_role_can_spawn_whitelist(self, roles_dir):
./docs/tasks/pipeline-rebase/codex-review-impl.md:660:tests/test_manager.py:422:        from app.prompting import role_can_spawn as _role_can_spawn
./docs/tasks/pipeline-rebase/codex-review-impl.md:661:tests/test_manager.py:423:        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker, reviewer]")
./docs/tasks/pipeline-rebase/codex-review-impl.md:662:tests/test_manager.py:424:        assert _role_can_spawn("boss") == ["worker", "reviewer"]
./docs/tasks/pipeline-rebase/codex-review-impl.md:663:tests/test_manager.py:426:    def test_role_can_spawn_missing_file_is_none(self, roles_dir):
./docs/tasks/pipeline-rebase/codex-review-impl.md:664:tests/test_manager.py:427:        from app.prompting import role_can_spawn as _role_can_spawn
./docs/tasks/pipeline-rebase/codex-review-impl.md:665:tests/test_manager.py:428:        assert _role_can_spawn("ghost") is None
./docs/tasks/pipeline-rebase/codex-review-impl.md:709:tests/test_manager.py:867:        """Нет манифеста → validate_spawn кидает FileNotFoundError → fallback _role_can_spawn.
./docs/tasks/pipeline-rebase/codex-review-impl.md:739:pipelines/tasks-pm/pipeline.yaml:18:  base-orchestrator: {kind: orchestrator, label: Хаб, order: 0, base_branch_strategy: main, can_spawn: [pm-glava, secretary], allow_unrouted_workers: true, tg: {emoji: "🧭", topic: "{project}"}}
./docs/tasks/pipeline-rebase/codex-review-impl.md:740:pipelines/tasks-pm/pipeline.yaml:19:  pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, base_branch_strategy: main, can_spawn: [pm-fichi, secretary], allow_unrouted_workers: false, docs_dir: {path: "_sprint", template: sprint.md}, tg: {emoji: "🎯", topic: "{project} · спринт"}}
./docs/tasks/pipeline-rebase/codex-review-impl.md:904:tests/test_default_pipeline.py:300:# ── validate_spawn: fail-open + can_spawn=['*'] + allow_unrouted_workers ────
./docs/tasks/pipeline-rebase/codex-review-impl.md:925:tests/test_default_equals_upstream.py:20:  2. validate_spawn для ВСЕХ пар (parent, child) совпадает с ``_role_can_spawn``.
./docs/tasks/pipeline-rebase/codex-review-impl.md:998:tests/test_pipeline.py:168:    def test_can_spawn_unknown_role_rejected(self, pipelines_root):
./docs/tasks/pipeline-rebase/codex-review-impl.md:1001:tests/test_pipeline.py:178:    def test_can_spawn_wildcard_allowed(self, pipelines_root):
./docs/tasks/pipeline-rebase/codex-review-impl.md:1155:tests/test_pipeline.py:694:    def test_wildcard_can_spawn_allows_any(self, pipelines_root):
./docs/tasks/pipeline-rebase/codex-review-impl.md:1167:tests/test_pipeline.py:740:      base-orchestrator: {kind: orchestrator, label: Хаб, order: 0, base_branch_strategy: main, can_spawn: [pm-glava, secretary], allow_unrouted_workers: true, tg: {emoji: "🧭", topic: "{project}"}}
./docs/tasks/pipeline-rebase/codex-review-impl.md:1168:tests/test_pipeline.py:741:      pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, base_branch_strategy: main, can_spawn: [pm-fichi, secretary], allow_unrouted_workers: false, docs_dir: {path: "_sprint", template: sprint.md}, tg: {emoji: "🎯", topic: "{project} · спринт"}}
./docs/tasks/pipeline-rebase/codex-review-impl.md:1612:tests/test_manager.py:867:        """Нет манифеста → validate_spawn кидает FileNotFoundError → fallback _role_can_spawn.
./docs/tasks/pipeline-rebase/codex-review-impl.md:1702:app/pipeline.py:222:                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
./docs/tasks/pipeline-rebase/codex-review-impl.md:1812:        граф can_spawn.
./docs/tasks/pipeline-rebase/codex-review-impl.md:1818:    cfg = PipelineConfig(**data)  # pydantic: схема + граф can_spawn
./docs/tasks/pipeline-rebase/codex-review-impl.md:1889:        order=spec.order, can_spawn=spec.can_spawn,
./docs/tasks/pipeline-rebase/codex-review-impl.md:1994:      ``can_spawn``-whitelist при ИЗВЕСТНЫХ ролях действует в обоих режимах.
./docs/tasks/pipeline-rebase/codex-review-impl.md:2018:                f"allowed: {parent.can_spawn or '(none)'}")
./docs/tasks/pipeline-rebase/codex-review-impl.md:2026:    if "*" in parent.can_spawn:
./docs/tasks/pipeline-rebase/codex-review-impl.md:2028:    if child_role not in parent.can_spawn:
./docs/tasks/pipeline-rebase/codex-review-impl.md:2031:            f"allowed: {parent.can_spawn or '(none — terminal)'}")
./docs/tasks/pipeline-rebase/codex-review-impl.md:2203:    can_spawn: list[str] = Field(default_factory=list)  # "*" = любая роль; [] = терминал
./docs/tasks/pipeline-rebase/codex-review-impl.md:2251:        """can_spawn ⊆ roles (кроме '*'): ссылка на несуществующую роль → ошибка."""
./docs/tasks/pipeline-rebase/codex-review-impl.md:2254:            for child in r.can_spawn:
./docs/tasks/pipeline-rebase/codex-review-impl.md:2257:                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
./docs/tasks/pipeline-rebase/codex-review-impl.md:2273:    can_spawn: list[str]
./docs/tasks/pipeline-rebase/codex-review-impl.md:2696:        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
./docs/tasks/pipeline-rebase/codex-review-impl.md:2702:                whitelist = role_can_spawn(parent_role)
./docs/tasks/pipeline-rebase/codex-review-impl.md:6143:-                whitelist = _role_can_spawn(parent_role)
./docs/tasks/pipeline-rebase/codex-review-impl.md:6144:+                whitelist = role_can_spawn(parent_role)
./docs/tasks/pipeline-rebase/plan.md:78:- ALL inlined prompt functions (`_safe_format_prompt`, `_read_prompt`, `_parse_role_frontmatter`, `_load_modules`, `_role_prompt_file`, `_role_can_spawn`, `_skills_catalog`, `get_role_icons`, `_roles_catalog`, `_prompt_template_hash`) — use `app.prompting` instead
./docs/tasks/pipeline-rebase/research.md:24:- `role_prompt_file`, `role_can_spawn`, `roles_catalog`, `skills_catalog`
./docs/tasks/debate-test/plan.md:21:| `_role_can_spawn()` | 153-169 | `_parse_role_frontmatter` |
./docs/archive/ROI_REPORT.md:89:| victor-researcher | $96 | 120 | 108 | idle |
./docs/archive/SPEC_v1.md:458:│   [orchestrator response]          │  │ researcher ● idle│  │
./docs/tasks/pipeline-rebase/codex-review-plan.md:101:- ALL inlined prompt functions (`_safe_format_prompt`, `_read_prompt`, `_parse_role_frontmatter`, `_load_modules`, `_role_prompt_file`, `_role_can_spawn`, `_skills_catalog`, `get_role_icons`, `_roles_catalog`, `_prompt_template_hash`) — use `app.prompting` instead
./docs/tasks/pipeline-rebase/codex-review-plan.md:354:  feat/mnt-data-projects-python-orchestra/html-skill-researcher      67fe30c262096cfd4eda3a47b9437eb4cffea984 research: HTML artifacts skill — Claude.ai internals, Thariq patterns, dogum analysis
./docs/tasks/pipeline-rebase/codex-review-plan.md:364:  feat/mnt-data-projects-python-orchestra/inject-researcher          1a6e20e610a0e347504d7006f2ae37b7354aa0e7 research: mid-turn message injection via ClaudeSDKClient.query()
./docs/tasks/pipeline-rebase/codex-review-plan.md:388:  feat/mnt-data-projects-python-orchestra/sdk-researcher             b2c62ea94c38378384f4f21960c322d2a182f9be feat: persistent client + seamless pending turns in session.py
./docs/tasks/pipeline-rebase/codex-review-plan.md:396:  feat/mnt-data-projects-python-orchestra/tg-researcher              756938a128f022536ec9c14e40e6cd31e14d645b feat: queue-based TG streaming with rate-limited delivery
./docs/tasks/pipeline-rebase/codex-review-plan.md:398:  feat/mnt-data-projects-python-orchestra/usage-researcher           207489b5d9997c9f5308606fed84cea40b7137f4 feat: send_file MCP tool — agents can send files to TG
./docs/tasks/pipeline-rebase/codex-review-plan.md:448:feat/mnt-data-projects-python-orchestra/html-skill-researcher 67fe30c262096cfd4eda3a47b9437eb4cffea984 research: HTML artifacts skill — Claude.ai internals, Thariq patterns, dogum analysis
./docs/tasks/pipeline-rebase/codex-review-plan.md:458:feat/mnt-data-projects-python-orchestra/inject-researcher 1a6e20e610a0e347504d7006f2ae37b7354aa0e7 research: mid-turn message injection via ClaudeSDKClient.query()
./docs/tasks/pipeline-rebase/codex-review-plan.md:482:feat/mnt-data-projects-python-orchestra/sdk-researcher b2c62ea94c38378384f4f21960c322d2a182f9be feat: persistent client + seamless pending turns in session.py
./docs/tasks/pipeline-rebase/codex-review-plan.md:490:feat/mnt-data-projects-python-orchestra/tg-researcher 756938a128f022536ec9c14e40e6cd31e14d645b feat: queue-based TG streaming with rate-limited delivery
./docs/tasks/pipeline-rebase/codex-review-plan.md:492:feat/mnt-data-projects-python-orchestra/usage-researcher 207489b5d9997c9f5308606fed84cea40b7137f4 feat: send_file MCP tool — agents can send files to TG
./docs/tasks/pipeline-rebase/codex-review-plan.md:860:def role_can_spawn(role: str):
./docs/tasks/pipeline-rebase/codex-review-plan.md:861:    """Return the can_spawn whitelist for a role, or None if unrestricted."""
./docs/tasks/pipeline-rebase/codex-review-plan.md:866:    if "can_spawn" not in meta:
./docs/tasks/pipeline-rebase/codex-review-plan.md:868:    val = meta["can_spawn"]
./docs/tasks/pipeline-rebase/codex-review-plan.md:870:        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
./docs/tasks/pipeline-rebase/codex-review-plan.md:1135:    can_spawn: list[str] = Field(default_factory=list)  # "*" = любая роль; [] = терминал
./docs/tasks/pipeline-rebase/codex-review-plan.md:1183:        """can_spawn ⊆ roles (кроме '*'): ссылка на несуществующую роль → ошибка."""
./docs/tasks/pipeline-rebase/codex-review-plan.md:1186:            for child in r.can_spawn:
./docs/tasks/pipeline-rebase/codex-review-plan.md:1189:                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
./docs/tasks/pipeline-rebase/codex-review-plan.md:1205:    can_spawn: list[str]
./docs/tasks/pipeline-rebase/codex-review-plan.md:1592:def _role_can_spawn(role: str):
./docs/tasks/pipeline-rebase/codex-review-plan.md:1593:    """Return the can_spawn whitelist for a role, or None if unrestricted.
./docs/tasks/pipeline-rebase/codex-review-plan.md:1602:    if "can_spawn" not in meta:
./docs/tasks/pipeline-rebase/codex-review-plan.md:1604:    val = meta["can_spawn"]
./docs/tasks/pipeline-rebase/codex-review-plan.md:1606:        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
./docs/tasks/pipeline-rebase/codex-review-plan.md:1664:17-    role_prompt_file, role_can_spawn,
./docs/tasks/pipeline-rebase/codex-review-plan.md:2005:301-    """Каталог ролей оркестратору из манифеста, отфильтрованный по ``can_spawn``.
./docs/tasks/pipeline-rebase/codex-review-plan.md:2007:303-    B2: показываем ВСЕ роли из ``can_spawn`` родителя (включая под-оркестраторов).
./docs/tasks/pipeline-rebase/codex-review-plan.md:2008:304-    ``can_spawn=['*']`` → все роли пайплайна. Сортировка по ``order``. Закрывает
./docs/tasks/pipeline-rebase/codex-review-plan.md:2015:311-    if "*" in parent.can_spawn:
./docs/tasks/pipeline-rebase/codex-review-plan.md:2036:333-    затем для оркестратора — каталог ролей (фильтр ``can_spawn``) + блоки других
./docs/tasks/pipeline-rebase/codex-review-plan.md:2210:654-        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
./docs/tasks/pipeline-rebase/codex-review-plan.md:2216:660-                whitelist = _role_can_spawn(parent_role)
./docs/tasks/pipeline-rebase/codex-review-plan.md:2924:268-        граф can_spawn.
./docs/tasks/pipeline-rebase/codex-review-plan.md:2938:345-        order=spec.order, can_spawn=spec.can_spawn,
./docs/tasks/pipeline-rebase/codex-review-plan.md:2958:    can_spawn/... + тело). Функции реконструкции: ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``,
./docs/tasks/pipeline-rebase/codex-review-plan.md:2959:    ``manager._role_prompt_file``, ``manager._load_modules``, ``manager._role_can_spawn``,
./docs/tasks/pipeline-rebase/codex-review-plan.md:2967:  2. validate_spawn для ВСЕХ пар (parent, child) совпадает с ``_role_can_spawn``.
./docs/tasks/pipeline-rebase/codex-review-plan.md:3053:    """Решение upstream по ``_role_can_spawn`` (frontmatter can_spawn).
./docs/tasks/pipeline-rebase/codex-review-plan.md:3055:    Семантика ``_role_can_spawn``:
./docs/tasks/pipeline-rebase/codex-review-plan.md:3061:    wl = manager._role_can_spawn(parent)
./docs/tasks/pipeline-rebase/codex-review-plan.md:3078:        """После B1: worker / full-cycle (нет can_spawn в upstream → unlimited)
./docs/tasks/pipeline-rebase/codex-review-plan.md:3081:            assert manager._role_can_spawn(parent) is None  # upstream: поля нет
./docs/tasks/pipeline-rebase/codex-review-plan.md:3086:        """reviewer / watcher (can_spawn: [] в upstream) — терминалы, не спавнят."""
./docs/tasks/pipeline-rebase/codex-review-plan.md:3088:            assert manager._role_can_spawn(parent) == []
./docs/tasks/pipeline-rebase/codex-review-plan.md:3141:    загружается нашим loader'ом и сверяется по roles/can_spawn/model/modules/tg.
./docs/tasks/pipeline-rebase/codex-review-plan.md:6592:394-        # TestCanSpawn проверяет LEGACY-fallback (_role_can_spawn по frontmatter),
./docs/tasks/pipeline-rebase/codex-review-plan.md:6779:724-        """Оркестратор pm-glava видит каталог только pm-fichi+secretary (can_spawn)."""
./docs/tasks/pipeline-rebase/codex-review-plan.md:6821:772-    def test_star_can_spawn_shows_all(self, tmp_path, monkeypatch):
./docs/tasks/pipeline-rebase/codex-review-plan.md:6822:773-        """can_spawn=['*'] → каталог показывает ВСЕ роли пайплайна."""
./docs/tasks/pipeline-rebase/codex-review-plan.md:6828:782-            "  b: {kind: worker, label: B, order: 2, can_spawn: []}\n"
./docs/tasks/pipeline-rebase/codex-review-plan.md:6854:810-        """pm-glava НЕ может спавнить coder (нет в can_spawn) — ValueError ДО worktree."""
./docs/tasks/pipeline-rebase/codex-review-plan.md:6874:851-        """pm-glava МОЖЕТ спавнить secretary (в can_spawn)."""
./docs/tasks/pipeline-rebase/codex-review-plan.md:6892:871:        """Нет манифеста → validate_spawn кидает FileNotFoundError → fallback _role_can_spawn.
./docs/tasks/pipeline-rebase/codex-review-plan.md:6915:894-        (prompts / "roles" / "boss.md").write_text("---\nname: boss\ncan_spawn: [worker]\n---\nB")
./docs/tasks/pipeline-rebase/codex-review-plan.md:7474:   PR tests and fallback code reference `manager._read_prompt`, `_role_can_spawn`, `_parse_role_frontmatter`, `_UPSTREAM_ROLE_SYSTEM_PROMPT`, etc. If main’s `prompting.py` is the implementation, keep compatibility wrappers in `manager.py` or update all tests/callers.
./docs/tasks/pipeline-rebase/codex-review-plan.md:7511:   PR tests and fallback code reference `manager._read_prompt`, `_role_can_spawn`, `_parse_role_frontmatter`, `_UPSTREAM_ROLE_SYSTEM_PROMPT`, etc. If main’s `prompting.py` is the implementation, keep compatibility wrappers in `manager.py` or update all tests/callers.
./docs/tasks/debate-test/codex_architecture.md:36:Контраргумент: `SessionManager` действительно крупный, но основная сложность в `create_session()` является orchestration boundary, а не случайным мусором. Создание сессии связывает в один атомарный поток: normalize scope/cwd/model, уникальность имени, role resolution, owned_dirs conflicts, prompt composition, parent resolution, `can_spawn`, TG topic default, MCP config, backend type, initial DB save, task status update, optional dirty auto-commit, worktree creation, skill injection, branch-aware prompt formatting, idle callback, second DB save, session start, registry insert и rollback worktree/DB on failure (`app/manager.py:419-536`).
./docs/tasks/debate-test/codex_architecture.md:76:`blocking:` не выделять `SpawnService` до появления тестов на create-session rollback, worktree creation, prompt formatting after branch assignment, parent/can_spawn и owned_dirs warnings.
./docs/tasks/cleanup/dead-code.md:17:| `role_can_spawn` | 11 | ✅ roles/*.md |
./docs/tasks/cleanup/dead-code.md:42:- **B (полное выпиливание, РИСК):** перенаправить `prompting.py._PROMPTS_DIR` на `pipelines/default/prompts/`, синхронизировать отсутствующие файлы (researcher/experimenter roles в app/prompts нет), проверить что get_session_prompt/get_role_icons не сломались. Большая правка, легко словить регресс. НЕ рекомендую без явного запроса.
./docs/tasks/25/plan.md:5:- **`can_spawn` ABSENT (no field) = NO restriction (allow all).**
./docs/tasks/25/plan.md:6:- **`can_spawn: []` (empty list present) = allow NOTHING (terminal role).**
./docs/tasks/25/plan.md:8:- Do NOT add `can_spawn` to orchestrator.md (leave absent = allow all).
./docs/tasks/25/plan.md:11:| parent `can_spawn` | meaning | child allowed? |
./docs/tasks/25/plan.md:18:The distinction "absent vs empty list" requires reading the raw frontmatter dict. **Codex caught a sharp edge:** `meta.get("can_spawn", None)` does NOT distinguish "field absent" from "field present but YAML null" (`can_spawn:` with no value → `yaml.safe_load` gives `{"can_spawn": None}`). Must use **`"can_spawn" not in meta`** to detect absence. YAML null and malformed (non-list) values → fail-open (unrestricted), with a warning.
./docs/tasks/25/plan.md:21:`can_spawn` is an **advisory guardrail**, not a security boundary. `parent_name` arrives from the caller (MCP `spawn_worker` sends `WORKER_NAME`; `/api/sessions` is internal-token-gated). A malicious caller could spoof a permissive parent — but the threat model is a single trusted operator + local MCP processes, so this is acceptable. Documented here so future-readers don't mistake it for enforcement. (Codex #25-2 — acknowledged, by design.)
./docs/tasks/25/plan.md:28:def _role_can_spawn(role: str):
./docs/tasks/25/plan.md:29:    """Return the can_spawn whitelist for a role, or None if unrestricted.
./docs/tasks/25/plan.md:38:    if "can_spawn" not in meta:
./docs/tasks/25/plan.md:40:    val = meta["can_spawn"]
./docs/tasks/25/plan.md:42:        # YAML null (`can_spawn:`) or malformed -> fail-open (unrestricted)
./docs/tasks/25/plan.md:43:        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
./docs/tasks/25/plan.md:51:# Validate parent's can_spawn whitelist (fail-open if parent unknown)
./docs/tasks/25/plan.md:55:        whitelist = _role_can_spawn(parent_role)
./docs/tasks/25/plan.md:86:**Edge:** if the caller is the top-level orchestrator, `parent_name=WORKER_NAME` = orchestrator name. `_resolve_role` finds it → role "orchestrator" → no `can_spawn` field → unrestricted. Correct. If the orchestrator session somehow isn't in DB yet, `_resolve_role` returns None → fail-open. Correct.
./docs/tasks/25/plan.md:89:- Do NOT add `can_spawn` to any existing role file.
./docs/tasks/25/plan.md:95:1. `test_no_can_spawn_field_allows_any` — parent role file without can_spawn → child spawns OK. (Use a temp role file via monkeypatching `_PROMPTS_DIR`, OR test `_role_can_spawn` returns None directly + a create_session integration test using existing orchestrator role.)
./docs/tasks/25/plan.md:96:2. `test_empty_can_spawn_blocks_all` — parent with `can_spawn: []` → ValueError.
./docs/tasks/25/plan.md:97:3. `test_whitelist_allows_listed` — parent `can_spawn: [worker]`, child `worker` → OK.
./docs/tasks/25/plan.md:98:4. `test_whitelist_blocks_unlisted` — parent `can_spawn: [worker]`, child `full-cycle` → ValueError.
./docs/tasks/25/plan.md:100:6. Unit-test `_role_can_spawn` directly for absent / YAML-null / [] / [list] / non-list by writing temp role .md files into a patched roles dir. Explicitly cover the `can_spawn:` (null) case → returns None (unrestricted).
./docs/tasks/25/plan.md:102:**Test strategy for role files:** monkeypatch `app.manager._PROMPTS_DIR` to a tmp dir with custom `roles/*.md`, OR add a focused unit test that calls `_role_can_spawn` with files written to a patched dir. For the create_session integration, seed a parent session in DB with a known role and patch the role file.
./docs/tasks/25/plan.md:107:- Malformed `can_spawn` (string instead of list) → fail-open (return None). Defensible: don't block spawns on a typo'd role file.
./docs/tasks/cleanup/app-prompts-refactor-plan.md:14:- **roles/**: pipeline имеет 6 ролей (+ researcher, experimenter), app/prompts — 4. Superset.
./docs/tasks/cleanup/app-prompts-refactor-plan.md:33:Все 12 функций (read_prompt, role_prompt_file, role_can_spawn, skills_catalog, roles_catalog, get_role_icons, inject_skills_to_worktree, _load_modules, prompt_template_hash) теперь читают pipeline. Никаких других правок в prompting.py — они уже используют константы.
./docs/tasks/25/research.md:4:Add `can_spawn: [role1, role2]` to role YAML frontmatter. On `spawn_worker`, validate that the **parent** (spawner) role is allowed to spawn the **child** role. Empty/absent `can_spawn` = anything allowed.
./docs/tasks/25/research.md:31:- `app/prompts/roles/orchestrator.md` — add `can_spawn` (e.g. all worker roles). Actually orchestrator should be able to spawn anything → leave `can_spawn` absent (= allow all), OR list explicitly. Per spec, absent = allow all, so orchestrator needs no change unless we want to restrict.
./docs/tasks/25/research.md:33:  - New helper `_role_can_spawn(role) -> list[str] | None` reading `can_spawn` from frontmatter.
./docs/tasks/25/research.md:34:  - In `create_session`: after resolving parent, if parent has a role with non-empty `can_spawn` and child `role` not in it → raise `ValueError`.
./docs/tasks/25/research.md:39:- **Parent not found** (no parent_name resolvable, e.g. top-level orchestrator spawn): can't determine parent role → **allow** (fail-open). Spec says empty/absent can_spawn = allow; absent parent should also not block.
./docs/tasks/25/research.md:40:- **Parent role file missing** `can_spawn` → allow all.
./docs/tasks/25/research.md:41:- **Empty list `can_spawn: []`** — spec says "Пустой can_spawn ... = разрешено всё". So `[]` = allow all (treat empty list same as absent). Confirmed by spec wording.
./docs/tasks/25/research.md:44:- **Existing spawn flow must not break**: orchestrator (no can_spawn) spawning worker/full-cycle must still work → fail-open covers it.
./docs/tasks/25/research.md:45:- **API consistency**: `create_session` is also called directly (not just via spawn_worker) — e.g. orchestrator creation, tests. Those pass no parent or a parent without can_spawn → allowed. Good.
./docs/tasks/25/research.md:51:Option A: `spawn_worker` sends `parent_name=WORKER_NAME`; `create_session` resolves parent role and validates `can_spawn`. Fail-open when parent role unknown or `can_spawn` empty/absent. Add a `_role_can_spawn` helper mirroring `_load_role_skills`.
./docs/tasks/cleanup/roles-plan.md:25:## 2. Судьба researcher / experimenter → **УДАЛИТЬ** (их суть в фазе 1)
./docs/tasks/cleanup/roles-plan.md:28:- Юзер хочет ОДИН мультиинструмент. researcher/experimenter суть = фаза 1 super-full-cycle.
./docs/tasks/cleanup/roles-plan.md:30:- Убираем из pipeline.yaml + удаляем roles/researcher.md, roles/experimenter.md.
./docs/tasks/cleanup/roles-plan.md:130:Удалить роли researcher + experimenter:
./docs/tasks/cleanup/roles-plan.md:133:#   researcher: {kind: worker, ...}
./docs/tasks/cleanup/roles-plan.md:134:#   experimenter: {kind: worker, ...}
./docs/tasks/cleanup/roles-plan.md:137:Проверить `can_spawn` списки оркестраторов — если researcher/experimenter в них перечислены, убрать (иначе оркестратор попробует спавнить несуществующую роль).
./docs/tasks/cleanup/roles-plan.md:140:- `pipelines/default/prompts/roles/researcher.md`
./docs/tasks/cleanup/roles-plan.md:141:- `pipelines/default/prompts/roles/experimenter.md`
./docs/tasks/cleanup/roles-plan.md:147:1. **can_spawn ссылки** — грепнуть researcher/experimenter в pipeline.yaml can_spawn, убрать.
./docs/tasks/cleanup/roles-plan.md:148:2. **Активные сессии researcher/experimenter** — их промпт в DB, доиграют. Новые спавны → full-cycle.
./docs/tasks/cleanup/roles-plan.md:150:4. **Оркестратор-промпт** — если он инструктирует «для research спавни researcher» — обновить на «спавни full-cycle, фаза 1». Грепнуть modules/orchestration.md.
./docs/tasks/cleanup/roles-plan.md:156:- **can_spawn**: все роли в default = `can_spawn: ["*"]` (wildcard). Удаление researcher/experimenter из `roles:` НЕ оставит битых ссылок. ✅
./docs/tasks/cleanup/roles-plan.md:157:- **orchestration.md**: упоминает «researcher» только описательно («you are NOT a researcher»), НЕ как спавн-инструкцию. Правка не нужна. ✅
./docs/tasks/cleanup/roles-plan.md:158:- **researcher/experimenter в pipeline.yaml**: строки 74-96 (полные определения ролей) — удалить.
./docs/tasks/cleanup/roles-plan.md:162:2. researcher/experimenter — удаляем (моя рекомендация, суть в фазе 1) или оставить лёгкий researcher для чистого гугла?
./docs/archive/research/tg-flood-fix.md:4:**Researcher**: usage-researcher agent
./docs/archive/research/usage-status-bar.md:4:**Researcher**: usage-researcher agent
./docs/tasks/cleanup/roles-analysis.md:1:# Роли: researcher / experimenter / full-cycle — объединять?
./docs/tasks/cleanup/roles-analysis.md:9:**Вопрос юзера:** можно ли объединить в мультиинструмент? Чтобы researcher СРАЗУ после approve делал implement + codex (не только research).
./docs/tasks/cleanup/roles-analysis.md:17:| **researcher** | ЗНАНИЯ (не код). Каждый факт = источник. | scope&search → verify&cross-check → synthesize. Пишет docs/research/*.md | Web-поиск + **counter-evidence** + confidence HIGH/MED/LOW. Верификация 2+ источника. НЕ трогает код. |
./docs/tasks/cleanup/roles-analysis.md:18:| **experimenter** | ДАННЫЕ из прогонов (числа). | hypothesis → experiment → conclusion. 1 гейт. Пишет docs/experiments/*/ | **Эмпирика**: прогнать, замерить, 2-3 итерации, pass/fail ДО прогона (анти-p-hacking). Temp-файлы, не прод. |
./docs/tasks/cleanup/roles-analysis.md:27:### researcher Phase 1 (research) vs full-cycle Phase 1 (research) — РАЗНЫЕ:
./docs/tasks/cleanup/roles-analysis.md:28:- researcher research = **внешние знания**: WebSearch, counter-evidence, источники с датами, confidence-уровни. Цель — узнать ПРАВДУ о мире/технологии.
./docs/tasks/cleanup/roles-analysis.md:30:→ Оба называются «research», но это разные активности. Слить = потерять специфику (researcher-промпт учит верификации источников, full-cycle — чтению кода).
./docs/tasks/cleanup/roles-analysis.md:32:### experimenter — УНИКАЛЕН:
./docs/tasks/cleanup/roles-analysis.md:33:Эмпирические замеры (прогнать N раз, числа, pass/fail заранее) — ни researcher (тот читает, не прогоняет), ни full-cycle (тот кодит фичу) этого не делают. Это отдельная дисциплина (benchmark/proof).
./docs/tasks/cleanup/roles-analysis.md:53:Спавнишь full-cycle с mode → стоп после research ИЛИ research+implement. researcher/experimenter удаляются как режимы.
./docs/tasks/cleanup/roles-analysis.md:55:- ➖ **ЛОМАЕТ специфику**: researcher-верификация источников и experimenter-замеры — это НЕ «фаза full-cycle», а другой тип работы с другими правилами (counter-evidence, p-hacking guard). Впихнуть в full-cycle = либо раздуть его промпт до нечитаемости, либо потерять эти правила.
./docs/tasks/cleanup/roles-analysis.md:57:- ➖ researcher output = docs/research (знания), full-cycle = код. Разные артефакты в одном промпте = путаница.
./docs/tasks/cleanup/roles-analysis.md:60:- ➕ **determinism**: каждая роль = один жёсткий маршрут, один тип output. Оркестратор выбирает роль по задаче (research → researcher, замер → experimenter, фича → full-cycle) — это ЕГО решение на спавне, не развилка внутри агента.
./docs/tasks/cleanup/roles-analysis.md:74:3. full-cycle уже мультифазный — этого достаточно для «сделать всё от research до кода». researcher/experimenter — для случаев где output НЕ код (юзер хочет знания или замеры, а не фичу).
./docs/tasks/cleanup/roles-analysis.md:76:### Про исходный запрос юзера («researcher сразу implement после approve»)
./docs/tasks/cleanup/roles-analysis.md:77:Если нужно «поресёрчил → сразу закодил» — это **уже есть = full-cycle** (research→plan→implement→codex). researcher существует для случаев где implement НЕ нужен (чистое знание: «какой прокси не блокирует РКН», «сравни подходы»). Смешивать не нужно — для «research+code» бери full-cycle, для «только знания» — researcher.
./docs/tasks/cleanup/roles-analysis.md:82:Минимальный компромисс: убрать **experimenter** ТОЛЬКО если он реально не используется (проверить историю спавнов). researcher + full-cycle покрывают 95% случаев. Но это отдельное решение по данным использования, не по «дублированию» (его нет).

codex
Нашёл одно важное место вне `pipeline.yaml`: `CLAUDE.md` всё ещё описывает `researcher` и `experimenter` как актуальные роли. Это не `can_spawn`, но для спавна через текстовые инструкции может быть реальной осиротевшей подсказкой, поэтому проверю точные строки и валидацию манифеста.
exec
/usr/bin/zsh -lc 'git status --short' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
 M CLAUDE.md
M  pipelines/default/pipeline.yaml
D  pipelines/default/prompts/roles/experimenter.md
M  pipelines/default/prompts/roles/full-cycle.md
D  pipelines/default/prompts/roles/researcher.md
M  tests/test_default_pipeline.py

exec
/usr/bin/zsh -lc "rg -n \"\\b(researcher|experimenter)\\b\" CLAUDE.md pipelines/default/prompts pipelines/default/pipeline.yaml tests --glob '"'!**/.git/**'"'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
CLAUDE.md:167:- `experimenter` — hypothesis → experiment → measure → conclude. Opus 4.8
CLAUDE.md:168:- `researcher` — search → verify → synthesize. Web research with counter-evidence. Opus 4.8
pipelines/default/prompts/modules/orchestration.md:16:- **Content/research/writing** (playbook, spec, report, analysis) → ALWAYS delegate to a specialist worker. You are NOT a writer, researcher, or domain expert. You are a manager — decompose, assign, verify. Even if you "know" the answer, a dedicated worker with web search and full context will produce better results

exec
/usr/bin/zsh -lc "nl -ba pipelines/default/pipeline.yaml | sed -n '55,82p' && nl -ba pipelines/default/prompts/roles/full-cycle.md | sed -n '1,150p' && nl -ba CLAUDE.md | sed -n '150,176p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
    55	    when: Clear task for a known module, implementation from detailed spec, bug fix with known repro
    56	    not_for: Tasks needing research or unknown scope — use full-cycle
    57	    description: >
    58	      General-purpose worker. Implements tasks directly, no pipeline gates.
    59	      For system workers (permanent, module-scoped) and disposable one-shots.
    60	  full-cycle:
    61	    kind: worker
    62	    label: Full-Cycle
    63	    order: 3
    64	    model: opus4.8
    65	    skills: [codex-debate]
    66	    modules: [git-workflow, report-format, self-improvement]
    67	    can_spawn: ["*"]
    68	    allow_unrouted_workers: false
    69	    when: New feature with unknowns, large refactoring (5+ files), external integration, deep research (find out everything about X), empirical measurement / benchmarks, anything where wrong approach = wasted day
    70	    not_for: Trivial bug fixes, config changes, one-line implementation from a clear spec
    71	    description: >
    72	      Research+Experiment (truth from sources AND measurements) → Plan sliced into
    73	      tickets with acceptance criteria → Implement ticket-by-ticket. Strict 3-phase
    74	      pipeline, 2 orchestrator approval gates, Codex review at plan + impl. For a
    75	      research-only task the orchestrator simply stops after Phase 1. All artifacts
    76	      in docs/tasks/<id>/.
     1	<role>
     2	## Role: Full-Cycle Worker
     3	
     4	You are a senior engineer who takes a task from truth-finding to shipped code.
     5	You follow a STRICT 3-phase pipeline with approval gates. Do NOT skip phases.
     6	Do NOT freestyle. The orchestrator drives you phase-by-phase — you never pick
     7	the phase yourself, you execute the current one fully and STOP at the gate.
     8	</role>
     9	
    10	<pipeline>
    11	## Pipeline — 3 phases, gates after 1 and 2
    12	
    13	### Phase 1: RESEARCH + EXPERIMENT (find the TRUTH)
    14	Goal: not opinions — verified truth. Theory (sources) AND practice (measurements),
    15	as the task demands. The orchestrator's task says what's needed: "sources only",
    16	"needs measurements", or both. Do exactly that.
    17	
    18	**Investigate (theory):**
    19	1. Read existing code the task touches (grep/read — understand before proposing)
    20	2. Search when external knowledge is needed (WebSearch/WebFetch) — prior art, docs,
    21	   API refs. Specify date ranges ("since 2025"). Read primary sources, not summaries.
    22	3. Cross-check: for every key claim find a SECOND source. Actively seek counter-evidence.
    23	
    24	**Experiment (practice) — when the task needs empirical proof:**
    25	4. State the hypothesis: "X causes Y because Z". Define metrics + pass/fail BEFORE running.
    26	5. Run it — temp files / /tmp / test scripts, NEVER production. 2-3 iterations for confidence.
    27	6. Record raw data (numbers, outputs, errors). Don't move goalposts after seeing results.
    28	
    29	**Synthesize:**
    30	7. Write `docs/tasks/<task-id>/research.md`:
    31	   - Question / what's being answered
    32	   - Findings — with inline sources [1][2] AND/OR measured numbers
    33	   - Confidence: CONFIRMED (proven/multi-source) / LIKELY / UNCERTAIN / REFUTED
    34	   - Counter-evidence — what argues against
    35	   - Affected files, risks, edge cases (for the code to come)
    36	8. Report: `RESEARCH DONE #<id>: <2-3 sentence truth + confidence>. docs/tasks/<id>/research.md. Awaiting approval to plan.`
    37	9. **STOP. Wait for approval.**
    38	
    39	### Phase 2: PLAN → slice into tickets (AC) + Codex review
    40	1. Write `docs/tasks/<task-id>/plan.md`: what changes in which files (functions/classes),
    41	   new files, migration notes, what NOT to touch.
    42	2. **Slice the plan into vertical tickets** (tracer-bullet style — not horizontal layers).
    43	   Each ticket is a self-contained unit of work that Phase 3 implements in a clean pass:
    44	   - **Vertical slice**: end-to-end thin cut (e.g. "add field + endpoint + test"), NOT
    45	     "all DB changes" then "all API changes". Each ticket ships something verifiable.
    46	   - **AC (acceptance criteria)**: concrete, checkable conditions that prove the ticket done
    47	     ("returns 404 on missing id", "old rows resume without error"). Phase 3 self-verifies against these.
    48	   - **blocked-by**: list ticket ids this one depends on (ordering). No cycles.
    49	   Write tickets in `docs/tasks/<task-id>/plan.md` under `## Tickets`:
    50	   ```
    51	   ### T1 — <short title>
    52	   - Files: <files touched>
    53	   - AC: <checkable criteria>
    54	   - blocked-by: none
    55	   ### T2 — <short title>
    56	   - AC: ...
    57	   - blocked-by: T1
    58	   ```
    59	   (These are plan-internal slices, not GitHub issues — Orchestra has its own Task Manager.)
    60	3. Codex review the plan + tickets (codex-debate skill Quick Review). Fix issues, document disagreements.
    61	4. Report: `PLAN READY #<id>: <approach>, N tickets. Plan + Codex in docs/tasks/<id>/. Awaiting approval.`
    62	5. **STOP. Wait for approval.**
    63	
    64	### Phase 3: IMPLEMENT ticket-by-ticket + Codex review
    65	1. Implement tickets in `blocked-by` order. Take ONE ticket at a time to keep context lean.
    66	2. After each ticket: check it against its AC (self-verify). If AC fails — fix before moving on.
    67	3. Test: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
    68	4. Codex review the git diff. Fix CRITICAL/HIGH, re-run if needed.
    69	5. Commit (one clean commit, or per-ticket if large): `#<task-id>: <what you did>`.
    70	6. Write `docs/tasks/<task-id>/report.md` (what, files ±lines, tickets done, tests, breaking, TODOs).
    71	7. Report DONE (report-format module) + "Codex approved. Report in docs/tasks/<id>/report.md".
    72	</pipeline>
    73	
    74	<artifacts>
    75	## Task documentation structure
    76	```
    77	docs/tasks/<task-id>/
    78	├── research.md          — Phase 1: truth (sources + measurements), affected files, risks
    79	├── plan.md              — Phase 2: what/how/which files + ## Tickets (slices with AC + blocked-by)
    80	├── codex-review-plan.md — Phase 2: Codex on the plan
    81	├── codex-review-impl.md — Phase 3: Codex on the impl
    82	└── report.md            — Phase 3: final report
    83	```
    84	</artifacts>
    85	
    86	<rules priority="critical">
    87	## Research+Experiment rules (Phase 1)
    88	- NEVER state a fact without a source OR a measurement — "I think" is not truth
    89	- NEVER stop at the first result — seek counter-evidence
    90	- NEVER change pass/fail criteria after seeing results (p-hacking)
    91	- NEVER experiment on production code — temp/tmp/test scripts only, clean up after
    92	- Flag stale info ("as of 2024, may have changed"); if sources conflict, present BOTH
    93	
    94	## Ticketing rules (Phase 2)
    95	- Slices are VERTICAL (thin end-to-end cuts), never horizontal layers — each ships something testable
    96	- Every ticket has concrete AC — vague AC ("works well") is useless; make it checkable
    97	- blocked-by must be acyclic; implement in dependency order
    98	
    99	## Pipeline rules
   100	- NEVER skip a phase. NEVER proceed without approval after Phase 1 and 2 — STOP and wait.
   101	  Exception: orchestrator says "don't wait" → skip the idle-gate but still do ALL phase work.
   102	- Codex review MANDATORY for complex tasks (5+ files, security, architecture, integrations).
   103	  Skip only on trivial (<50 lines, 1 function). Never claim a review ran without its output.
   104	- All findings → files (docs/tasks/<id>/), not just chat.
   105	- If research reveals the task is wrong/unnecessary — say so, don't proceed blindly.
   106	</rules>
   107	
   108	<code-quality>
   109	## Code quality
   110	
   111	**Think before coding.** State your assumptions. If multiple interpretations exist — ask, don't pick silently. If there's a simpler solution — say so. If the orchestrator's spec has a flaw — push back.
   112	
   113	**Adversarial self-review.** Before committing, find 2-3 potential bugs or weak spots in your own code. Fix them or flag them in your report.
   114	
   115	**Simplicity first.**
   116	- Minimum code that solves the task. Nothing speculative
   117	- No features beyond request. No abstractions for one-off code
   118	- No comments except WHY (not WHAT), non-obvious decisions, docstrings on public API
   119	- 200 lines where 50 suffice → rewrite
   120	
   121	**Surgical changes.** Touch ONLY what the task requires.
   122	- Don't "improve" neighboring code, formatting, comments
   123	- Don't refactor what isn't broken. Follow existing style
   124	- Noticed dead code → mention, don't delete unless your changes orphaned it
   125	
   126	**Pit of success.** Code where screwing up is hard.
   127	- Flat structure, minimal indirection. Reads top to bottom
   128	- One task = one pattern. Not two helpers for the same thing
   129	- Explicit > implicit. No magic, no hidden side effects
   130	- Fail loud — crash > silent bug. Errors must be visible immediately
   131	- 3 duplicate lines > premature abstraction
   132	</code-quality>
   150	- GitHub Actions CI (pytest on push), 522 tests pass
   151	- app.js split: 5303→4489 lines, 3 leaf modules extracted (utils, tool-renderers, usage)
   152	- 9 Playwright smoke tests
   153	- Currency symbol from .env (CURRENCY_SYMBOL, default ₽)
   154	- Pipeline-as-config (Вадим PR #2) merged and rebased
   155	
   156	### Seedon enterprise fork
   157	- Safety prompt (SAFETY_PREFIX) — was in main, REVERTED. Lives in private fork orchestra-enterprise
   158	- Per-role lean tools — was in main, REVERTED. Will return when coding-worker role exists
   159	
   160	## Session notes (2026-06-11 to 2026-06-16)
   161	
   162	### Major refactoring
   163	- **P0-P4 full codebase refactor** (Fable 5 full-cycle, $33): session.py split → CostTracker/TurnManager/HibernateManager; main.py 1574→91 lines; 3 circular deps cut; 34 isinstance killed; 487 tests green
   164	- **tg_bridge split** — refactor-tg worker (Opus 4.8) in progress, research+plan done, awaiting impl
   165	
   166	### New roles
   167	- `experimenter` — hypothesis → experiment → measure → conclude. Opus 4.8
   168	- `researcher` — search → verify → synthesize. Web research with counter-evidence. Opus 4.8
   169	- Both in `pipelines/default/pipeline.yaml` + `prompts/roles/`
   170	
   171	### Key features
   172	- **4-level cost**: turn/ctx/session/total. ctx persisted in DB (survives reboot), session = in-memory only
   173	- **Worker persistent memory** (#81): `docs/workers/{name}.md` auto-injects into prompt on spawn/resume
   174	- **Dynamic model list**: `available_models_block()` from models.py → orchestrator prompts
   175	- **Prompt visualization** (#77, #80): dashboard shows prompt blocks by source (file/module/dynamic/skill)
   176	- **TG topic toggle**: right-click agent → toggle TG topic

exec
/usr/bin/zsh -lc "UV_CACHE_DIR=/tmp/uv-cache uv run python - <<'PY'
from app.pipeline import load_pipeline
cfg = load_pipeline('default')
print(sorted(cfg.roles))
PY" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 312ms:
['full-cycle', 'orchestrator', 'sub-orchestrator', 'worker']

codex
Валидация `load_pipeline('default')` проходит, роли сейчас только `full-cycle`, `orchestrator`, `sub-orchestrator`, `worker`. Осталось оценить, не сломаны ли тестовые ожидания и нет ли скрытой GitHub-специфики/развилки в формулировках.
exec
/usr/bin/zsh -lc 'git diff -- tests/test_default_pipeline.py CLAUDE.md' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
diff --git a/CLAUDE.md b/CLAUDE.md
index 83aa499..be90334 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -245,6 +245,7 @@ Every feature should minimize agent overhead: fewer tool calls, less context was
 - **Don't auto-approve implementation** — user asked about self-learning, I approved impl without permission. Rule: ASK before approving large implementations
 - **Orchestrators delegate content** — sales playbook, user guides = specialist workers, not orchestrator
 - **Dynamic Workflows blocked** — Claude Code's built-in Workflow tool blocked for all agents (wastes tokens, MCP tools don't propagate)
+- **«Мёртвый код» → грепни РЕАЛЬНЫЕ чтения перед удалением** — разведка сказала «app/prompts мёртвая» (грепнули строку `app/prompts`, нашли только комменты). Но `prompting.py._PROMPTS_DIR` читал её через 12 функций — это был живой fallback + дашборд-визуализация. Правило: перед удалением папки/модуля грепни кто РЕАЛЬНО импортит/читает (не строковые совпадения), проверь fallback-пути. Перепроверка спасла дашборд от поломки
 
 ## BUGS.md — баг-репорты от агентов
 - Агенты (оркестраторы и воркеры) могут вызывать `report_bug(title, description)` MCP tool

exec
/usr/bin/zsh -lc 'UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_default_pipeline.py -q' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 exited 1 in 2455ms:
............F.F..................F........                               [100%]
=================================== FAILURES ===================================
__________ TestDefaultRolesResolve.test_modules_resolve_from_manifest __________

self = <tests.test_default_pipeline.TestDefaultRolesResolve object at 0x74c11ff0cd40>

    def test_modules_resolve_from_manifest(self):
        """modules пробрасываются из манифеста в ResolvedRole без слияния с defaults."""
>       assert P.get_role(PIPELINE, "orchestrator").modules == ["git-workflow", "orchestration"]
E       AssertionError: assert ['git-workflo...-improvement'] == ['git-workflo...rchestration']
E         
E         Left contains 3 more items, first extra item: 'background-jobs'
E         Use -v to get more diff

tests/test_default_pipeline.py:129: AssertionError
________ TestDefaultRolesResolve.test_orchestrator_skills_from_manifest ________

self = <tests.test_default_pipeline.TestDefaultRolesResolve object at 0x74c11ff0d5e0>

    def test_orchestrator_skills_from_manifest(self):
        rr = P.get_role(PIPELINE, "orchestrator")
>       assert set(rr.skills) == {"html-artifacts", "vps-deploy", "codex-debate"}
E       AssertionError: assert {'codex-debat... 'vps-deploy'} == {'codex-debat... 'vps-deploy'}
E         
E         Extra items in the left set:
E         'grill-me'
E         Use -v to get more diff

tests/test_default_pipeline.py:139: AssertionError
_ TestUpstreamCharacterization.test_build_prompt_matches_concatenation_of_layers _

self = <tests.test_default_pipeline.TestUpstreamCharacterization object at 0x74c11ff1d1f0>

    def test_build_prompt_matches_concatenation_of_layers(self):
        """build_system_prompt(orchestrator) = base.md + role + modules."""
        base = P.prompt_path(PIPELINE, "base.md").read_text()
        role = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text()
        git = P.prompt_path(PIPELINE, "modules/git-workflow.md").read_text().strip()
        orch = P.prompt_path(PIPELINE, "modules/orchestration.md").read_text().strip()
        expected = f"{base}\n\n{role}\n\n{git}\n\n{orch}"
>       assert P.build_system_prompt(PIPELINE, "orchestrator") == expected
E       AssertionError: assert '<platform>\n...-improvement>' == '<platform>\n...rchestration>'
E         
E         Skipping 20004 identical leading characters in diff, use -v to show
E         - hestration>
E         + hestration>
E         ?            +
E         + 
E         + <background-jobs>...
E         
E         ...Full output truncated (78 lines hidden), use '-vv' to show

tests/test_default_pipeline.py:299: AssertionError
=========================== short test summary info ============================
FAILED tests/test_default_pipeline.py::TestDefaultRolesResolve::test_modules_resolve_from_manifest
FAILED tests/test_default_pipeline.py::TestDefaultRolesResolve::test_orchestrator_skills_from_manifest
FAILED tests/test_default_pipeline.py::TestUpstreamCharacterization::test_build_prompt_matches_concatenation_of_layers
3 failed, 39 passed in 1.73s

codex
Фокусированный тест по default pipeline сейчас красный: 3 падения про старые ожидания по modules/skills оркестратора, не про удалённые роли. В ревью отделю это от вопроса про `researcher/experimenter`, чтобы не смешивать регресс маршрутизации и уже существующую/соседнюю несинхронность тестов.
exec
/usr/bin/zsh -lc "nl -ba tests/test_default_pipeline.py | sed -n '116,146p;288,304p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
   116	        assert rr.model == "opus4.8"
   117	
   118	    def test_sub_orchestrator_is_orchestrator_opus(self):
   119	        """sub-orchestrator — kind:orchestrator, opus, can_spawn=['*']."""
   120	        rr = P.get_role(PIPELINE, "sub-orchestrator")
   121	        assert rr is not None
   122	        assert rr.is_orchestrator is True
   123	        assert rr.model == "opus"
   124	        assert rr.can_spawn == ["*"]
   125	        assert rr.allow_unrouted_workers is True
   126	
   127	    def test_modules_resolve_from_manifest(self):
   128	        """modules пробрасываются из манифеста в ResolvedRole без слияния с defaults."""
   129	        assert P.get_role(PIPELINE, "orchestrator").modules == ["git-workflow", "orchestration"]
   130	        assert P.get_role(PIPELINE, "sub-orchestrator").modules == ["git-workflow", "orchestration"]
   131	        assert P.get_role(PIPELINE, "worker").modules == ["git-workflow", "report-format"]
   132	        assert P.get_role(PIPELINE, "full-cycle").modules == ["git-workflow", "report-format"]
   133	
   134	    def test_tg_emoji_for_v216_roles(self):
   135	        assert P.get_role(PIPELINE, "sub-orchestrator").tg.emoji == "🎯"
   136	
   137	    def test_orchestrator_skills_from_manifest(self):
   138	        rr = P.get_role(PIPELINE, "orchestrator")
   139	        assert set(rr.skills) == {"html-artifacts", "vps-deploy", "codex-debate"}
   140	
   141	    def test_orchestrator_can_spawn_wildcard_and_unrouted(self):
   142	        """Апстрим не ограничивает оркестратора: can_spawn=['*'], дефолтный
   143	        role='worker'/пустая роль допустима."""
   144	        rr = P.get_role(PIPELINE, "orchestrator")
   145	        assert rr.can_spawn == ["*"]
   146	        assert rr.allow_unrouted_workers is True
   288	            text = P.prompt_path(PIPELINE, f"skills/{skill}.md").read_text()
   289	            assert text.lstrip().startswith("---"), f"{skill}.md must keep frontmatter"
   290	            assert f"name: {skill}" in text
   291	
   292	    def test_build_prompt_matches_concatenation_of_layers(self):
   293	        """build_system_prompt(orchestrator) = base.md + role + modules."""
   294	        base = P.prompt_path(PIPELINE, "base.md").read_text()
   295	        role = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text()
   296	        git = P.prompt_path(PIPELINE, "modules/git-workflow.md").read_text().strip()
   297	        orch = P.prompt_path(PIPELINE, "modules/orchestration.md").read_text().strip()
   298	        expected = f"{base}\n\n{role}\n\n{git}\n\n{orch}"
   299	        assert P.build_system_prompt(PIPELINE, "orchestrator") == expected
   300	
   301	
   302	# ── validate_spawn: fail-open + can_spawn=['*'] + allow_unrouted_workers ────
   303	
   304	class TestDefaultValidateSpawn:

exec
/usr/bin/zsh -lc "nl -ba pipelines/default/pipeline.yaml | sed -n '1,78p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-proxy
 succeeded in 0ms:
     1	name: default
     2	description: Upstream pipeline v2.18 (orchestrator / sub-orchestrator / worker / full-cycle). Behaviour 1:1 with mccalpink/orchestra main.
     3	validation: fail-open
     4	defaults:
     5	  model: opus
     6	  skills: []
     7	  mcp_servers: []
     8	  inherit_claude_md: true
     9	  prompt_layers:
    10	    orchestrator: [base.md, "roles/{role}.md"]
    11	    worker:       [base.md, "roles/{role}.md"]
    12	  worktree:
    13	    symlinks: []
    14	    copies:   [CLAUDE.md, .mcp.json, .env, .worktreeinclude]
    15	  base_branch_strategy: main
    16	  docs_scaffold: false
    17	roles:
    18	  orchestrator:
    19	    kind: orchestrator
    20	    label: Orchestrator
    21	    order: 0
    22	    model: opus
    23	    skills: [html-artifacts, vps-deploy, codex-debate, grill-me]
    24	    modules: [git-workflow, orchestration, background-jobs, task-management, self-improvement]
    25	    can_spawn: ["*"]
    26	    allow_unrouted_workers: true
    27	    when: Managing a team of workers, decomposing tasks, approving plans
    28	    not_for: Direct implementation — delegate to workers
    29	    description: >
    30	      Manages worker agents. Decomposes tasks, spawns workers, reviews results.
    31	      Available worker roles are injected automatically from roles/ directory.
    32	  sub-orchestrator:
    33	    kind: orchestrator
    34	    label: Sub-Orchestrator
    35	    order: 1
    36	    model: opus
    37	    modules: [git-workflow, orchestration, background-jobs, task-management, self-improvement]
    38	    can_spawn: ["*"]
    39	    allow_unrouted_workers: true
    40	    tg: {emoji: "🎯"}
    41	    when: Managing a sub-team within a larger hierarchy (department lead, tech lead, team lead)
    42	    not_for: Direct implementation — delegate to workers
    43	    description: >
    44	      Manages a subset of workers under a parent orchestrator.
    45	      Reports up to parent, delegates down to workers.
    46	  worker:
    47	    kind: worker
    48	    label: Worker
    49	    order: 2
    50	    model: sonnet
    51	    skills: [codex-debate]
    52	    modules: [git-workflow, report-format, self-improvement]
    53	    can_spawn: ["*"]
    54	    allow_unrouted_workers: false
    55	    when: Clear task for a known module, implementation from detailed spec, bug fix with known repro
    56	    not_for: Tasks needing research or unknown scope — use full-cycle
    57	    description: >
    58	      General-purpose worker. Implements tasks directly, no pipeline gates.
    59	      For system workers (permanent, module-scoped) and disposable one-shots.
    60	  full-cycle:
    61	    kind: worker
    62	    label: Full-Cycle
    63	    order: 3
    64	    model: opus4.8
    65	    skills: [codex-debate]
    66	    modules: [git-workflow, report-format, self-improvement]
    67	    can_spawn: ["*"]
    68	    allow_unrouted_workers: false
    69	    when: New feature with unknowns, large refactoring (5+ files), external integration, deep research (find out everything about X), empirical measurement / benchmarks, anything where wrong approach = wasted day
    70	    not_for: Trivial bug fixes, config changes, one-line implementation from a clear spec
    71	    description: >
    72	      Research+Experiment (truth from sources AND measurements) → Plan sliced into
    73	      tickets with acceptance criteria → Implement ticket-by-ticket. Strict 3-phase
    74	      pipeline, 2 orchestrator approval gates, Codex review at plan + impl. For a
    75	      research-only task the orchestrator simply stops after Phase 1. All artifacts
    76	      in docs/tasks/<id>/.

codex
**Findings**

1. **Blocking-ish orphaned instruction:** `CLAUDE.md:167-169` still lists `experimenter` and `researcher` as real roles “in `pipelines/default/pipeline.yaml` + `prompts/roles/`”. Since `pipeline.yaml` has `inherit_claude_md: true` and copies `CLAUDE.md`, this can still steer agents toward spawning deleted roles. Not a `can_spawn` broken link, but it is an orphaned role reference in live agent context. Fix: remove that block or rewrite to `full-cycle Phase 1`.

2. **Tests are currently red:** `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_default_pipeline.py -q` gives 3 failures. They are not about `researcher/experimenter`; tests still expect old orchestrator modules/skills at `tests/test_default_pipeline.py:129`, `:139`, `:299`, while manifest has extra modules/skill at `pipelines/default/pipeline.yaml:23-24`. Separate from this diff, but merge-blocking if CI runs it.

**По пунктам**

1. `pipeline.yaml can_spawn`: битых ссылок на `researcher/experimenter` нет. Все default-роли используют `can_spawn: ["*"]`; `load_pipeline('default')` проходит и видит только `full-cycle`, `orchestrator`, `sub-orchestrator`, `worker`.

2. Phase 1 специфика не потеряна: есть counter-evidence/source cross-check (`full-cycle.md:22`, `:34`, `:89`) и hypothesis→metrics/pass-fail→measure (`:24-27`, `:90-91`).

3. Детерминизм в целом ок: `full-cycle.md:15-16` прямо говорит, что task от оркестратора задаёт `sources only` / `needs measurements` / both, агент “does exactly that”. Это не выглядит как самостоятельный выбор маршрута агентом.

4. Phase 2 ticketing понятен: вертикальные слайсы, AC, `blocked-by`, no cycles, dependency order. GitHub-специфики нет, даже явно сказано “not GitHub issues” (`full-cycle.md:59`).

5. Промпт не раздут критично. Он стал плотнее, но читаемый: 3 фазы, правила сгруппированы, дублирование небольшое. Единственная мелкая шероховатость: описание в `pipeline.yaml:72` говорит “sources AND measurements”, а промпт допускает source-only. Лучше заменить на “sources and/or measurements” для консистентности.
tokens used
51,748
**Findings**

1. **Blocking-ish orphaned instruction:** `CLAUDE.md:167-169` still lists `experimenter` and `researcher` as real roles “in `pipelines/default/pipeline.yaml` + `prompts/roles/`”. Since `pipeline.yaml` has `inherit_claude_md: true` and copies `CLAUDE.md`, this can still steer agents toward spawning deleted roles. Not a `can_spawn` broken link, but it is an orphaned role reference in live agent context. Fix: remove that block or rewrite to `full-cycle Phase 1`.

2. **Tests are currently red:** `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_default_pipeline.py -q` gives 3 failures. They are not about `researcher/experimenter`; tests still expect old orchestrator modules/skills at `tests/test_default_pipeline.py:129`, `:139`, `:299`, while manifest has extra modules/skill at `pipelines/default/pipeline.yaml:23-24`. Separate from this diff, but merge-blocking if CI runs it.

**По пунктам**

1. `pipeline.yaml can_spawn`: битых ссылок на `researcher/experimenter` нет. Все default-роли используют `can_spawn: ["*"]`; `load_pipeline('default')` проходит и видит только `full-cycle`, `orchestrator`, `sub-orchestrator`, `worker`.

2. Phase 1 специфика не потеряна: есть counter-evidence/source cross-check (`full-cycle.md:22`, `:34`, `:89`) и hypothesis→metrics/pass-fail→measure (`:24-27`, `:90-91`).

3. Детерминизм в целом ок: `full-cycle.md:15-16` прямо говорит, что task от оркестратора задаёт `sources only` / `needs measurements` / both, агент “does exactly that”. Это не выглядит как самостоятельный выбор маршрута агентом.

4. Phase 2 ticketing понятен: вертикальные слайсы, AC, `blocked-by`, no cycles, dependency order. GitHub-специфики нет, даже явно сказано “not GitHub issues” (`full-cycle.md:59`).

5. Промпт не раздут критично. Он стал плотнее, но читаемый: 3 фазы, правила сгруппированы, дублирование небольшое. Единственная мелкая шероховатость: описание в `pipeline.yaml:72` говорит “sources AND measurements”, а промпт допускает source-only. Лучше заменить на “sources and/or measurements” для консистентности.
