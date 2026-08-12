The Luna scope limit is actionable and not inherently self-contradictory, but the Sol guidance requests an effort choice the reader cannot make. The diff also adds an unsupported numerical comparison and an overbroad manifest comment that conflicts with following values.

Full review comments:

- [P2] Remove the unactionable top-effort direction for Sol — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/modules/model-routing.md:7-7
  A spawning agent can select only the model and role, while both eligible roles currently supply `effort: high`; it cannot act on the claim that Sol should run at the top rung. For an open task that cannot be routed to Luna, this leaves no executable route matching “There is no cheap Sol” and may falsely imply that selecting Sol produces `xhigh`.

- [P2] Qualify the unsupported Luna bug comparison — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/modules/model-routing.md:6-6
  The supplied measurement establishes the effort curves and Luna's adequacy at `high`, but does not establish the newly added “one real bug,” `5.0/5.0`, or `13.2×` figures. Because numerical prompt claims require attribution and agents may weight these cost wins when routing, this comparison should be removed or tied to a stated measurement.

- [P2] Scope the effort comment to the affected worker roles — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/pipeline.yaml:17-18
  The comment says the value below is correct for the default Opus model and gives Opus a `high` target, but the immediately following Opus orchestrator roles retain `effort: medium`. A future editor can therefore read this as validation of values that contradict the comment's own target; name the specific `worker`/`full-cycle` fields to which the constraint applies.

## Round (2026-08-12T05:24:53Z)

Re-review status:

- FIXED — unactionable Sol effort direction.
- FIXED — Luna comparison is corrected and attributed.
- FIXED — manifest comment is scoped to worker roles.

New findings: None.

Verdict:

1. No. The prompt now directs only an executable model choice: “a task you would only fund at a discount goes to Luna, not to Sol.” The preceding text—“its returns keep climbing to the top of the effort ladder”—is measurement context, not an instruction to select an unavailable effort level.

2. Yes. The comment explicitly limits itself to “РАБОЧИХ ролей (`worker`, `full-cycle`)” and says: “Оркестраторских `medium` ниже это не касается.” It also prevents authorization ambiguity with: “Ждёт правки в коде; до неё Sol-воркеры недополучают ступень. Это запись ограничения, не задание.”

This is consistent with every manifest value: both orchestrator roles use `effort: medium`, while `worker` and `full-cycle` use `effort: high`.
