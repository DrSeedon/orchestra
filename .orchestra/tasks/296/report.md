# #296 — risk-based review routing

## Result

Review routing now has one canonical owner:
`pipelines/default/prompts/skills/codex-debate.md`. The base prompt, worker/full-cycle roles,
and orchestration module only tell decision makers to apply that gate; they do not restate its
table. The policy implements the approved #289 ladder:

- a trivial, fully closed leaf can skip model review only with a named, pre-existing or frozen,
  deterministic oracle and observed output;
- a compact low/medium-risk diff with that oracle gets one fresh Luna review;
- a verified Luna blocker, required-property uncertainty, or schema mismatch gets one targeted
  Sol escalation;
- shared runtime, auth, security, secrets, and migrations always require Sol;
- high-risk code authored by Sol/Luna additionally requests targeted Opus cross-family review
  when Claude is available; otherwise the report must say `cross-family verdict unavailable`;
- docs/fact extraction uses mechanical completeness checks or one Luna completeness pass;
- another round opens only after an artifact change for a verified blocker or an evidence-backed
  blocker dispute, within the existing prose/executable ceilings.

The author cannot lower the route by calling their own work trivial or their own oracle strong:
the gate requires changed consumers, author metadata, exact AC, and a named command with actual
output. High-risk is derived from an explicit changed-consumer taxonomy (shared process/session/
delivery/concurrency, auth/security/secrets, persistence/migration/data-loss, external contracts,
and control gates) or an upstream orchestrator classification; ambiguity raises rather than lowers
the floor. `codex_review` remains Sol-only. Luna and Opus reviews are delegated to a fresh reviewer
session by a spawn-capable parent; a terminal worker hands off instead of silently substituting
another model.

## Files

- `pipelines/default/prompts/skills/codex-debate.md` — canonical policy, routing, evidence and
  independence contract, follow-up rule.
- `pipelines/default/prompts/{base.md,roles/worker.md,roles/full-cycle.md,modules/orchestration.md,modules/report-format.md}`
  — single-owner pointers and neutral review reporting.
- `pipelines/default/pipeline.yaml` — delivers the skill to every role that can decide or perform
  review, including sub-orchestrator.
- `scripts/check_pipeline_manifest.py` — executable policy ownership/delivery/staleness checker.
- `tests/test_check_pipeline_manifest.py`, `tests/test_default_pipeline.py` — checker and assembled
  prompt regressions.

No runtime or production code changed.

## Acceptance evidence

Baseline before the prompt change: the new checker test failed with 20 policy errors; the first
was the missing canonical heading. After implementation:

```text
$ uv run pytest -q tests/test_check_pipeline_manifest.py tests/test_default_pipeline.py \
    tests/test_pipeline.py tests/test_prompting.py tests/test_manager.py tests/test_session.py \
    tests/test_legacy_pipeline_skills.py tests/test_runtime_registry.py
649 passed in 108.78s (0:01:48)

$ python scripts/check_pipeline_manifest.py --check
OK: pipelines/default/pipeline.yaml agrees with prompt files

$ git diff --check
<no output>
```

The focused prompt/manifest subset passed `259 passed in 10.04s`; after the Sol finding and its
mutation the focused checker/assembly subset passed `110 passed in 7.36s`.

## Mutation checks

Every mutation started from a green test, used a fresh `cp` backup, restored with `mv` + `touch`,
and was followed by a green rerun.

| Mutation | Expected failure |
|---|---|
| Remove the worker's canonical gate pointer | focused delivery test failed (`rc=1`) |
| Remove the self-certification guard anchor | manifest checker failed (`rc=1`) |
| Replace evidence-derived high-risk taxonomy with author-declared risk | manifest checker failed (`rc=1`) |
| Reintroduce stale `Codex review MANDATORY...` wording | checker rejected both stale text and missing pointer (`rc=1`) |
| Weaken mandatory-Sol high-risk wording to optional | canonical-anchor check failed (`rc=1`) |
| Remove `codex-debate` from sub-orchestrator skills | assembled-prompt delivery test failed (`rc=1`) |
| Copy the canonical policy heading into `orchestration.md` | checker rejected a duplicate owner (`rc=1`) |

The assembled-prompt tests also prove that orchestrator, sub-orchestrator, worker, and full-cycle
receive the gate exactly once, while reducer receives neither the skill nor a gate pointer.

## Activation

These are prompt-source changes only. They reach an agent on the next applicable prompt
re-injection; native skill projections are refreshed on backend reconnect. Editing the files does
not replace the prompt already loaded by a live native session. No restart, deploy, or production
mutation was performed.

## Review gate for this diff

- Changed surface: shared review-policy prompt, manifest delivery, executable checker and tests.
- Author: Sol/Codex session metadata.
- AC/oracle: the named 649-test suite, manifest checker, and seven independent mutations above.
- Risk: high — a bypass could suppress mandatory security/shared-runtime review or falsely claim
  cross-family independence. Static tests are strong for exact ownership/delivery but cannot prove
  semantic completeness.
- Route: mandatory targeted Sol review, then targeted Opus cross-family review if Claude is
  available.

Review outcomes are recorded below after the final diff is reviewed.

### Sol round 1

The reviewer ran the focused suite (`109 passed in 7.85s`) and found one P1: the initial text
forbade self-downgrade but did not define a non-author-controlled high-risk floor outside the five
mandatory-Sol surfaces. Accepted. The canonical gate now derives high-risk from changed consumers
and routes high-risk/non-compact/weak-oracle work directly to Sol before applying the Opus
cross-family addition. The background wrapper marked the job failed because the response omitted a
`## Verdict` heading; the substantive finding and quoted lines are preserved in
`docs/tasks/296/codex-review-impl.md`, so this counts as round 1 rather than a transport retry.

### Sol round 2

The same reviewer session marked the P1 **FIXED**, found no new blocking regression, and returned
`APPROVED`. Its evidence quote — “Автор может добавить класс риска, но не снять сработавший” — is
present in the canonical policy. Sol review therefore completed in two executable-artifact rounds,
with round 2 opened only after changing the artifact for the verified blocker.

### Opus cross-family

Fresh Opus reviewer creation was refused before a session existed:

```text
weekly_quota_blocked: New worker turn blocked: Claude weekly quota is 100% (new worker turns stop at 95%). Available provider: Codex, Codex Spark.
```

No Sol/Luna review was substituted as independent cross-family evidence. Final independence
status: `cross-family verdict unavailable`. This is an unresolved reviewer-availability gate, not
an approval; the completed same-family evidence remains Sol round 2 `APPROVED` plus the 649-test
suite and seven mutation checks.
