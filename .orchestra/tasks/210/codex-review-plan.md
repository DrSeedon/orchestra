## Summary

The composite mutation is detected: three of seven tests fail, so the acceptance test can detect the rule’s removal even when its marker is planted in `base.md`.

The larger problem is operational: two of the three claimed consumers do not actually require evidence that the test existed and was red, and `oracle: none` is currently the cheapest compliant choice. The plan needs small wording changes before implementation.

## Findings

### Blocking — two “mechanical consumers” can be satisfied without the artifact

The anti-ritual argument overstates enforcement:

- Codex can produce a plan review without executing or inspecting a committed red test. The proposed rule says Codex reviews “the plan together with the test,” but defines no required evidence of the red run.
- `PLAN READY` can quote a fabricated `exit 1` and failing line. The statement “подделать это … нельзя” is false: it is still agent-authored narrative.
- Phase 3 currently only says to check the ticket against its AC. The plan claims Phase 3 “requires red→green,” but adds no such requirement to the proposed Phase 3 text. An executor can run only the final green command and comply.

Minimal fix within `full-cycle.md`: explicitly require Codex to verify the committed test and its recorded red failure, and make Phase 3 run the named test before implementation, stopping if it is already green or missing. Otherwise the red artifact remains largely ceremonial.

### Suggestion — `oracle: none` is the cheapest compliant behavior

Yes. The agent may mark every ticket `oracle: none` without explaining why, without Codex rejecting an unjustified classification, and without any other consequence beyond keeping work expensive. Counting the marks makes misuse visible later but does not prevent the cheapest local behavior.

Minimal fix: change the ticket field to require a reason, for example:

`Test: oracle: none — <why neither a behavioural check nor a delivery check is possible>`

Then require the existing Codex plan review to treat `oracle: none` as blocking whenever it can identify a viable check. This preserves the deliberate absence of a penalty while making the escape hatch reviewable before handoff.

### Suggestion — composite-mutation coverage is valid, but the plan should state the exact result

Under the plan’s exact mutation:

- Fails: `test_plan_step_is_owned_by_the_full_cycle_file`
- Stays green: `test_executor_rule_is_owned_by_both_working_role_files`
- Fails: `test_every_clause_of_the_plan_step_survives_assembly`
- Stays green: `test_ticket_template_carries_the_test_field_and_the_none_marker`
- Stays green: `test_plan_ready_report_quotes_the_failing_run`
- Stays green: `test_working_roles_receive_their_anchors`
- Fails: `test_orchestrator_roles_receive_neither`

Thus three fail and four stay green. The source-owner and non-leak checks independently catch the mutation; there is no realistic version of the stated mutation where all seven stay green.

### Suggestion — test ownership and copied structure are sound

`TestOracleGate` belongs in `tests/test_default_pipeline.py`. Its source/delivery/non-leak structure faithfully extends `TestPremortemReachesWorkingRolesOnly`.

The classes do not fight:

- They use distinct anchors.
- Their source assertions cover different rules.
- Their orchestrator non-leak assertions overlap structurally but not textually.
- The new class’s numbering-based block extraction correctly matches the planned insertion between Phase 2 steps 2 and 3, after renumbering to steps 3 and 4.

The focused baseline run behaved as documented: `6 failed, 1 passed, 49 deselected`.

## Verdict

Changes required. The acceptance test is adequate and correctly owned, but the workflow still permits ritual compliance and makes `oracle: none` the easiest path. Tighten those two contracts before implementing the plan.

## Round (2026-08-12T05:55:36Z)

## Summary

Fix 1 closes the original ritual hole for tickets with named tests. However, Round 2 exposes one blocking inconsistency: `oracle: none` tickets cannot pass the now-unconditional Phase 3 pre-check. The new assertion also does not bind the reason requirement to the ticket template, which still contains the bare marker.

## Findings

### STILL OPEN — blocking: Phase 3 has no path for `oracle: none`

For a ticket with a named test, there is no compliant path where the executor avoids observing red: it must run the command before touching code and stop if it is green or missing. But an `oracle: none` ticket has no named test, so the same unconditional Phase 3 step classifies it as “missing” and requires STOP—even on the expensive side. Add the minimal exception to Phase 3 step 2: the red→green requirement applies unless the ticket has a reviewed, reasoned `oracle: none`. Otherwise such tickets are visible but impossible to implement.

### STILL OPEN — blocking: the reason assertion does not bind the template

An agent can copy the verbatim ticket template, which still says:

`- Test: ... or oracle: none`

That produces the bare marker which the surrounding prose declares invalid. The test remains satisfiable because `oracle: none — <why` appears elsewhere in the assembled prompt; it does not prove that the template requires it. A content-free reason such as “no test possible” is acceptable with the Codex backstop—the review must refute it by naming a viable check—but the template itself must use the reasoned form, and the assertion should pin that complete `- Test:` form.

### NOT A PROBLEM — numbering, extraction bounds, and anchors

The proposed numbering is coherent: Phase 2 becomes steps 1–5, and Phase 3 retains its existing numbering with step 2 replaced. The extraction between `"\n3. "` and `"\n4. "` still isolates exactly the new oracle step. The two new anchors do not collide with existing role text—the focused RED run shows both are currently absent—and their planned locations are distinct. The run matches the report: `7 failed, 1 passed, 49 deselected`.

## Verdict

Two blocking findings remain, both fixable with surgical wording/test changes: exempt reviewed `oracle: none` tickets from the Phase 3 red precondition, and put the reasoned form directly in the ticket template with an assertion bound to that field.
