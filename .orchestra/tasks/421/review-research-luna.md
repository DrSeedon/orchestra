<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Because apparently `rg` needed a syntax lesson before certifying the architecture 😏

## Summary

The artifact is not ready for the Phase-1 gate. The six-column table, M1–M7 rows, and three direct-answer sections exist, but the load-bearing negative evidence is invalid and the KB promotion is not discoverable.

The research’s risk framing is otherwise good; this quote is especially accurate: “Rollback лечит обнаруженный вред, но не предотвращает тихо полезный по локальной reward и вредный глобально навык.” ([research.md:81](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:81))

## Findings (blocking/suggestion/question)

### Blocking

- **[blocking] Fix the negative measurement before calling F2 confirmed.**
  **File:** [research.md:27](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:27), [prime-agent.md:6](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/kb/prime-agent.md:6) · **Confidence:** 1.0
  The recorded `rg` pattern uses GNU-grep alternation (`\|`), but `rg` treats it literally; a control query for `foo\|bar` returns no matches. Therefore `RC=1` does not establish absence of an IPython/kernel runtime. The corrected pattern also needs a semantic audit: Orchestra already has persistent session state in [backend_harness.py:3](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/app/backend_harness.py:3) and [harness/sessions.py:1](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/app/harness/sessions.py:1), even if it is not Prime-equivalent model-visible namespace.

- **[blocking] Promote the KB topic through the required index.**
  **File:** [prime-agent.md:1-25](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/kb/prime-agent.md:1) · **Confidence:** 1.0
  `prime-agent.md` is absent from `docs/kb/README.md`. The memory-search contract requires new topics to be indexed, so future agents following the file-first retrieval path will not discover this promoted knowledge.

- **[blocking] Do not collapse the entire Prime lifecycle delta to the missing namespace.**
  **File:** [prime-agent.md:5](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/kb/prime-agent.md:5) · **Confidence:** 0.98
  Prime’s official long-running documentation separately describes persistent goals and bounded autonomous continuation, while Orchestra’s own M9 row admits those are only partial matches. The KB fact should preserve that gap instead of stating that the remaining lifecycle delta is only recoverable IPython state. ([Prime long-running docs](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/long-running-agents.md#L153-L199))

- **[blocking] Satisfy the per-cell evidence contract for absence claims.**
  **File:** [research.md:30-36](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:30) · **Confidence:** 0.97
  M4 (“no unified CRUD ledger”), M7 (“no kernel snapshot”), M8 (“no session tree”), and M9 (“no persistent-goal path”) assert absence without a scoped command or a direct owner/consumer audit in their own `есть ли у нас` cells. The cited positive lines prove existing logs, prompts, or jobs, not that the missing counterpart cannot exist. This contradicts the artifact’s own exact AC at lines 116–118.

### Suggestion

- **[suggestion] Point citations at the implementations they claim to prove.**
  **File:** [research.md:63](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:63) · **Confidence:** 0.99
  `app/workspace.py:492-538` stops before the branch creation at line 542; `app/mcp_stdio.py:930-1005` passes `owned_dirs` but does not implement collision checking; and neither range supports the stated squash-merge lifecycle. Use [workspace.py:540](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/app/workspace.py:540), [manager.py:533](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/app/manager.py:533), and the actual merge owner.

- **[suggestion] Label F1 as local code plus vendor documentation, not code on both sides.**
  **File:** [research.md:85](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:85) · **Confidence:** 0.99
  Sources [4] and [5] are Prime’s official architecture documents, not Prime implementation code. The document correctly distinguishes vendor evidence elsewhere, but F1’s “primary code on both sides” label overstates independence and should be corrected.

- **[suggestion] Mark the Orchestra reward-hacking example as hypothetical.**
  **File:** [prime-agent.md:8](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/kb/prime-agent.md:8) · **Confidence:** 0.93
  The Prime RCON observation is vendor-reported, while the Orchestra test-skipping scenario is a plausible risk, not a measured local incident. Preserve that distinction in the KB fact so future agents do not treat the analogue as observed evidence. ([Prime technical post](https://www.primeintellect.ai/blog/prime-agent#L169-L175))

## Verdict

❌ **Incorrect — not ready for approval.** Confidence: **0.99**

The architectural direction is mostly fair, and the external Prime descriptions match the cited mechanisms, but the invalid `rg` oracle and missing KB index make the current evidence and promotion contract fail. No files were edited.

Right now the proof is a locked door with `RC=1` scribbled on it.

- Attempt 2 started: 2026-08-30; resume after material artifact changes; same Luna reviewer/session.

## Round (2026-08-30T12:07:06Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Round 2: the prose improved, so naturally the curator revealed a second autonomous writer 😏 The prior blockers are resolved, but the trust comparison still misses one Hermes creation path.

## Summary

Hermes v0.20.1 source confirms `prune_builtins=true` by default and deterministic bundled-skill archival; the current config has no override. The `3/84` conclusion is qualitatively calibrated, but its notation and provenance need tightening. Official Hermes docs agree that pruning is enabled by default and LLM consolidation is separate and opt-in. ([Hermes curator docs](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/curator.md#L207-L241))

Required quote from the updated artifact: “Hermes показывает отдельную развилку, но не готовый «правильный центр».” ([research.md:115](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:115))

### Prior findings

- **B1 — FIXED:** invalid `rg` alternation replaced with valid `-e` expressions; scope narrowed to Prime-equivalent namespace.
- **B2 — RESOLVED DISAGREEMENT:** README remains untouched under explicit task authority; no edit is required here.
- **B3 — FIXED:** lifecycle gaps now include goals/autonomy and general transcript-tree semantics.
- **B4 — FIXED:** absence claims have scoped evidence; Claude `fork_session` correction is included.
- Prior citation, evidence-tier, and hypothetical reward-hacking issues are fixed.

## Findings (blocking/suggestion/question)

### Blocking

- **[blocking] Include curator-created umbrella skills in the writer matrix.**
  **File:** [research.md:53-60](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:53) · **Confidence:** 0.99
  The curator’s own LLM prompt explicitly permits `skill_manage(action=create)` for a new umbrella skill ([curator.py:482](/home/maxim/.hermes/hermes-agent/agent/curator.py:482)). The background preflight only covers existing-target actions, so `create` proceeds when approval is off ([skill_manager_tool.py:454](/home/maxim/.hermes/hermes-agent/tools/skill_manager_tool.py:454), [skill_manager_tool.py:1561](/home/maxim/.hermes/hermes-agent/tools/skill_manager_tool.py:1561)). Thus Hermes has two autonomous initial skill writers: the cadence-based self-improvement fork and the curator consolidation fork; the current text describes the latter as only patching/consolidating existing skills.

### Suggestion

- **[suggestion] Make the `3/84` denominator explicit.**
  **File:** [research.md:92](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:92), [prime-agent.md:12](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/kb/prime-agent.md:12) · **Confidence:** 0.99
  `3 agent-created / 81 bundled = 3.57%` visually states `3/81`, which is 3.70%; 3.57% is `3/(3+81) = 3/84`. Also, Hermes `curator adopt` can mark an existing skill as agent-created, so this is an inventory count, not necessarily a background-review creation count. The qualitative “no causal inference” conclusion is correctly calibrated.

- **[suggestion] Use the actual Hermes worktree setting.**
  **File:** [research.md:39](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-prime-agent/docs/tasks/421/research.md:39) · **Confidence:** 0.99
  The installed documentation configures `delegation.worktree_isolation: true`; `--subagent-worktree-isolation` appears only as the feature’s inspiration, not as the Hermes option. ([Hermes delegation docs](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/delegation.md#L390-L400))

## Verdict

❌ **Not ready yet.** Confidence: **0.99**

Previous findings are resolved, but the direct trust comparison is incomplete because curator consolidation can create new durable skills without approval under the current configuration. The curator currently has two pens, while the document names only one.

## Author resolution after Round 2 (round ceiling reached)

- **Blocking — ACK/FIXED after verdict:** `research.md` M5/M12 and the Hermes writer matrix now name both autonomous initial writers: cadence self-improvement fork and opt-in curator consolidation fork. Evidence: installed `agent/curator.py:430-539` permits `skill_manage(action=create)`; `tools/skill_manager_tool.py:454-460,1561-1581` lets create reach the approval gate; current `consolidate=false` disables the curator writer but not the architectural permission.
- **Suggestion — FIXED:** inventory notation is now `3 agent-created из 84 total = 3.57%; 81 bundled`; research/KB say `curator adopt` can set the managed marker, so the count is not a creation count.
- **Suggestion — FIXED:** Hermes setting is now `delegation.worktree_isolation: true` with default false, not a nonexistent CLI option.
- No Round 3 was requested: `codex-debate` caps prose at two rounds. The reviewer verdict above remains the Round-2 verdict; these fixes are mechanically checked but not re-reviewed.
