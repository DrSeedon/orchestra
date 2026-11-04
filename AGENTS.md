# Orchestra — repository guide

Orchestra coordinates persistent AI agents through FastAPI, SSE, SQLite, provider CLIs
and stdio MCP. Work on Orchestra itself follows this file. Agent behavior in projects
belongs to `.orchestra/pipelines/default/prompts/`; keep each rule with its owning module.
`CLAUDE.md` must remain a symlink to this versioned `AGENTS.md`. Keep root instructions
below 16 KiB; put task evidence and history in their directories, not here.

## Find the relevant code

- `app/session.py`: agent turns, injected messages, context compaction and recovery.
- `app/manager.py`: session registry, worker creation, lifecycle, role prompt assembly.
- `app/merge_operations.py`: durable merge operations, exact-HEAD acceptance, idempotency
  and recovery. `app/routes/merge_operations.py` exposes the HTTP surface.
- `app/merge_test_gate.py`: bounded merge-time test selection; it is not the full suite.
- `app/pipeline.py`: pipeline validation, role resolution, prompt layers and effort.
- `app/models.py`: model registry, aliases and provider/worker admission;
  `app/quota_gate.py` owns quota admission. Catalog presence alone is not permission.
- `app/prompting.py`: safe template substitution, instruction and memory delivery.
- `app/kb_index.py`: the knowledge index injected into agent prompts.
- `app/`: API, provider backends and dashboard code; `tests/`: behavior and integration
  contracts; `scripts/`: checks and tooling; `deploy/`: deployment configuration.
- `.orchestra/pipelines/default/`: manifest, roles, reusable modules and skills.
- `.orchestra/kb/`: accepted knowledge; `.orchestra/tasks/<id>/`: task evidence;
  `.orchestra/workers/`: worker memory. Historical conclusions are not current policy.

Read the current implementation and relevant tests first. Use `rg`/`rg --files` and
targeted reads. Consult symbol history for a regression or unclear prior decision.
Search knowledge on demand using the knowledge module; a new topic needs both a file
and a descriptive entry in `.orchestra/kb/README.md` to reach agents.

## Scope and worktrees

- Preserve existing changes. Work in an assigned branch/worktree and edit repository
  files only there. Do not switch a managed worker's branch or edit the main checkout.
- Deliver the authorized outcome. Research ends at findings; a recommendation does not
  authorize implementation. Do not change neighboring systems or add speculative rules.
- Inspect `git remote -v`: `origin` is our public remote. Leave other remotes alone;
  no force-push, discarded commits or shared-worktree stash operations.
- Successful tests do not authorize merge, push, deployment or service startup. Workers
  report their result; merge authority and lifecycle gates belong to the orchestrator.
- Existing authorization covers bug fixes and red CI repair; it does not cover data
  deletion, new spending, disruptive restarts or consequential architectural choices.
  After an authorized push, check CI with `~/.local/bin/gh-clean run list`.
- Before closing a worker, preserve accepted work or its findings and rejection reason
  with the source branch. A preserve tag alone is insufficient; follow worker-lifecycle.

## Runtime and safety

- Do not deploy or run `git pull` on the VPS yourself. Automatic Orchestra restarts are
  owned by the idle watcher: merged Python is newer and no agent is active on two checks.
  A disruptive restart or a laptop restart needs explicit authorization. Never restart
  telegram-bot-api. After a permitted restart, check cut_names and recover interrupted work.
- Do not coordinate infrastructure through other projects' orchestrators. Verify service
  state read-only; files on disk are not proof that a live Python process loaded them.
- On the VPS, resource priority is kesha-bot-vps, Orchestra, then agents. Do not change
  infrastructure limits or move jobs to another cgroup to bypass them.
- Before heavy work, check available memory and the process cgroup limits. Keep tests
  sequential unless parallelism is justified. On the owner's laptop use nice=15 and
  MemoryMax=2G; use `/mnt/data` for large temporary files. Stop only precisely owned PIDs.
- Do not send secrets, protected data or live infrastructure to Hub workers. Follow
  model-routing for safe source bundles and protected local work. Disabled providers
  remain disabled; provider failure does not authorize a paid fallback.
- New paid API routes require permission. Harness admits exact free routes and only
  paid routes in PAID_HARNESS_ROUTES in `app/models.py`. Claude API credits are opt-in
  for specific tasks, never the ordinary-worker fallback.

## Data and implementation conventions

- Keep one canonical owner for policy and state. API/configuration/current code outrank
  historical measurements; an index or projection cannot replace its source.
- Prefer small, explicit changes following surrounding style. Enforce safety at the
  operation it protects; unavailable optional metadata must not block a safe native path.
- Preserve the chat's fresh network snapshot followed by SSE. Do not add an IndexedDB
  history mirror or stale-while-revalidate chat cache.
- `data/` is ignored runtime state. `db.add_log`, `live_broker.publish` and delivery
  copies preserve content verbatim for the owner. Do not mask this display path.
- `app/secret_mask.py` owns masking at publication boundaries. Scan raw exports before
  putting them in tracked artifacts or sending them outside. Never publish credentials,
  `.env` contents or secrets from logs. A secret in private storage is not itself a leak;
  report a confirmed public leak immediately without unilateral rotation.
- Use isolated test state, never the production database, Telegram tokens,
  NOTIFY_SOCKET of a live service or real provider CLIs without an explicit probe goal.
  Copy live SQLite using backup(), not a filesystem copy.

## Validation and completion

Use the repository virtual environment, not system Python or an unrelated `pytest`:

```sh
uv sync --frozen --group dev
.venv/bin/pytest tests/test_default_pipeline.py tests/test_prompting.py tests/test_local_delegation_prompts.py
uv run --frozen python -m pytest <test-paths> -q
uv run --frozen python scripts/run_tests.py
uv run --frozen python scripts/check_instruction_contract.py
```

Run focused checks for the changed contract; the full runner is for full-suite validation.
Tests should cover behavior, authorization, failure/retry, concurrency and recovery where
relevant. Do not weaken frozen acceptance tests. For prompts, preserve module delivery,
role isolation and template contracts rather than pinning editorial wording.

Before handoff, inspect the diff, required checks, secret boundaries and unrelated changes.
Report the outcome, actual checks including failures/skips, evidence paths and remaining
risk. Name the absolute imported `app` path so the checked checkout is unambiguous.
Use `report_bug` for platform defects when available; keep task evidence under the task
directory. Distinguish measured behavior from proposals and on-disk changes from activation.
