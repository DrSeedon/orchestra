# V-1256 — research delivery correction

## Scope and authority

Approved implementation, owner decision, 2026-11-03: every completed research assignment
must receive a substantive owner-facing explanation through the existing user-answer-format.
Evidence acceptance and delivery of that explanation both precede research closure.
Research does not authorize implementation. No new approval phase, runtime task-state
contract, provider invocation, polling, restart or deployment is authorized by this change.

## Findings recorded before edits

- `roles/orchestrator.md` already owns `<user-answer-format>` and says finished research
  must be retold. Its exclusion of denominators/filters and method details needs qualification
  so decision-relevant evidence and limitations are not lost when delivering the result.
- `modules/orchestration.md` class B says research ends at RESEARCH DONE with an artifact.
  This leaves worker completion conflated with accepted, owner-delivered research closure.
- `modules/worker-lifecycle.md` permits completion after findings are accepted and saved,
  without explicitly checking that the owner received the explanation.
- `modules/communication-style.md` suppresses non-results but does not explicitly protect
  a new material worker finding awaiting acceptance and owner delivery.
- `roles/sub-orchestrator.md` correctly reports up through the parent. Preserve this boundary;
  shared closure rules must require forwarding material findings for owner delivery, not direct
  user messaging or a duplicate answer template.

## Supplied-copy limitations

At initial inspection no prior V-1256 artifacts, outbox, `.git`, `app/`, `scripts/`,
`.orchestra/pipelines/default/pipeline.yaml` or `prompts/base.md` were present.
Only supplied files may be edited; do not invent missing product/manifest/contract sources.
The provisioned runner exists and reports uv 0.11.28. Real pipeline assembly, app import,
instruction contracts and runtime delivery cannot be claimed without the omitted sources.
No credentials, task-store records, private logs or server identities were fetched.

## Intended correction

Keep the single owner-facing format in `roles/orchestrator.md`. Reference it from shared
research acceptance/closure and lifecycle paths. Sub-orchestrators forward complete findings
through their parent, who owns the actual user-facing explanation. Add only structural
assembly tests if missing; no tests of literal policy wording or section ordering.

## First verification outcome

The provisioned uv 0.11.28 successfully created the default `.venv` from the frozen lock
(76 packages). The targeted pytest command exited 2 during collection: four collection
errors, because `app` and `scripts/check_pipeline_manifest.py` are absent. No tests passed
and no model/provider or live-service checks ran. The public `pytest.log` now contains a
sanitized pointer and original SHA256; the parent retained the full raw output privately.

During local diff review, cross-module references were written as `user-answer-format`,
not duplicate XML blocks: existing ownership/isolation tests prohibit the top-level template
from appearing in sub-orchestrator or worker prompts. The shared rule explicitly qualifies
the direct-owner-message prohibition as applying to sub-orchestrators only.

## Final bounded turn — owner clarification, 2026-11-03

The parent relayed the owner's clarification: default answers must be short and dense,
without losing the research result. Updated only the existing user-answer-format paragraph
and its mechanisms/examples bullet: default to verdict, decision-relevant numbers and practical
implication/next action; expand only on request or to explain a material risk. The English
owner-decision entry and reason remain in the canonical format. Updated the existing changelog
entry accordingly; no additional template or delivery/approval protocol was introduced.

Removed exactly the two authorized generated artifacts from this copy:
- `tmp/orchestra-test-catalog-6n1ezx3n/projects.yaml`
- `tmp/uv-1263a287bf9d3eb7.lock`

No broader cleanup occurred. Original failed-check logs were subsequently preserved privately
by the parent; their public files now contain sanitized pointers and original SHA256 values.
Previous static-check evidence, the final structural-check script and its output remain here.

## Final diff and reading order

1. `roles/orchestrator.md`: the single user-answer-format owner explains each completed
   research result, now explicitly short by default. Decision-relevant qualifiers remain
   visible; DONE/status/artifact links cannot replace the explanation.
2. `modules/orchestration.md`: class B distinguishes worker completion from task closure;
   acceptance requires evidence and actual owner delivery. Parent/sub-orchestrator handoff
   preserves findings and an explicit outstanding delivery obligation.
3. `modules/worker-lifecycle.md`: research completion/archival references that shared check.
4. `modules/communication-style.md`: genuine non-results remain suppressible; new material
   findings and limitations must not disappear through silence/acknowledgement suppression.
5. `tests/test_default_pipeline.py`: six parameter combinations check that orchestration,
   lifecycle and communication modules are configured and delivered exactly once to both
   orchestrator roles by the real loader and manager assembler. No literal policy phrases
   or section ordering are asserted. Existing ownership tests remain unchanged.
6. `CHANGELOG.md`: records the prompt-only correction and concise default.

Shared modules are the intended route to both managing roles; the answer template remains
only in the top-level role. Real manifest/loader/manager sources are missing in this supplied
copy. The parent subsequently reported successful focused assembly/contract validation on
the complete host worktree; this worker did not execute those host checks.

## Actual checks and limitations

| Check | Result |
|---|---|
| Provisioned uv 0.11.28, frozen default .venv | Setup succeeded |
| Earlier focused pytest command | RED: exit 2, four collection errors; absent app and manifest checker |
| Earlier instruction contract | Could not run: exit 2, scripts/check_instruction_contract.py absent |
| Earlier pipeline contract | Could not run: exit 2, scripts/check_pipeline_manifest.py absent |
| Final safe structural check through uv | PASS: exit 0; see final-structural-check.log |
| Six new assembly variants in this copy | Unrun; missing real app/manifest/base prompt |
| Later independent host focused tests | 177 passed, reported by the parent; not run by this worker |
| Later actual host instruction and pipeline contracts | Both passed, reported by the parent |
| Merge test gate for reviewed revision 93c6eb59 | Passed, reported by the parent; publication guard blocked merge before commit |
| Actual delivery and model adherence | Unverified; no runtime/provider calls authorized or made |

The earlier missing-source commands were not repeated. The final check parses the changed
Python test, checks singular/balanced wrappers and top-level ownership, checks removal of
only the named artifacts, and checks retention of the original log files. These structural
checks do not prove real prompt assembly or improved model adherence.

No app import succeeded; there is no absolute imported app path to report. The expected
source package under this copy's root is absent. No runtime source, task-state contract,
provider routing, model-review freeze, approval boundary or fresh-instance policy was changed.

## Commit and handoff

This is still a broker copy without `.git`: both `git status --short` and `git log -1`
reported `fatal: not a git repository (or any of the parent directories): .git`. Therefore
a local commit, clean Git tree or exact final imported HEAD cannot be truthfully reported
from here. The parent reports reviewing revision 93c6eb59 and successfully completing the
focused host checks and both contracts. The subsequent merge stopped before commit solely
on the publication guard for the three raw logs. The platform must import this report-only
correction on the managed task branch; the parent will inspect the resulting exact HEAD and
start a new merge operation under the existing guard. No test rerun, push or restart occurred.

## Publication-boundary correction

At the parent's explicit direction, changed only this report and the public bodies of
`instruction-contract.log`, `pipeline-contract.log` and `pytest.log`. Each log now preserves
its original RED/exit-2/missing-source meaning with a relative private-original pointer and
SHA256. Before replacement this worker verified that the three supplied originals matched
the hashes provided by the parent. The parent separately saved and hash-verified the raw
originals in `.orchestra/private/V-1256/publish-guard-originals` and retains them in local Git
history. This worker neither accessed nor recreated those private copies.

Prompt, source, test and changelog bytes remain unchanged in this correction. Earlier
supplied-copy failures remain failures; later host validation is separately attributed to
the parent. No new tests, runtime checks, model calls, network calls or guard bypass were used.
