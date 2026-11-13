# V-1290 — Antigravity turn health

**DONE — all 126 requested focused tests pass (5 + 121); ready for merge.**
The contract owner explicitly authorized updating the obsolete frozen runtime test
to V-1290's tool-error contract. The assertion block now requires visible error tool
results, no error banner and a successful completed turn without `model_error`;
the test name now says `preserves_terminal_success`. No failures, errors, skips or
deselections in the final focused runs. Prior full-suite history and environment
limits are recorded below.

## Changes

- `app/backend_antigravity.py`: current-process assistant output recovers sticky
  retry failures without turn-level error events. No-output failures retain
  credentials/quota/model categories. Partial auth/quota refusals, missing terminal
  results and interruptions remain failures; intermediate replies followed by tools
  or incomplete responses do not conceal auth/quota refusals.
- Tool errors remain visible, deduplicated `tool_result` events with `is_error=True`,
  retaining error/output content; they do not emit a second banner or fail a completed
  turn. Tool identity, arguments and MCP canonicalization are preserved.
- Latest `gen_metadata.idx` is read after process exit using a bounded, read-only
  SQLite connection, including WAL data. A small protobuf decoder extracts occupied
  context and the CLI's actual maximum; malformed, absent, oversized or invalid
  metadata produces `UnknownContext` without failing the turn. Aggregate generation
  token usage is never substituted for occupied context.
- `orchestra-conversation.json` retains cumulative tokens, thinking, call count and
  duration bound to conversation/model/auth generation. Terminals emit non-negative
  deltas; cost is derived from delta token buckets with `cost_is_delta=True` when
  priced. Resume reloads baselines, identity/counter resets rebase them, absent
  fields retain prior baselines, and failed/interrupted terminal spend is accounted.
- `tests/test_antigravity_turn_health.py`: 79 synthetic offline regressions covering
  streams/results, multi-turn recovery/accounting, recreation, resets, old state,
  missing/non-finite counters, protobuf boundaries/corruption and read-only/WAL access.
- `tests/test_antigravity_tools_v1288.py`: updated its non-frozen tool-error assertions
  to the new contract, retaining existing correlation/deduplication checks.
- `tests/test_antigravity_runtime.py`: updated the obsolete frozen tool-error test
  with explicit contract-owner authorization, preserving both assertions that the
  failed tool result remains visible. Other frozen assertions remain unchanged.
- `CHANGELOG.md`: hand-written Unreleased entry with no infrastructure details.

## Scope and findings

- Work is limited to the supplied worker copy; no provider, deployment or restart.
- Terminal retry errors can remain populated after assistant output; tool errors also
  independently overwrite successful terminals in the existing adapter.
- Existing usage is cumulative, and conversation state currently discards accounting
  baselines on every send. Current context is always unknown.
- Frozen `test_t1_tool_error_overrides_terminal_success_and_is_not_silent` in
  `tests/test_antigravity_runtime.py` explicitly requires duplicate error events and
  `ok=False/tool_error`. This contradicts V-1290's required tool-error behavior.
  It was initially preserved and reported separately. The contract owner subsequently
  explicitly authorized its correction; that conflict is now resolved in source.

## Validation

- Contract-owner final focused runs (`contract-owner-tests.log`):
  **5 passed in 5.46 s** for the runtime file and **121 passed in 9.38 s** for the
  tool, turn-health and usage-contract files. This includes all 79 new regressions
  and the corrected runtime tool-error contract. The final commands keep the
  runtime-only `not docs` filter separate so the MCP `docs_extra` test also runs.
  The initial combined-filter check passed 125 tests but deselected that parameter;
  the final two runs replace that incomplete selection.
- Baseline with broker uv 0.11.28: **69 passed, 6 failed, 6 setup errors**
  (`baseline.log`). Five login tests require the unprovided
  `scripts/antigravity-login.sh`; one requires `docs/antigravity-runtime.md`.
  Six browser tests cannot run: Playwright Chromium headless shell revision 1223
  is not installed. These blockers precede all source edits. Do not replace the
  runner, install a browser or fabricate missing source dependencies.
- First focused regression pass: **78 passed, 1 failed** (`regressions.log`). The
  failure was a new read-only SQLite spy's parameter named `uri`, colliding with
  SQLite's `uri=True` keyword. Renamed that fixture parameter; no product or frozen
  acceptance assertion was weakened. Added interruption accounting and refusal
  after intermediate output coverage during source review.
- First complete post-fix run: **146 passed, 8 failed, 6 setup errors**
  (`required-tests.log`). In addition to the baseline blockers and frozen conflict,
  V-1288's non-frozen tool regression expected the same obsolete duplicate banner
  and failed turn. Updated only that assertion block to require retained tool error
  content, no banner and a successful completed turn. Its identity/deduplication
  checks remain unchanged.
- Previous full required run: **147 passed, 7 failed, 6 setup errors in 7.44 s**
  (`final-tests.log`). All 79 new regressions and all 6 usage-contract tests pass.
  Seven failures = the six missing-file baseline failures plus the unchanged frozen
  runtime test requiring obsolete tool-error behavior. Six setup errors = the same
  missing Chromium executable. No checks were skipped or marked xfail.

Final follow-up commands (broker uv 0.11.28, default `.venv`, frozen lock):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1290/tmp"
uv run --frozen python -m pytest tests/test_antigravity_runtime.py -k 'not docs' -q --tb=short --basetemp=.orchestra/tasks/V-1290/pytest-tmp -o cache_dir=.orchestra/tasks/V-1290/pytest-cache
uv run --frozen python -m pytest tests/test_antigravity_tools_v1288.py tests/test_antigravity_turn_health.py tests/test_usage_contract.py -q --tb=short --basetemp=.orchestra/tasks/V-1290/pytest-tmp -o cache_dir=.orchestra/tasks/V-1290/pytest-cache
```

Earlier full-suite command:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1290/tmp"
uv run --frozen python -m pytest tests/test_antigravity_*.py tests/test_usage_contract.py -q --tb=short --basetemp=.orchestra/tasks/V-1290/pytest-tmp -o cache_dir=.orchestra/tasks/V-1290/pytest-cache
```

Broker uv **0.11.28**, default checkout `.venv`, frozen lock. No substitute interpreter.
Imports were verified as this worker copy's `app/backend_antigravity.py` (absolute
path reported in the verification tool output). AST parsing and source/log credential
shape scans passed. Retained logs have checkout/home prefixes anonymized and pass
the private-host marker check. Generated temporary fixtures/cache were removed;
no test/browser/provider process remains in this checkout. Other agents' processes
were not touched. No real credentials, production database, provider call, Git
commit/push, deployment or restart was used.

## Limits and handoff

- The orchestrator reports that the missing login/runbook tests pass in the complete
  checkout, and 125/126 focused tests passed there before this contract correction.
  This is upstream evidence, not a worker-local run. Browser checks still require
  an installed Chromium. The previous full-suite result above remains historical;
  the final owner-requested focused checks are now **126/126 green locally**.
  The missing-source/browser checks were not rerun in this follow-up; their exact
  worker-copy blockers remain documented in the baseline and previous full logs.
- Live CLI recovery remains unverified here; behavior follows the measured wire
  contract supplied with V-1290 and is exercised offline.
- A legacy resumed conversation with no saved baseline reports its first available
  cumulative snapshot as the initial delta; historical usage cannot be reconstructed
  from an absent baseline. Likewise, a process exiting without a result cannot
  attribute unreported spend to that turn; a later cumulative snapshot includes it.
- Future incompatible protobuf metadata falls back to unknown. Unknown model prices
  remain explicitly unaccounted; no new prices or provider routes were added.
