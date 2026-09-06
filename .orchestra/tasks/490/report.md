# #490 — three prompt modules merged from `task-490/prompt-engineer`, with wiring

Content-transfer onto a fresh branch from `main` (`task-520/merge-prompt-modules`).
The source branch was **not** merged: after the 03.09 layout migration it lags `main` by
thousands of files and a merge would erase live data. Files were compared by content, not path
(`pipelines/…` in the branch vs `.orchestra/pipelines/…` on `main`).

## What was transferred

Three modules created under `.orchestra/pipelines/default/prompts/modules/`:

| module | source of content | wired into |
|---|---|---|
| `communication-style.md` | `base.md` `<communication-style>` + standard rule "Respond in the same language" | all 5 roles |
| `knowledge-and-context.md` | `base.md` `<project-memory>` + 3 standard rules (persist / where knowledge goes / context economy) | all 5 roles |
| `user-values.md` | `base.md` `<user-values>` (RU→EN) + new owner values from the branch | all 5 roles |

`base.md` lost exactly those blocks (126 → 53 lines). `pipeline.yaml` gained the three module
names in `modules:` for `orchestrator`, `sub-orchestrator`, `worker`, `full-cycle` **and
`reducer`** — the reducer had `modules: []`, so without the addition it would have been the one
role that silently lost the whole conduct/values layer.

### New rules kept from the branch (this is what the task was for)

- **Restart authority** — only the owner initiates an Orchestra restart; no agent initiates or
  performs one on its own at any severity, live incident included; an agent executes one only on
  the owner's active explicit command for that exact restart.
- **Approval covers a working result, not one attempt** — a merge is not a working result, a commit
  in `main` is not a deployment check, merged Python does not run until a restart while frontend
  JS/CSS is hot; a report that merges `app/**` states the restart need in that same report
  (#220: median delay to deploy 3.3 h, p75 22.9 h).
- **The one-phrase test "Same goal, or a new one?"** with its continue-list (defect in your own
  delivered work, unfinished part of the stated goal, a change without which the result is not
  reached, another pass after a measurement) and ask-list (new goal, architectural fork, another
  project, change of spend class, anything irreversible); never ask whether to continue after a
  first pass — report the number, next pass already started.
- **Reducer scope** — its working result is the complete assigned collection and nothing beyond it.
- **No cross-project infrastructure coordination** — never warn, coordinate with, or ask other
  projects or orchestrators to spend turns on infrastructure work.
- **A proven new path completely replaces the old one** — proof first, then the old path is removed
  and all callers rewritten in the same work; no deprecated wrappers, re-exports, shims or
  just-in-case copies. External contracts get a separate decision and migration plan.
- **A criterion invented by an agent is not a requirement of the external world** — name the threat,
  the environment it protects and its price; its author withdraws it when cost exceeds protection.

## What was rejected, and why

| rejected from the branch | reason |
|---|---|
| `roles/worker.md` revert | The branch restores the old total ban on touching tests instead of `main`'s current rule about *frozen acceptance* tests. Explicit task boundary #1. `main`'s edition stays. |
| `full-cycle` `description:` revert in `pipeline.yaml` | Same class of regression: the branch reinstates the strict 3-phase / 2-gate wording that `main` has already replaced with the outcome-ownership description. |
| Moving `<background-jobs>` out of `base.md` into the module for every role | Out of scope (the task names three modules) and gains nothing: the block already reaches every role through `base.md`. Doing it would have meant touching `background-jobs` wiring for four roles for a zero-content change. |
| `- a project rule → CLAUDE.md` (branch wording in `knowledge-and-context`) | Regression against `main`, which says "a rule for the project → its canonical owner under the project authoring policy" — `AGENTS.md` is the source and `CLAUDE.md` its byte-identical mirror. `main`'s wording kept. |
| Dropping the owner's verbatim Russian quotes from `communication-style` | The branch replaced «ты нахуй пиздишь что готовишь но не делаешь блять» and «все задачи разбирать не подвисать» with a bare "(user decision, 04.09.2026)". The quotes are the anchor for those two rules; kept verbatim. |
| Branch's shortened `communication-style` details | The branch dropped "(research/plans stay full)", "or the same text sent as a user message or error is delivered normally", and "whether the file is 5 KB or 50 KB". All three restored from `main`. |
| Every other file the branch changes (`skills/*`, `research-method`, `orchestration`, `code-quality`, `git-workflow`, `memory-search`, `model-routing`, all `roles/*`) | Not this task. |

## Proof that no rule disappeared (boundary #2)

Both texts are assembled by the code Orchestra itself uses — `app.pipeline.build_system_prompt(
"default", role)` (`app/pipeline.py:583`), the same call `manager` makes. Neither is committed as a
text dump: the oracle renders both itself, so the proof is reproducible instead of ~6000 lines of
duplicated repository content.

```
uv run --frozen python .orchestra/tasks/490/check_no_rule_lost.py
```

- before: `git archive a1fd56bb9adb2799d197d5a5ce67776a225d136a .orchestra/pipelines/default` into
  a temp dir (the merge-base of this branch with `main`), `pipeline.PIPELINES_DIR` repointed at it.
- after: the working tree as it stands — editing a module and re-running *is* the check.
- Byte size and sha256 of both slices are printed per role, so a divergence is caught by comparing
  hashes against `.orchestra/tasks/490/no-rule-lost.txt` without re-reading either text.

Oracle: `.orchestra/tasks/490/check_no_rule_lost.py` — splits each BEFORE prompt into semantic
units (top-level bullets and paragraphs, >40 chars) and requires each one to be either

1. present **character-for-character** (whitespace-normalised) in the AFTER prompt, or
2. listed in its `REWORDED` table with literal anchors that must all appear in the AFTER prompt.

Anything else fails the run. Result (`.orchestra/tasks/490/no-rule-lost.txt`, full output with
sizes and hashes):

```
orchestrator       verbatim=317  reworded= 11   66922 B → 67948 B
sub-orchestrator   verbatim=284  reworded= 11   59567 B → 60593 B
worker             verbatim=165  reworded= 11   35105 B → 36131 B
full-cycle         verbatim=284  reworded= 11   60276 B → 61302 B
reducer            verbatim= 48  reworded= 11   16271 B → 17297 B
PASS — no rule lost in any of the five role prompts
```

The reworded set is **identical for all five roles** — the 11 units this task deliberately moved
or translated, nothing role-specific. Everything else survives byte-for-byte.

**Mutation check.** Deleting `Silence is not consent anywhere except a live incident.` from
`user-values.md` turns the oracle red with 5 failures — one per role, naming the missing anchor —
and restoring the line turns it green again. No regeneration step is needed: the AFTER slice is the
working tree. The oracle is in this diff, not a throwaway probe.

### Rules reformulated rather than copied (boundary #4)

Russian → English, meaning preserved 1:1. Nothing here is a new rule; each is a translation of a
line that stands on `main` today:

1. `<user-values>` heading — "Ценности владельца — действуют во ВСЕХ проектах" → "Owner values — in
   force in ALL projects".
2. The preamble — owner decisions, not agent preferences; outrank any local project agreement; a
   project rule may narrow but not cancel; approved by name on 04.09.2026.
3. "Реализацию начинает его слово, ресёрч агент запускает сам" → "Implementation starts with his
   word; research an agent starts on its own", with "he pays for every worker and every burned
   subscription", "research … does not change system state and therefore goes without asking",
   "silence is not consent anywhere except a live incident".
4. "Архитектурная развилка выносится ему ДО реализации, на любом пути работы" → "An architectural
   fork goes to him BEFORE implementation, on any path of work".
5. "При живой поломке сначала вернуть работу, полировать потом" → "On a live breakage, restore work
   first and polish later".
6. "Он обязан ПОНИМАТЬ, что происходит" → "He is obliged to UNDERSTAND what is happening",
   including his right to be argued with.
7. "Найденный в собственных логах и данных ключ — рабочий инструмент, а не инцидент" → "A key found
   in our own logs and data is a working tool, not an incident".
8. Standard rule "Respond in the same language the user communicates in" — not translated, but
   **widened**: it now explicitly also binds the orchestrator's user-facing voice, which the
   surrounding `communication-style` block otherwise excludes.

Everything already in English (`communication-style`, `knowledge-and-context`) was moved verbatim,
not rewritten.

## Size budget (boundary #5)

`.orchestra/tasks/490/size-budget.md`:

| role | before (chars) | after | delta | % |
|---|---|---|---|---|
| orchestrator | 63569 | 66049 | +2480 | +3.9% |
| sub-orchestrator | 56591 | 59071 | +2480 | +4.4% |
| worker | 32431 | 34911 | +2480 | +7.6% |
| full-cycle | 56532 | 59012 | +2480 | +4.4% |
| reducer | 13576 | 16056 | +2480 | **+18.3%** |

Four roles are inside the 10% ceiling. **The reducer is not, and cannot be** without breaking
boundary #2 or #3:

- The absolute growth is the same +2480 chars for every role — it is one block of new owner values,
  not per-role bloat. The reducer's percentage is high only because its prompt is the smallest
  (13.6K vs 32–64K).
- I looked for the duplicate the ceiling's rationale predicts. There is none: the reducer loads
  no other modules, so the new text has nothing to duplicate. `communication-style` grew +173 chars
  (the moved language rule), `knowledge-and-context` +12; the remaining +2295 is entirely new
  `user-values` content that boundary #3 says to keep.
- I did compress: the branch's version of the same content cost +2749 chars; rewriting the first
  value bullet without dropping any assertion took it to +2480.

The only lever left is to drop `user-values` from the reducer, which would remove rules it receives
today — a boundary #2 violation. **Owner's call, not mine.** Delivered as is, flagged here.

## Tests

- `uv run --frozen python -m pytest tests/ -k "prompt or pipeline or module" -q`
  → `352 passed, 9 skipped, 3707 deselected, 1 xfailed`.
  Two failures were fixed on the way:
  - `tests/test_check_pipeline_manifest.py` — `scripts/check_pipeline_manifest.py` requires an
    inline source marker on the same line as a measured number; the `#220` marker had wrapped onto
    the next line. Reflowed to `(#220: median delay to deploy 3.3 h, p75 22.9 h)`.
  - `tests/test_default_pipeline.py::test_modules_resolve_from_manifest` — hardcoded `modules:`
    lists updated. Added `test_shared_conduct_modules_reach_every_role`, which fails if any of the
    five roles loses one of the three modules (the regression this refactor makes possible).
- Every test file that mentions the changed files, run together:
  `test_default_pipeline test_fan_prompt_407 test_kb_markdown_contract test_manager
  test_orchestra_layout_430 test_pipeline test_project_knowledge_distribution_412 test_reducer_role
  test_runtime_registry test_tasks_pm_pipeline test_task_tracker_integration test_wf_run
  test_check_pipeline_manifest` → `520 passed, 7 skipped, 3 xfailed, 1 failed`.
- The one failure, `test_task_tracker_integration.py::test_t3_merge_operation_replay_does_not_
  repeat_git_or_lose_task_outcome` (`PARTIAL` vs `FAILED`), is **pre-existing**: reproduced on a
  clean detached worktree at `HEAD` (`a1fd56bb`) with none of these changes. Merge-operation replay,
  no relation to prompts.
- Full suite not run, no test lock taken (per the task).

## Residual risk

- **Reducer +18.3%** — above the stated ceiling, argued above. It is a `gpt-5.6-luna` role, so the
  extra ~600 tokens per turn hit the cheapest agent in the system, but they are per-turn on the most
  frequently woken one.
- **No restart needed for the content itself.** `build_prompt_modules` (`app/pipeline.py:568`)
  reads each module file uncached on every call, and the manifest cache
  (`_load_pipeline_cached`, `app/pipeline.py:379`) is keyed on `(mtime_ns, st_size)`, so an edit
  is a miss. Live agents pick the new blocks up on their next turn through
  `ROLE_SYSTEM_PROMPT` (`app/manager.py:347`). No `app/**` code changed here.
- **`user-values` is now English while the owner approved it in Russian.** Meaning was preserved
  line by line and audited above, but nuance loss in a translation is not something a mechanical
  anchor check can rule out. The Russian original stays in git history at `HEAD:base.md`.
- The three modules now also reach the **reducer**, which previously read them from `base.md`
  anyway — no behaviour change there, but its ordering in the assembled prompt moved (modules are
  appended after `roles/reducer.md`, whereas `base.md` came first).
