The single shared module is preferable to two copies and reaches exactly the currently declared spawn-capable roles without changing the moved text's ordering relative to `orchestration`. However, the escalation criterion is not fully machine-decidable, and the regression test can miss routing leakage that omits the XML wrapper.

Full review comments:

- [P2] Require acceptance criteria to have machine-verifiable outcomes — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/modules/model-routing.md:7-7
  The escalation trigger is not decidable from machine evidence alone: CLOSED only requires that acceptance criteria can be named, so a criterion such as “the wording is clear” can be judged unmet without any objective signal. The red-test branch is deterministic, and the wording clearly forbids a second Luna attempt, but the AC branch needs to require an explicit machine-checkable verification command or result.

- [P2] Test routing content rather than only its wrapper tag — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/tests/test_default_pipeline.py:147-147
  This test stays green if routing silently reaches `worker` without the exact `<model-routing>` wrapper—for example, copying the Luna bullet or the whole block minus its tags into `base.md` makes the worker receive the rule while this negative assertion still passes. Since the test claims routing reaches only spawn-capable roles, assert a stable routing-content anchor is absent from `worker` (and ideally that its source is the dedicated module), not only the opening tag.

## Round (2026-08-12T03:21:23Z)

Re-review status:

1. **AC finding: FIXED, but NEW BUG in another escalation branch.** Luna now requires command evidence: “**the named test command stays red, or an acceptance criterion is not shown met by the output of a command**” and rejects unverifiable ACs: “**A criterion nobody can check by running something is not an AC**”.

   However, Spark still says: “**Escalate to Sol if a test fails or scope grows.**” An agent can assert that “scope grows” without machine-checkable evidence. So yes, one escalation branch remains non-decidable.

2. **Routing-test finding: STILL BROKEN.** Mutation: copy only this Opus routing instruction into `base.md`:

   > “**Opus 5 (`claude-opus-5[1m]`) — DEFAULT for OPEN work: implementation with unknowns, fixes, review, general multi-step work; strongest for ambiguity/dialogue, reading between the lines, creative prose, images, and 1M-context synthesis. A closed task goes to Luna instead.**”

   Worker then receives real model-routing content, while none of the tested anchors—“`<model-routing>`”, “`gpt-5.6-luna`”, or “`ahead of the Opus default`”—is present. `out.count(module) == 1` also remains true for spawn-capable roles.

Verdict: **STILL BROKEN**—both requested properties retain a counterexample.

## Round (2026-08-12T03:23:07Z)

Re-review status: both prior findings **FIXED**.

The test requires each spawn-capable prompt to contain the complete module exactly once:

> `assert out.count(module) == 1, f"{role}: маршрутизация должна прийти ровно из модуля"`

It also rejects every verbatim routing bullet in `worker`:

> `for anchor in ["<model-routing>", *bullets]:`  
> `    assert anchor not in worker_out, f"маршрутизация протекла воркеру: {anchor[:40]}"`

I cannot construct a mutation that stays green while a listed spawn-capable role loses routing or `worker` receives a verbatim bullet. The remaining counterexample requires manually rewording routing content; the docstring explicitly records that accepted limitation.

New findings: none.

Verdict: **APPROVED**.
