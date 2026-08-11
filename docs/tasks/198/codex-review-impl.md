## Summary

The full-cycle renumbering is internally consistent: no stale Phase 3 step references remain. The new rule does not conflict with the Codex gate or DONE evidence requirements, but it creates a blocking narration conflict and leaves the worker ordering ambiguous.

Verbatim evidence from the reviewed prompt:

> Do NOT freestyle. The orchestrator drives you phase-by-phase — you never pick

## Findings

1. **blocking — Full-cycle requires narration between tool calls**

   [full-cycle.md:86](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-codex-theses/pipelines/default/prompts/roles/full-cycle.md:86) says to “list up to 5” scenarios before testing. That requires visible prose in the middle of implementation, directly conflicting with the supplied context-economy rule prohibiting narration between tool calls.

   The prompt never assigns the list an artifact or private reasoning location. The more specific numbered instruction will therefore override context economy. Require the agent to derive the scenarios silently and encode checkable ones directly as tests, or name a file where the list belongs.

2. **blocking — Worker ordering remains contradictory**

   In [worker.md:55](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-codex-theses/pipelines/default/prompts/roles/worker.md:55), “All changes committed” precedes the pre-mortem. Then [worker.md:57](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-codex-theses/pipelines/default/prompts/roles/worker.md:57) orders the agent to add tests, while [worker.md:58](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-codex-theses/pipelines/default/prompts/roles/worker.md:58) says testing has already occurred.

   A checklist may be read as unordered, but its current textual order describes commit → pre-mortem → add tests → tests already ran. For deterministic behavior, put the pre-mortem before “Code works,” then commit/clean-tree last, or give the worker the same explicit implementation → pre-mortem → test → review → commit sequence as full-cycle.

3. **suggestion — The inert-change escape hatch permits routine vacuous compliance**

   Both prompts allow “one line saying why the change is inert” without defining inertness or demanding concrete evidence. An agent can cheaply claim that a small refactor, prompt edit, test-only change, or documentation change is inert and skip the intended falsification.

   Limit the escape to changes with no runtime or consumer-visible behavior and require naming the inspected diff/caller that proves this. Otherwise require at least one scenario. Also remove “an item nobody can check is not worth writing down”: it rewards labeling difficult risks uncheckable instead of finding the nearest observable proxy.

4. **suggestion — “Every checkable item” overstates the testing contract**

   [worker.md:57](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-codex-theses/pipelines/default/prompts/roles/worker.md:57) and [full-cycle.md:91](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-codex-theses/pipelines/default/prompts/roles/full-cycle.md:91) require every checkable scenario to become a test. Some concrete checks are appropriately validated by a command, type checker, migration rehearsal, or manual integration probe rather than a persistent test.

   This wording can cause speculative test creation and conflicts with minimum/surgical-change rules. “Turn each scenario into a test or another recorded check” preserves enforceability without forcing inappropriate code.

5. **suggestion — The test does not prove that the step reached either role**

   [test_default_pipeline.py:388](/home/kesha/orchestra/worktrees/home-kesha-orchestra/audit-codex-theses/tests/test_default_pipeline.py:388) searches the complete assembled prompt for the generic substring `Pre-mortem`. It will pass if the actual instruction disappears from a role file but that phrase later appears in `base.md` or an inlined module. Thus its stated structural guarantee is weaker than claimed.

   Use a unique stable marker owned by this instruction, such as an XML tag or explicit rule ID. The negative orchestrator assertion also encodes a fragile vocabulary ban: an orchestrator could legitimately discuss or assign a pre-mortem later without receiving the executor step.

6. **suggestion — The wording can be materially shortened**

   The two versions duplicate several ideas:

   - “for whoever gets this next” and “the first thing someone does after this ships”
   - “never a category” plus two generic negative examples
   - “an item nobody can check is not worth writing down”
   - “This is your own check”
   - “it costs no Codex round”
   - “does not replace the gate” when the numbered workflow already places the Codex gate afterward

   A compact enforceable form is approximately:

   > Before testing, identify up to five concrete regressions outside the AC. Name the affected file, command, or caller and the observable symptom; include existing data and the next consumer action. Add a test or recorded check for each. If the diff has no consumer-visible effect, state the concrete reason.

   This retains the behavioral contract while reducing permanent prompt cost and interpretive branches.

## Verdict

**Changes requested.** The full-cycle renumbering is correct, and no contradiction with “State your assumptions,” the Codex review gate, or DONE evidence was found. However, the mid-turn listing requirement conflicts with the no-narration rule, and worker ordering remains ambiguous enough to produce commit-before-test behavior. These should be resolved before merging shared role prompts.

## Round (2026-08-11T18:38:37Z)

## Round 2

## Re-review status

1. **FIXED — narration conflict.** Silent derivation plus deferred recording gives the reasoning an explicit destination without requiring mid-tool narration. Recording it at step 7 is neither circular nor impossible: step 3 derives scenarios and drives checks; step 7 records the completed scenarios and evidence.

2. **FIXED — worker ordering.** First position plus “do this FIRST, before the checks below” is sufficiently deterministic. “All changes committed” now naturally occurs after any tests or probes added by the pre-mortem.

3. **FIXED — inert escape hatch.** The exception now requires both absence of consumer-visible behavior and concrete evidence from a caller or diff. The observable-proxy requirement also closes the easy “uncheckable” dismissal.

4. **FIXED — testing contract.** Tests remain preferred, while commands, rehearsals, and probes cover cases where persistent tests are inappropriate.

5. **FIXED — test ownership.** The new source-level assertion closes the reproduced false positive where `base.md` supplied the anchor after the role instruction disappeared. The remaining vocabulary-ban tradeoff is explicit and has a deterministic migration path.

6. **STILL BROKEN — permanent wording cost.** The additional branches are justified, but equivalent enforceability is available more compactly. Exact replacements:

For full-cycle:

> 3. **Pre-mortem — what breaks for the next consumer.** Before testing, silently identify 1–5 concrete regressions outside the AC. For each, name the affected file/command/caller and observable symptom; consider changed callers, old data, and the next consumer action. Cover each in step 4 with a test or recorded command, rehearsal, or probe; if no direct check exists, use the nearest observable proxy. Only when the diff has no consumer-visible behavior, record the caller or diff proving that. Record the scenarios and checks in `report.md` (step 7); no Codex round.

For worker:

> - **Pre-mortem — do this FIRST.** Silently identify 1–5 concrete regressions outside the task spec. For each, name the affected file/command/caller and observable symptom; consider changed callers, old data, and the next consumer action. Cover each with a test or recorded command, rehearsal, or probe; if no direct check exists, use the nearest observable proxy. Only when the diff has no consumer-visible behavior, name the caller or diff proving that. Put the scenarios and checks in the DONE report; no Codex round.

Using “1–5” also makes the narrowed zero-scenario exception syntactically unambiguous.

## New findings

None. Specifically:

- The deferred `report.md` write is a record of work performed at steps 3–5, not a prerequisite for that work.
- The worker instruction does not imply that the DONE report is written first; it says the pre-mortem activity occurs first and its result is emitted later in the DONE report.
- No stale Phase 3 numbering references remain.

Verbatim reviewed line not quoted in round 1:

> Someone else's fix is a hypothesis about our system, not a verdict: reproduce it here first.

## Verdict

Approved with one non-blocking prompt-cost suggestion. Both previous blocking findings are resolved, the ownership test now protects its stated structural invariant, and I found no new behavioral or ordering defect.
