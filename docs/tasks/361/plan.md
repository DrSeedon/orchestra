# #361 — staged live activation plan

Research basis: `docs/tasks/361/research.md` at commit `5ced099b`.

Oracle history: `4dfab9a7` is excluded from implementation evidence. Its initial missing-module RED hid
a fixture FK error: `ensure_project("VPN-Service")` stored `vpn-service`, after which the fixture inserted
a task under the discarded uppercase ID. The corrected oracle preserves an explicit legacy uppercase
row and adds a green fixture reachability control; ticket nodes are rebound below.

## Goal and fixed constraints

Ship one restart-safe typed knowledge runtime that is queryable through the real MCP/HTTP chain in
every resumable project scope. Generation 2 keeps legacy TM/RAG as the active response owner while the
typed candidate is mirrored and measured. Generation 3 is a separate persisted transition after all
six gates verify. Historical Markdown and native provider sessions are preserved. SQLite, FTS, and
vector stay rebuildable projections. `clear-session` and projection deletion are not operations.

No provider/model/GPU/eval/review call is part of any ticket. Tests use isolated SQLite, small local Git
repositories, and a mini ASGI app; they never enter the production `app.main` lifespan or start TG.

## Exact runtime contract

Create `app/ia/runtime.py` with these public production seams:

```python
@dataclass(frozen=True)
class RuntimeConfig:
    state_root: Path
    legacy_db_path: Path
    vector_db_path: Path
    scope_roots: Mapping[str, Path]
    prompt_assembler: Callable[[str, str], str]

@contextmanager
def knowledge_runtime_mode(config: RuntimeConfig) -> Iterator[KnowledgeRuntime]: ...

def active_runtime() -> KnowledgeRuntime: ...
def authorized_knowledge_request(request: Request, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...
def production_runtime_config() -> RuntimeConfig: ...
```

`KnowledgeRuntime` exposes read-only `state`, `paths`, `scope_registry`, `task_store`,
`evidence_records()`, `parity()`, `verify_gates()`, and administrative `cutover(request)`. State lives
under:

```text
${STATE_DIRECTORY or ${XDG_STATE_HOME or ~/.local/state}/orchestra}/knowledge-v1/
├── runtime-state.json
├── scope-registry.json
├── canonical/                 # dedicated local Git repository; JSON only
├── task-current.db            # rebuildable
├── current.db                 # rebuildable current/FTS
├── vector-snapshot.receipt.json
├── receipts/*.json
└── debt/*.json
```

The runtime creates directories mode 0700, rejects multi-path/non-absolute `STATE_DIRECTORY`, and never
uses ignored repo `data/` for canonical JSON. The Git repository has no remote and commits every
canonical transaction/receipt with deterministic tree content; projections remain outside it.

Canonical project IDs come from one persisted scope registry. A lowercase slug legacy ID is preserved;
otherwise use `<sanitized-base>-<sha256(raw-id-or-scope)[:12]>`, with `project-` as an empty base.
Every canonical path is resolved and checked beneath its configured root before a write. Caller payload
never chooses its project: `/api/knowledge` resolves `X-Orchestra-Session-Id` plus
`X-Orchestra-Mcp-Proof`, loads the session scope, and injects its registry ID. Conflicting `project_id`
is 403. `cross_project` and mutation require an orchestrator proof; worker/reducer/read-only callers are
query-only.

`payload.query` is normalized to `payload.text`; supplying both with different values is 400. An empty
topic registry is a health state only. Shadow bootstrap imports current task state and pinned Git/log
evidence for all registered resumable scopes before publishing generation 2.

## Ownership and sequencing

1. `app.main.lifespan`, after `init_db()` and before `manager.auto_resume_all()`, enters exactly one
   `knowledge_runtime_mode(production_runtime_config())`. Knowledge/projection/cutover owners are
   process-global. TM receives a process-global shadow context with a shared `threading.RLock`; its
   existing ContextVar remains available only for isolated tests.
2. Shadow TM commits legacy first. Candidate commit happens under the runtime lock. Candidate failure
   returns the successful legacy result with `shadow_match=False`, persists debt, and cannot make the
   legacy outcome unknown. Generation 3 is blocked while debt or mismatch exists.
3. Generic typed queries use the candidate current/FTS projection. Legacy `/api/memory/search` continues
   to use the existing RAG owner in generation 2; it switches to typed current only after generation 3.
4. Git evidence is read from the pinned commit/tree/blob. Canonical JSON stores identity/path/commit/blob/
   SHA only, never the Markdown/log body. Projection payloads are privacy-filtered; unresolved token-shape
   matches block the privacy gate.
5. Runtime state and receipts are load-before-serve and byte-idempotent. Restart never re-runs a new
   bootstrap manifest over a newer head. A repeated request reads the existing receipt.
6. Prompt assembly treats a null-overlay old prompt as platform-owned only when it has the complete old
   platform role/module envelope. It rebuilds that prompt and records an owned empty/ownership overlay;
   a true custom full prompt is preserved byte-for-byte. No code changes `sessions.session_id`.

## Files

- New: `app/ia/runtime.py` — the sole live runtime/state/scope/Git/receipt owner.
- `app/main.py` — enter/exit the production runtime around the existing lifespan body.
- `app/tm.py`, `app/ia/task_store.py` — process-visible locked shadow context, mapped project identity,
  safe paths, load-existing/reconcile and non-fatal persisted mirror debt.
- `app/routes/knowledge.py`, `app/mcp_stdio.py`, `app/mcp_proof.py` — proof-bound scope/operation auth and
  query→text normalization; one MCP tool remains.
- `app/ia/knowledge.py`, `app/ia/projections.py`, `app/routes/memory.py` — verified Git evidence adapter,
  candidate/active read selection, privacy projection and retained vector debt/head.
- `app/ia/cutover.py`, `scripts/ia_document_inventory.py`, `scripts/ia_migrate_documents.py` — delegate
  generation/receipt ownership to the persistent runtime and remove hardcoded one-project assumptions.
- `app/manager.py` — ownership-safe legacy prompt migration during ordinary assembly.
- `deploy/orchestra.service`, `deploy/orchestra.service.template` — one `StateDirectory=orchestra`
  contract without changing interpreter/socket/handover settings.
- New: `scripts/activate_knowledge.py` — `preflight`, `shadow`, `verify`, `canonical`, `rollback`, `state`;
  JSON output, no deletion flag, no service/session commands.
- New: `docs/tasks/361/acceptance/test_live_activation_behavior.py` — immutable Phase 2 oracle.

Do not touch RAG model/chunking/ranking, provider backends, session history/compact, live DB schemas,
merge behavior, historical Markdown bodies, remote Git configuration, or any delete/VACUUM path.

## Tickets

### T1 — Scoped MCP query reaches a live shadow runtime

- Files: `app/ia/runtime.py`, `app/main.py`, `app/routes/knowledge.py`, `app/mcp_stdio.py`,
  `app/mcp_proof.py`, `docs/tasks/361/acceptance/test_live_activation_behavior.py`.
- Test: `.../python -m pytest docs/tasks/361/acceptance/test_live_activation_behavior.py::test_t1_scoped_mcp_query_is_live_and_authorized -q` — committed RED in `2560da4f`.
- Failing assertion: `#361 T1 missing production KnowledgeRuntime owner`.
- AC: the named command is green; a generic `payload.query` from a proof-bound worker returns only that
  session scope’s typed items; conflicting project/cross-project/mutating requests are refused; missing
  project scope is an error, not an empty success; `app.main` installs the same runtime before resume.
- blocked-by: none

### T2 — Task shadow is concurrent, restart-safe, and non-fatal to legacy

- Files: `app/ia/runtime.py`, `app/tm.py`, `app/ia/task_store.py`, the acceptance test.
- Test: `.../python -m pytest docs/tasks/361/acceptance/test_live_activation_behavior.py::test_t2_task_shadow_is_concurrent_restart_safe_and_debt_bound -q` — committed RED in `2560da4f`.
- Failing assertion: `#361 T2 missing production KnowledgeRuntime owner`.
- AC: the named command is green; two concurrent creates have distinct identities and parity; invalid
  legacy project IDs cannot escape state root; closing/reopening keeps generation 2 and identical receipt
  bytes; injected candidate failure preserves the legacy update, returns `shadow_match=False`, persists
  debt, and blocks canonical transition.
- blocked-by: T1

### T3 — Pinned Git evidence and retained projections are privacy/scope safe

- Files: `app/ia/runtime.py`, `app/ia/knowledge.py`, `app/ia/projections.py`,
  `app/routes/memory.py`, `scripts/ia_document_inventory.py`, `scripts/ia_migrate_documents.py`, the
  acceptance test.
- Test: `.../python -m pytest docs/tasks/361/acceptance/test_live_activation_behavior.py::test_t3_git_evidence_is_pinned_private_and_projection_rebuildable -q` — committed RED in `2560da4f`.
- Failing assertion: `#361 T3 missing production KnowledgeRuntime owner`.
- AC: the named command is green; evidence binds commit+blob+SHA and ignores later working-tree edits;
  untracked/secret files and secret values never enter canonical/projection output; bogus commit/alias is
  rejected; loss/staleness of current SQLite falls back to verified Git canonical data with debt;
  vector DB bytes remain unchanged and no projection is deleted.
- blocked-by: T1

### T4 — Durable receipts gate canonical generation and rollback

- Files: `app/ia/runtime.py`, `app/ia/cutover.py`, `scripts/activate_knowledge.py`, the acceptance test.
- Test: `.../python -m pytest docs/tasks/361/acceptance/test_live_activation_behavior.py::test_t4_cutover_receipts_survive_restart_and_keep_projections -q` — committed RED in `2560da4f`.
- Failing assertion: `#361 T4 missing production KnowledgeRuntime owner`.
- AC: the named command is green; shadow/gate receipts are byte-identical across reopen; missing/mixed-head
  gate blocks generation 3; verified parity/privacy/rollback/prompt/live/projection gates allow 2→3;
  reopen stays at 3; delete request is rejected; rollback emits generation 4 and retains canonical JSON,
  task/current/vector SQLite, FTS, and historical sources.
- blocked-by: T2, T3

### T5 — Prompt/session delivery and activation CLI preserve native contexts

- Files: `app/manager.py`, `app/main.py`, `deploy/orchestra.service`,
  `deploy/orchestra.service.template`, `scripts/activate_knowledge.py`, the acceptance test.
- Test: `.../python -m pytest docs/tasks/361/acceptance/test_live_activation_behavior.py::test_t5_prompt_and_restart_delivery_preserve_native_sessions -q` — committed RED in `2560da4f`.
- Failing assertion: `#361 T5 missing production KnowledgeRuntime owner`.
- AC: the named command is green; reconstructable platform prompts gain all six knowledge anchors;
  custom full overrides remain byte-identical; every native `session_id` is unchanged across two runtime
  opens; MCP registry still has `knowledge` and not `search_memory`; service files declare the same state
  directory; activation CLI contains no clear-session/delete/provider invocation.
- blocked-by: T1, T4, and the live-query gate below.

**HARD GATE — prompt anchors ship LAST (user requirement, 25.08.2026).** The six knowledge anchors
must NOT reach any prompt-owner file until a live `knowledge` query has already returned success
through the real agent path (MCP → route → runtime) in a resumable scope. Green tests, a merged
runtime, and a running service are NOT this gate; only a successful live answer is. Rationale and
the measured failure are in `CLAUDE.md` § "Промпты агентов меняются ПОСЛЕДНИМИ": on 25.08 anchors
landed first, a foreign orchestrator hit `503 knowledge_not_configured` on a mandatory step, and the
rule had to be withdrawn by rolling prompts back to `search_memory`. A broken prompt breaks every
agent in every project at once; unused code breaks nobody. If the live gate fails, roll back the
PROMPT, never the runtime.

### T6 — Live shadow, canonical cutover, query, and worker release

- Files: production state only through `scripts/activate_knowledge.py`; `docs/tasks/361/report.md`.
- Test: delivery check — `scripts/activate_knowledge.py preflight --json` reports current main, exact DB/
  vector/state paths, native-session checksum, scope denominator, zero destructive operations, and exits
  zero. This command is first frozen by T5; it cannot be a pre-implementation live RED without mutating
  the wrong checkout.
- AC: after T1–T5 are merged to `main`, run preflight → shadow → safe `/api/restart` → verify; prove a
  real MCP `knowledge` query in each registered resumable scope with zero cross-scope rows; verify the six
  receipts and unchanged native-session checksum; run canonical 2→3 → safe restart → repeat real MCP
  query; release/reconnect stale workers only at turn boundaries; projection and historical path hashes
  unchanged. If any check fails, stay/return legacy and stop before the next transition.
- blocked-by: T5 and merge to `main`

## Verification matrix

After each ticket, run its exact node and the pre-existing T2/T3b/T4/T7 regression set. Before merge:

```text
/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest \
  docs/tasks/361/acceptance/test_live_activation_behavior.py \
  docs/tasks/315/acceptance/test_t2_task_behavior.py \
  docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py \
  docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py \
  docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py -q
```

Then run the full suite once, without starting any provider/model/eval. Any `uv.lock` modification stops
the task. Live commands run only from merged `main`; no worktree test app may load live TG credentials.

## Review route

No model review: provider/model/eval/review calls are explicitly forbidden. Phase 2 review is mechanical:
each requested behavior maps to a named immutable assertion; each ticket has files, exact command, AC,
and acyclic dependency; the test must collect normally and fail on the missing runtime behavior rather
than import/collection/setup.
