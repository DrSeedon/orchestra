# #422 — Plan: activate and measure the exact-free Harness lane

Approved scope: remove the two live activation doors, prove one real `:free` Harness turn, then
run the frozen N=30 replay from `protocol.json`. Periodic work, watchdogs, auto-spawn and prompt
changes are excluded.

Immutable RED commit: `1605003b59de71d43f0d954f417e805651359176`.
Protocol SHA-256: `87fd1f1c46afb5666f0f39e5e866545ac74a11287e09aaec0e5833407dc0d5bd`.
Earlier RED commits `cbb7ccea4c0132310c61f60602aecb316fd28540` and
`48096877eb7579a95c2874827ea7b78e4f93c957` are excluded: Luna proved the first could
accept a zero-request summary and the second still trusted self-authored receipts/outcome labels.
`248d913d353b8ca0ac15c07125fff7edd45317bc` is also excluded: final Luna review found a
self-supplied signing key, mismatched bwrap policy owners and incomplete tool-env enforcement.
`162bca94d59cb26dc1673b6c1901666a62a4b0a1` is superseded only because the orchestrator
explicitly removed absent Harness `turn_usage` from T2 acceptance; the revised test was observed
RED on its missing canary receipt before the receipt was written.

## Current code decision

No production diff is justified for activation:

- `POST /api/models/catalog/refresh` already calls `refresh_catalog()` and persists/registers the
  exact-free text+tools catalog.
- `PATCH /api/models/catalog/flags` already validates a Harness route and persists
  `dashboard`/`agents` flags.
- `POST /api/sessions` already routes a registered Harness model through `HarnessBackend`.

The task-local replay runner uses `OpenRouterClient` + `AgentLoop` directly, not
`HarnessBackend.connect()`: the key is passed as a constructor argument, then removed from
`os.environ` before the loop. Path-confined read/write/edit/glob/grep remain in the controller;
the only arbitrary-code tool (`bash`) is replaced with a per-call bubblewrap subprocess over a
small IPC result boundary. Thus the controller keeps OpenRouter network/key, while model-executed
shell has neither. `MCP={}` and `app.harness.llm.MAX_RETRIES=1` are set before inference.

## Rejected isolation arm

`systemd-run --user` is not an alternative. The local arm observed `NETWORK_ESCAPE` and
`MAIN_ENV_READABLE`; the independent production-shaped control returned verbatim:

```text
Failed to connect to user scope bus — $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined
```

`bwrap --unshare-net` returned `NETWORK_DENIED`, rc=0. Full evidence is in `preflight.md`.

## Files and state

Planned task-local files:

- `docs/tasks/422/run_free_lane_replay.py` — controller, corpus selection, bwrap tool execution,
  graders and result writer.
- `docs/tasks/422/evidence/` — catalog/roster/corpus/probe/raw-run/summary receipts.
- `docs/tasks/422/report.md` — measured result and failure taxonomy.
- `docs/kb/auto-work.md` — append/replace current #422 facts with live activation and measurement.

Approved live state changes through existing APIs:

- `kv.model_catalog_cache` — populated by catalog refresh.
- `kv.model_flags` — the two static exact-free routes enabled for dashboard and agents.
- one durable session `task422-free-canary` plus its logs/turn_usage receipt.

Production `app/` files, `pipelines/`, `docs/kb/README.md`, #418 territory and tests outside the
frozen #422 oracle are not touched unless a demonstrated blocker forces a revised plan first.

## Tickets

### T1 — Activate catalog and the two static exact-free routes

- Files/state: live `kv.model_catalog_cache`, `kv.model_flags`; task evidence receipt only.
- Action: snapshot production `sessions`; call catalog refresh with internal auth; verify every
  registered Harness route is exact `:free`; PATCH the two static routes to
  `dashboard=true, agents=true`; snapshot sessions again.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q -s docs/tasks/422/acceptance/test_free_lane_422.py::test_t1_catalog_cache_and_static_free_flags_are_live_without_session_writes`
  — committed RED in `1605003b59de71d43f0d954f417e805651359176`.
- RED: `PRODUCTION_SESSIONS_BEFORE=572 PRODUCTION_SESSIONS_AFTER=572` then
  `AssertionError: T1 catalog cache is empty`.
- AC: the named command is green; both counts are equal; cached IDs contain both static routes;
  both stored flags are exactly `{dashboard: true, agents: true}`; every live registered Harness
  route is available exact `:free`, text→text, tools-capable and catalog-eligible; no enabled
  paid/unsuffixed route can hide beside the two statics.
- blocked-by: none

### T2 — Prove one real exact-free Harness turn

- Files/state: ignored canary cwd under production `data/`, durable session/log/turn_usage;
  `docs/tasks/422/evidence/canary.json`.
- Action: select one enabled exact-free static route; create `task422-free-canary` through the
  normal session API; send a bounded one-line read-only prompt; wait for its terminal receipt;
  record response/model/runtime/attempt count without copying the key.
- Test: `TASK422_CANARY_NONCE=<fresh receipt nonce> TASK422_CANARY_NOT_BEFORE=<operation UTC start> /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q -s docs/tasks/422/acceptance/test_free_lane_422.py::test_t2_one_real_exact_free_harness_turn_is_successful`
  — committed RED in `1605003b59de71d43f0d954f417e805651359176`.
- RED: `AssertionError: T2 canary receipt is missing`.
- AC: the named command is green; it finds `backend_type=harness`, exact `:free` model,
  terminal idle/waiting status plus exact input/text/end_turn logs containing a unique run nonce;
  receipt binds exact session ID + timestamps to a fresh operation nonce and
  `TASK422_CANARY_NOT_BEFORE` supplied by the current invocation, so an old successful canary cannot
  mask the new run. `turn_usage` is recorded as an observed count but is not an oracle: the first
  Harness turn produced 0 usage rows, so N=30 uses runner/raw receipts and logs. The check itself
  keeps session count unchanged.
- blocked-by: T1

### T3 — Execute the frozen N=30 two-route replay

- Files: `docs/tasks/422/run_free_lane_replay.py`, frozen `protocol.json`,
  `docs/tasks/422/evidence/**`.
- Action: freeze the mechanically selected three-route roster before task inference; classify the
  eligible 60-day population using precedence from protocol; sample 6×5 tickets with the frozen
  seed; run pilot then 60 scored attempts with two routes/ticket; enforce bwrap, MCP={}, environment
  allowlist, isolated DB/counter/session, no remotes/solution object, exact `:free`,
  `MAX_RETRIES=1`, 900-attempt hard stop; preserve every raw outcome.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q docs/tasks/422/acceptance/test_free_lane_422.py::test_t3_frozen_n30_replay_is_complete_and_protocol_bound`
  — committed RED in `1605003b59de71d43f0d954f417e805651359176`.
- RED: `AssertionError: T3 replay summary is missing`.
- AC: the named command is green; summary is bound to the frozen protocol and to hashes of the
  exact-cutoff population, corpus, catalog, roster and isolation manifests. The test recomputes
  precedence+seed selection and hash-ranked roster from transport-canary survivors, enforces two
  distinct balanced routes/ticket, 9 pilot + 60 raw hash-bound receipts with nonzero attempts and
  provider model equality, per-run DB/counter/session/remotes/alternates/solution/oracle receipts,
  both false-premise cases in high-risk with evidence-bearing `honest_stop`, positive/negative/no-op
  controls, unchanged sessions/logs/KV/tasks/OpenRouter-counter state, actual attempt sum ≤900 and
  the decision from measured metrics. The supervisor signs raw HTTP/control/outcome/state payload
  with an ephemeral Ed25519 key unavailable to model tools; acceptance verifies the signature,
  binds summary outcomes to signed raw outcomes, cross-checks corpus strata against population,
  independently executes the exact bwrap negative/positive controls, and recomputes per-route,
  per-stratum and weighted success. A fabricated or no-op summary cannot pass.
- blocked-by: T2

### T4 — Publish the measured fraction and failure taxonomy

- Files: `docs/tasks/422/report.md`, `docs/kb/auto-work.md`, review artifact.
- Action: compute per-route and best-of-two weighted success with the frozen uncertainty/decision
  rule; separately count `honest_stop`, `silent_invention`, explicit wrong answer, availability,
  budget and safety outcomes; include isolation receipts and exact attempt counts; update KB facts.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q docs/tasks/422/acceptance/test_free_lane_422.py::test_t4_report_and_kb_publish_fraction_and_failure_modes`
  — committed RED in `1605003b59de71d43f0d954f417e805651359176`.
- RED: `AssertionError: T4 report.md is missing`.
- AC: the named command is green; machine-readable report metrics equal replay summary metrics,
  decision, HTTP attempts, per-route fractions and recomputed failure counts; rendered report
  contains those exact values plus manual acceptance time/isolation/review; KB fact contains exact
  decision and weighted result. Heading-only prose cannot pass.
- blocked-by: T3

## Ordering and stop conditions

`T1 → T2 → T3 → T4`. The chain is intentionally serial: later evidence depends on live activation
and the exact canary route. Stop before inference on any of:

- route ID is not exact `:free` or provider reports a different paid/unsuffixed model;
- production key/environment appears in tool-visible state;
- bwrap negative controls do not fail or positive workspace controls do not pass;
- production session count changes during the isolated replay;
- protocol hash or any oracle path differs from the RED commit;
- eligible population cannot supply six tickets in any frozen stratum.

No criterion is relaxed after a result. A stop is reported as premise/protocol failure, not converted
into a smaller or differently stratified benchmark.

## Post-ceiling resolution — authorized, not externally re-reviewed

Luna Round 3 left three security blockers. The executable-artifact review ceiling was exhausted;
the orchestrator accepted all three and explicitly authorized one post-ceiling refreeze without a
fourth Luna or auxiliary Sol. Resolution:

1. **Self-signature removed:** the own runner is non-adversarial; cryptographic receipt provenance
   was deleted instead of pretending a receipt-supplied public key was trust. Safety remains bound
   to exact routes, raw outcomes and independently executed isolation.
2. **One exact bwrap owner:** `bwrap_policy.py` is used by runner and verifier and pinned by source
   SHA-256 `138a46601ab2ed955094eed690367a358972f0c29f237f79b0606b0e4c0bfc59`.
3. **Exact tool environment:** the exec environment must equal `TOOL_ENV`; any extra key refuses.
   `HTTPS_PROXY`, `HTTP_PROXY`, lowercase variants, ALL/NO proxy and all key/token names are also
   explicit forbidden controls.

Post-ceiling RED `162bca94d59cb26dc1673b6c1901666a62a4b0a1` was not reviewed by an external model;
this is explicit in the artifact as required. Its independent policy probe returned all eight expected
true controls. No OpenRouter inference, catalog refresh, flag mutation or canary occurred before refreeze.

## Implementation-review ceiling resolution — authorized, not externally re-reviewed

Luna implementation Round 3 exhausted the executable-artifact ceiling with one new P1: offline
`reconcile()` verified the current summary and receipts against each other, but did not bind them to
the independently audited immutable source at commit `867b517f`. The orchestrator verified that the
commit exists, accepted the finding, and authorized a post-ceiling fix without a fourth review round.

The dedicated paired-forgery oracle was frozen RED in `4e58c322`: it edits one receipt and its current
summary descriptor consistently, so the pre-fix local digest check accepts the pair and the test fails
with `paired summary+receipt forgery was accepted`. The implementation must load
`reconciliation-provenance.json`, read the source summary and raw receipts with `git show`, verify the
source summary SHA-256 and each receipt digest/identity, and accept current receipt state only when it
equals either the immutable source or its deterministic reconciled form. Any paired divergence fails
closed. This post-ceiling oracle and implementation were explicitly **not reviewed by an external
model**; provider inference and the frozen N=30 replay are forbidden during this resolution.
