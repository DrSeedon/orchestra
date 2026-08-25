# #361 Phase 2 mechanical review

## Route

Review: none — provider/model/eval/review calls are explicitly forbidden. The subject is high-risk
shared runtime, persistence, auth/scope, restart, and secrets work; the normal route would require a
technical model pass, but authorization forbids it. No substitute reviewer was started.

## Superseded-oracle note

The first frozen oracle `4dfab9a7` is excluded: after T1 added the missing module, the fixture failed
`sqlite3.IntegrityError: FOREIGN KEY constraint failed` before any runtime call. The cause was the test
discarding `ensure_project`'s casefolded ID. The corrected fixture inserts the production-shaped legacy
uppercase project row explicitly and adds a green tasks/sessions/logs reachability control. No AC or
runtime assertion was weakened.

## Gate inputs

- Author metadata: `live-knowledge-cutover-sol`, `gpt-5.6-sol`, as returned by live `list_agents`.
- Changed Phase 2 consumers: `docs/tasks/361/plan.md` and the frozen acceptance file only.
- Exact AC: six ticket AC blocks in `plan.md`; T1–T5 have named pytest nodes, T6 has a named delivery
  preflight and post-merge live checks.
- Frozen oracle commit: `2560da4f`; current acceptance bytes are identical to that commit (16,702
  bytes).

## Completeness result

- Tickets: 6; dependency graph `T1 → {T2,T3} → T4 → T5 → T6`, acyclic.
- Every ticket has Files, Test, AC, and blocked-by.
- T1–T5 each collect normally and exit 1 on the ticket-specific assertion, not ImportError or setup.
- T6 delivery command exits 127 because the activation CLI does not exist; that is the missing delivery,
  not a prose oracle.
- The acceptance file never imports or enters `app.main`, TG, a provider backend, a model, or an embedder.
  It uses temporary SQLite/Git roots and a mini FastAPI router.
- The test file is immutable after `2560da4f`; the following commit changes only plan/review references.

## Observed RED

```text
T1 exit 1: AssertionError: #361 T1 missing production KnowledgeRuntime owner
T2 exit 1: AssertionError: #361 T2 missing production KnowledgeRuntime owner
T3 exit 1: AssertionError: #361 T3 missing production KnowledgeRuntime owner
T4 exit 1: AssertionError: #361 T4 missing production KnowledgeRuntime owner
T5 exit 1: AssertionError: #361 T5 missing production KnowledgeRuntime owner
T6 exit 127: zsh:1: no such file or directory: scripts/activate_knowledge.py
```

`git diff --check` and the plan completeness/byte-identity script both exit 0. No blocking mechanical
finding remains. The implementation must rerun each exact node before touching its ticket and stop if a
node is already green or missing.
