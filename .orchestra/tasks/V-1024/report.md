# V-1024 — hub pool admission and provider-limit notifications

Suggested platform commit subject: `V-1024: enforce permanent hub Sol default and named Claude exceptions`

## Review corrections — reported windows and offline isolation

Review was resumed on the supplied merged copy (orchestrator identified its merge as `449eba6d`). The two blockers were confirmed in source: `_usable` invented a requirement for named 5h and Weekly windows, and a fixture local to hub workspace tests did not protect the sibling V-1025 effort tests.

`_usable` now checks every window the account actually reports, independent of label/kind. A missing provider window does not block. The supplied real-relay-shaped fixture has Codex Weekly-only values 59/28/31/95 and Grok Weekly-only values 65/99; it yields 4/4 usable Codex accounts and 2/2 usable Grok accounts, and permits `hubsol` admission using the same cache. Any reported window at the strict/configured threshold still excludes the account.

Conservative choice for absent data: an account with no windows, or invalid usage data, is **unknown** and does not count as usable. The sanitized provider summary exposes an `unknown` count. When the pool has no positively usable account, admission is refused with the alternate model hint; an unknown account does not prevent admission through another account with reported headroom. Relay unavailability still warns and allows work, as previously specified.

The shared autouse fixture `tests/conftest.py::_offline_hub_pool_fetch` now stubs the fetch boundary and resets the cache/lock for every test. Relay-parser/cache tests explicitly restore the production fetch function only after installing `_FakeHub`; the not-configured case installs a null factory. A regression test makes construction of a real relay transport fail immediately and verifies ordinary capacity checks never invoke it. This also protects `tests/test_hub_effort.py` without adding local capacity patches there. The merged `HubBackend.retarget_model` order remains capacity check first, then target effort resolution; its V-1025 effort forwarding was not edited.

Actual offline test entrypoint (available virtualenv interpreter, unchanged nice=15 / 2 GiB limit):

```sh
PYTHONPATH=. "$VENV_PYTHON" .orchestra/tasks/V-1024/run_checks.py tests/test_hub_effort.py tests/test_hub_model_reason.py tests/test_hub_model_reason_frontend.py tests/test_hub_pool.py tests/test_hub_pool_frontend.py tests/test_quota_admission_e2e.py tests/test_hub_workspace.py
```

**214 passed in 31.81s**, `review-tests.txt`. Imported application: `app/__init__.py`, verified to resolve inside this workspace. The runner now prints a workspace-relative import path; no absolute hub workspace path is written into evidence.

`review_mutation_check.py` caught **3/3** additional mutations: requiring a missing 5h window again, granting capacity to accounts without windows, and removing the shared fetch stub. The isolation mutant is caught by the transport-construction guard before any connection. Output: `review-mutations.txt`; all mutated sources were restored byte-for-byte. Existing pool mutation-script anchors were updated to the reported-window implementation, without changing their protected behaviors.

Post-restoration effort/pool check: **51 passed in 4.64s**, `review-restored-tests.txt`. No live relay query, service restart, deployment or repository commit was performed here. The private-copy platform still owns committing. Retained task evidence was checked for credential-shaped content and absolute workspace paths before handoff.

## Owner clarification at 17:10 — permanent default and enforced Claude exceptions

The hub bullet now states owner decision, 2026-10-22 as permanent policy: every task defaults to `hubsol`, including bug fixes, features, tests, refactors, research and reports. Creative prose, video/scene direction and visual/aesthetic judgment explain the Claude exception; existing Opus-only cases remain reasons for `hubopus`. Project Sol bans still take precedence. The former Codex-class/Claude-class split is absent.

`model_reason` is an optional tool argument whose non-empty, stripped value is mandatory for hub Claude aliases and canonical IDs. One validator (`app.models.validate_model_reason`) owns the named rule `hub_claude_reason_required`. Both MCP tools validate it before any API call. The manager also validates direct spawn calls before side effects, and `AgentSession.change_model` validates direct model changes. Sol and our own models need no reason. Existing model permissions and the whole-pool gate still apply: a valid reason with zero usable Claude accounts is refused with the `model='hubsol'` hint.

Reasons reach the session, database getters, live and unloaded dashboard lists, and reconstructed sessions. The additive `session_model_reasons` table binds a reason to session ID and selected model, with cascade cleanup; the session and reason are saved in the same transaction. A pending target reason lets the existing model-transition persistence save the correct reason before the wrapper returns. Failed switches retain the previous reason; selecting Sol clears it. Fresh schema and existing v3 initialization create the metadata table idempotently, without rebuilding the existing sessions table. No live database was migrated here.

The dashboard renders the reason as text next to the model in the worker card and active-session header. Its Claude picker and manual creation flow request the reason. Text is not interpreted as HTML. CHANGELOG has handwritten Added/Changed/Fixed entries for the final V-1024 behavior.

Follow-up checks (same offline virtualenv runner, nice=15 / 2 GiB limit as below):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/venv/bin/python .orchestra/tasks/V-1024/run_checks.py tests/test_hub_model_reason.py tests/test_hub_model_reason_frontend.py tests/test_hub_pool.py tests/test_hub_workspace.py tests/test_hub_pool_frontend.py tests/test_quota_admission_e2e.py tests/test_quota_gate.py tests/test_db.py tests/test_session.py tests/test_change_model_unloaded.py tests/test_mcp_stdio.py tests/test_mcp_quota_gate.py tests/test_manager.py tests/test_models.py
```

Result: **994 passed in 89.67s**, `reason-tests.txt`. This includes 51 new reason tests plus an executable dashboard test. Both rejection and permission arms, all three hub Claude aliases, direct server calls, tool argument propagation, persistence/reload, model/reason transaction consistency, failed changes, default/own-model exemptions and reason-plus-pool composition are covered.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/venv/bin/python .orchestra/tasks/V-1024/reason_mutation_check.py
```

Result: **12/12 additional mutations caught** by failing repository tests; `reason-mutations.txt`. Mutations disable central or server checks, drop tool/API arguments, lose database or restored state, persist the previous reason during a transition, hide either dashboard display, or bypass the pool gate despite a named reason. The runner confirmed every mutated source was restored byte-for-byte.

Post-restoration run: **94 passed in 15.32s**, `reason-restored-tests.txt`. The server restart notice arrived after that run had already written its complete success summary; sources were checked before continuing.

The refreshed test policy then required removal of a literal prompt-wording test from `tests/test_hub_pool.py`. It was deleted rather than updated to match the rewritten policy. Remaining pool behavior tests: **27 passed in 4.80s**, `final-pool-tests.txt`. The earlier 994/94 totals include that now-removed prose-only case; implementation code was unchanged after those successful runs.

The source diff was reviewed and retained in `reason-diff.patch`; new regression tests are source files in `tests/` and included in that diff. Native Orchestra messaging tools are not exposed in this hub runtime; final parent reporting uses the existing identity-bound hub outbox. No repository commit, deployment or restart was performed by this worker. The platform commits this private copy, and Python enforcement needs the owner's authorized service restart to become live.

## Changes

- The model-routing hub bullet defaults all work to `hubsol`. Claude requires a task-specific need and pool headroom; project-level Sol bans retain priority.
- `app/hub_pool.py` counts usable accounts across the entire provider pool, without publishing account rows, identifiers or emails. Every window reported by the provider must have usage strictly below `MULTICODE_HUB_POOL_THRESHOLD_PCT` (default 100; valid range greater than 0 through 100). A window omitted by the provider is not required. Accounts without valid window data remain unknown and, like rejected accounts, do not count. An inactive account can count even when its credentials are not currently loaded.
- Spawn checks capacity before worktree/task/session creation. Session admission, model switching, backend retargeting and actual hub turns share this rule. Exhausted Claude suggests `model='hubsol'`; exhausted Codex suggests `model='hubsonnet'`. Existing project/model permissions are still checked.
- Admission reuses the existing 300-second success / 60-second failure cache. An unavailable relay or missing provider allows work with a warning; actual backend turns emit a visible status warning.
- Provider usage/rate-limit failures in launch errors, terminal thread status, run errors or the final reply yield a failed turn with a named limit and alternative model. The existing identity-bound bridge sends one notice to the worker's own parent. A failed notice is named in the worker error. Notices contain a safe limit category rather than raw account errors. Context-length/turn-count failures and ordinary successful reports about limit handling are not treated as provider quota failures.
- The dashboard shows usable/total accounts for each provider, with Russian translation, while retaining the active account's window details.

## Offline verification

`uv --version` failed: the hub shim reports that uv is unavailable and this copy cannot forward it. No dependencies were installed. Used the existing `/tmp/venv/bin/python` through the task-local runner, with nice=15, a 2 GiB address-space cap, bytecode/cache disabled, NOTIFY_SOCKET removed and temporary files under this task directory.

Command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/venv/bin/python .orchestra/tasks/V-1024/run_checks.py tests/test_hub_pool.py tests/test_hub_workspace.py tests/test_hub_pool_frontend.py tests/test_quota_admission_e2e.py tests/test_quota_gate.py tests/test_change_model_unloaded.py tests/test_backend_routing.py tests/test_session.py
```

Result: **529 passed in 48.02s**. Output: `tests.txt`.

Imported app: `/home/<hub-user>/orchestra-ws/vmi3407579/hub-d096a386e52e4192/app/__init__.py`.

Coverage includes both provider arms, inactive account headroom, reported windows, strict/configured threshold boundaries, unavailable relay/cache reuse, refused and allowed spawn/model switch, session preflight and backend refusal before upload, reply/status/launch limit errors, exact-parent notification, ordinary successful reports, non-quota failure categories, redaction and executable JavaScript dashboard rendering.

Mutation command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /tmp/venv/bin/python .orchestra/tasks/V-1024/mutation_check.py
```

**12/12 mutations killed by failing assertions**, covering active-only checks, either-window acceptance, inclusive threshold, unavailable-relay blocking, bypassed session/spawn/model-change/backend gates, missed reply/status limits, omitted parent notification and loaded-count dashboard rendering. See `mutations.txt`. Every mutated source was restored; the final 529-test run followed restoration and the context-limit exclusion.

## Operational limits

No live relay/provider calls, service restart, deployment or repository commit/push was performed. The platform commits this private copy. Python changes require the owner's authorized service restart to affect the running process. Capacity is a cached observation, not a reservation; concurrent consumption can still reach a provider limit after admission. New provider error wording may require extending the text classifier.

Generated temporary test repositories and empty runtime stubs were removed before handoff. Only the requested source/test changes and task-local evidence are retained. Changed source and retained evidence were checked using the repository's credential-shape filter.
