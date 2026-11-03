# V-1261: CI 41615549009, change-model quota contract

Source: orchestrator task brief. Reported main revision:
`c8e3e14ce9810f8b58a298c46c34aa276cb62af8` (provided reference, not verified HEAD).
This broker copy has no `.git`; no commit/remote operations are performed here.
Result destination, assigned by broker: `task-V-1261/fix-gemini-ci`.

First reproduction with provisioned uv 0.11.28 and frozen lock:
`uv run --frozen python -m pytest tests/test_mcp_quota_gate.py::test_change_model_is_control_action_even_when_target_bucket_blocked -q`
Result: **1 failed in 18.73s**, exit 1. See `first-red.log`.
Exact failure: `resolve_model('gpt-5.6-sol')` at `app/mcp_stdio.py:2452`
raises ValueError, converted to ApiToolError at line 2459.

Finding: historical readiness labels are synthetic response data in quota tests;
only the actual change-model argument now goes through the real registry resolver.
An obsolete request cannot prove that a valid control operation bypasses quota.
Rejecting unknown models is correct. Keep the resolver and Argon identity/routing
checks intact; repair this request fixture and its fake change-model response.
Leave unrelated historical readiness/spawn fixtures intact.

Planned regression coverage: current Hub Sol canonical ID and alias forward exactly
one control request despite blocked target readiness; retired/unknown and disallowed
Hub requests never forward. Existing V-1257/V-1240 tests cover persisted identity,
scope, forbidden routes, old-session state and queued-delivery recovery offline.
No Phase B, activation, model/provider calls, restart, migration, config or manifest
changes. Parent V-1257 activation/safe smoke remains incomplete; V-1260 untouched.

## Result

Changed only `tests/test_mcp_quota_gate.py` plus this task's evidence:
- Fake REST change-model response echoes its request model instead of a retired ID.
- Existing quota-control acceptance remains and now covers both `hub-gpt-6.1-sol`
  and `hubsol`, with exact forwarded body and no readiness request.
- Four negative cases: retired native ID, unknown native ID, unknown Hub ID,
  registered but disallowed Hub Luna. All refuse before any REST call, including
  when `model_reason` claims owner intent.

This is a fixture defect, not a production quota/Argon defect. No production fix,
retired alias, resolver stub, readiness stub replacement, policy relaxation or
historical fixture sweep was needed. The original acceptance's no-readiness
assertion is retained and its endpoint-only assertion strengthened to exact body.
The initial real failure is direct regression evidence for restoring the retired
request; the added negative case also requires that ID to remain refused.

## Exact validation

Every Python test shell used:
```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
```
Runner verified: `uv 0.11.28 (x86_64-unknown-linux-gnu)`. Default `.venv`, unchanged
`uv.lock`; uv provisioned its pinned dependencies. No replacement runner was used.
Commands ran sequentially under `nice -n 10`, with `oom_score_adj=1000`, output
redirected into this directory. The second test run used repository-local
`TMPDIR="$PWD/.venv/tmp"` for isolated test storage.

Initial RED command above: **1 failed, exit 1**.

Final command:
```sh
uv run --frozen python -m pytest tests/test_mcp_quota_gate.py tests/test_gemini_specialist_v1257.py tests/test_hub_sol_only_v1240.py tests/test_mcp_stdio.py::test_change_worker_model_preserves_history_by_default tests/test_mcp_stdio.py::test_change_worker_model_reports_chat_history_transfer_size tests/test_mcp_stdio.py::test_change_worker_model_surfaces_api_refusal_with_code_and_reason -q
```
Result: **215 passed in 23.31s, exit 0**, no skipped/failed tests. See
`targeted-green.log`. Existing tests include persisted Argon specialist identity,
cross-scope rejection, forbidden Hub models, retained old session state and
queued-delivery recovery; they remain unchanged.

`uv run --frozen python` also imported `app` and verified SHA-256 of all baseline
sources except the intentionally changed test. Imported app (relative; original preserved):
`app/__init__.py [absolute original path SHA-256: cd91312a67a28f9ffcc2cf5506eb06c1b149a8f5a4215e3185200d74463bf362; original: .orchestra/private/V-1261/publication-originals/notes.md; file SHA-256: aae3788b9d89f2df3cdd3d97e2090ab61d0d54b0ee6ad1b28f8ce2a5b2b3b9c3]`.
See `copy-verification.log` for relative import and original reference, all resulting hashes, unchanged
production/lock/manifest checks, Phase A role assertions and patch whitespace /
conflict-marker check. Baselines are in `source-before.sha256`; review patch is
`fix.diff`. Actual changed test SHA-256:
`4739b55089ede2ea2a73932454be2e4d3b683c955b88969596f947f3fc515bbe`.

Resource check before testing: hub available memory 78 GiB; own cgroup limit
52,755,525,632 bytes, current 14,449,344,512 bytes, quota 8 CPUs. One test process,
no browser or additional workers. Logs contain local synthetic reproduction only;
no protected raw CI dump/account paths or credentials were copied or accessed.
The original private trace remains referenced by CI run `41615549009` and the
provided source revision above; neither is claimed to have been fetched here.

## Limits and handoff

No full suite, live model/API, browser, remote infrastructure, actual CI rerun,
merge, push, restart, activation or archive was performed in this copy. `.git` is
absent; the revision above is the orchestrator-provided source reference, not an
invented locally verified HEAD. Broker imports/commits the changed files into
`task-V-1261/fix-gemini-ci`; root must accept, merge/push, verify actual CI, and
archive. Local green does not establish CI green or live process behavior.
V-1257 activation + safe smoke remain not done; V-1260 config/restart await owner.

Final publication-boundary check: `app.secret_mask.mask_secrets` found no
secret-shaped values in the changed test and all six evidence artifacts. The
redundant original test snapshot was removed after producing the diff.
