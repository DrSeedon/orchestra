# V-1234 — eval default apps

Scope from the worker brief: disable apps only in the evaluation actor's managed
CODEX_HOME before startup. Keep ordinary config composition, CLI flags and the
strict residual MCP guard unchanged. No live provider or benchmark operations.

Supplied evidence: separate private metadata-only probes contrasted the default
codex_apps entry with an empty registry after features.apps=false. The exact failed
run response was not saved; the probes do not establish that run's exact response.
No private probe artifacts were supplied or reproduced here.

Initial source finding: connect() writes the managed config before
_connect_unlocked() starts the process. Allowed base scalars are carried, but base
feature tables and MCP servers are deliberately not copied. The eval override must
precede [features.sleep_tool] to keep apps in the parent TOML table.

Initial check blocker: the broker's uv 0.11.28 created .venv successfully, but the
mapped backend/eval/home test invocation stopped during collection because
tests/test_eval_admission.py imports scripts.wf_adapters and scripts.wf_run, and
scripts/ is absent from this source copy. scripts/check_instruction_contract.py
and root CLAUDE.md are also absent. Do not fabricate these dependencies or weaken
the tests. Raw command output is ignored under raw/.

Pre-fix regression check: the six new parsed-TOML/startup cases ran with frozen uv,
offline. All three ordinary cases passed; all three eval cases failed at the
intended apps assertion (KeyError: apps), before fake process startup. Base apps
was absent, true or false. This establishes a red control without live CLI calls.

## Result and checks

Production change: three lines in `_prepare_codex_home()` add `[features] apps=false`
only when `_evaluation_actor_id` is set, before the existing sleep-tool table.
No change to eval_admission.py, ordinary runtime flags, effort, routing or quota.
CHANGELOG records the bounded source fix and activation limit.

Tests parse the generated config at fake process spawn, initialize and thread/start
for eval and ordinary managed actors, with absent/true/false base apps. They also
check stale managed config replacement, preserved allowed base scalars, unchanged
base file, disabled sleep_tool and unchanged ordinary MCP selection. Admission
tests now include explicit codex_apps and unknown residual entries, retaining the
existing orchestra/missing-data/pagination cases and zero-send assertion. The
existing positive fakewire returns the explicit empty data/nextCursor=null shape.

All Python commands used provisioned uv 0.11.28, frozen lock, default .venv.
After initial dependency setup, every command used --offline. No alternate runner.
TMPDIR and pytest base directories were inside ignored raw/; runs were sequential,
nice=10 with oom_score_adj=1000. No provider CLI/account/service/SSH/live DB calls.

| Check | Actual result | Ignored raw evidence |
| --- | --- | --- |
| Initial mapped backend/eval/home invocation | Collection blocked: scripts missing; no tests executed | raw/baseline.log |
| New cases before fix | 3 expected eval failures, 3 ordinary passes; 110 deselected | raw/red.log |
| `uv run --frozen --offline python -m pytest tests/test_backend_codex.py tests/test_codex_home_lifecycle.py tests/test_codex_managed_state.py -q` | 124 passed, no skips | raw/fixed.log |
| Source mutation apps=false → apps=true, new cases | 3 eval failures at `assert True is False`, 3 ordinary passes; 110 deselected. Fixed source restored in finally and checked byte-for-byte | raw/mutation.log, raw/mutation-summary.log |
| `uv run --frozen --offline python -m pytest tests/test_eval_admission.py -q` after edits | Exit 2, collection error: `ModuleNotFoundError: No module named 'scripts'`; residual-MCP negatives and positive fakewire remain unrun | raw/eval.log |
| `uv run --frozen --offline python -m pytest tests/test_instruction_contract.py -q` | 9 failed, no skips: every child command lacks scripts/check_instruction_contract.py | raw/instructions-tests.log |
| `uv run --frozen --offline python scripts/check_instruction_contract.py` | Exit 2: required script absent | raw/instruction-contract.log |
| Imports and compile() of the three changed Python files via frozen uv | Passed | raw/import-and-syntax.log |

Imported app (relative to this copy): `app/__init__.py`; backend is the sibling
`app/backend_codex.py`. The absolute path of the private workspace is deliberately
omitted from this public report; the exact private evidence stays with the host
owner (ignored `raw/` logs, not published).

## Limits and handoff

The source fix and executable backend/home regression checks are ready. Acceptance
is incomplete until the parent reruns eval/admission fakewire and instruction
checks in the full source checkout. No full suite, model review or live probe was
run. The 9 instruction failures are missing-copy prerequisites, not green checks.
No benchmark replay/resume/reissue, grant/ledger mutation, merge, push or activation
was performed. Platform imports this copy to task-V-1234/fix-eval-default-apps;
parent acceptance/merge/push and normal idle activation are required before any
next separately authorized benchmark run. No claim about live process behavior.

Final review: changed-source diff and notes passed the existing app.secret_mask
form-based scan; added lines have no trailing whitespace. The reviewed patch and
scanner output remain ignored in raw/source.patch and raw/diff-review.log. No
other production file was edited.
