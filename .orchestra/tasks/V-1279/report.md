# V-1279 result

Fixed a test watchdog race; no demonstrated production no-retry defect.
Source revision supplied by the task: `2305b9fe`; CI run `41820028765`.
Result destination supplied by broker: `task-V-1279/fix-topic-timeout-ci`.
The full source HEAD and the final imported-commit HEAD cannot be reported from this
copy: it contains no `.git`/remote and the platform commits after the worker exits.
The orchestrator must attach those exact revisions at import/acceptance.

## Diagnosis and minimal change

The original test passed in isolation. Adding a single 60 ms delay after writing the
synthetic uncertainty marker makes it fail at the outer 50 ms `wait_for`, with the
same `TG topic create uncertain ... automatic retry disabled` message reported in CI.
The operation's internal 10 ms timeout already fired and persisted the no-retry guard.
The shielded create task's completion still needs event-loop callbacks before its
caller resumes; the outer timer can expire first. This is a demonstrated timing race,
not proof of the exact slowdown on the inaccessible CI host.

Only `tests/test_tg_bridge.py::TestTgLifecycleReliability::test_topic_create_timeout_is_not_blindly_retried`
changes (`fix.patch`). Keep the real 10 ms operation timeout, give the outer hang
watchdog 5 s, and additionally assert cancellation of the fake Telegram request,
no phantom topic, a persisted guard, and no retry after reloading that config.
Original one-call and uncertainty-marker assertions remain. Runtime code, dependency
lock and configuration remain byte-identical; hashes checked. No frozen acceptance
assertion was removed or weakened, and no live Telegram/service/database/CLI was used.

## Actual validation

| Check | Result | Evidence |
| --- | --- | --- |
| Original targeted test | 1 passed, 4.53 s | baseline.log |
| Original + 60 ms delayed synthetic persistence | Expected failure: outer TimeoutError, 2.61 s | repro-original.log |
| Fixed lifecycle class + same delay | 11 passed, 3.02 s | focused-delayed.log |
| Both bridge modules, offline | 225 passed, 5 skipped, 5.08 s | bridge-suite.log |
| Fixed test + bypassed retry guard | Expected failure: original assertion sees 2 calls | mutation-retry.log |
| Fixed test + forgotten guard on config reload | Expected failure: restart assertion sees 2 calls | mutation-forget-on-load.log |

The 5 skipped checks require the unavailable ffmpeg/ffprobe tools (`mp4_file` fixture).
Full repository tests and CI itself were not run; neither deployment nor service
restart applies to this test-only broker result.

Runner: provisioned **uv 0.11.28**, default local `.venv`, pinned `uv.lock`.
Every pytest command used `uv run --frozen python -m pytest ... -q` and `nice -n 10`;
test process OOM score was 1000. Setup fetched only locked dependencies. Subsequent
suite and mutation runs also set `UV_OFFLINE=1`. Tests used synthetic mocks/isolated
SQLite and config paths; TMPDIR and --basetemp were inside the task directory.

Imported package:
`<CHECKOUT>/app/__init__.py`.
Interpreter and tg_bridge absolute paths: `validation-metadata.txt`.

## Reproduction commands

From the root of this copy, with the provisioned runner:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1279/tmp"
export PYTHONPATH="$PWD/.orchestra/tasks/V-1279:$PWD"
export UV_OFFLINE=1
mkdir -p "$TMPDIR"
echo 1000 > /proc/self/oom_score_adj
nice -n 10 uv run --frozen python -m pytest tests/test_tg_bridge.py::TestTgLifecycleReliability -q -p timing_probe --basetemp=.orchestra/tasks/V-1279/tmp/focused
nice -n 10 uv run --frozen python -m pytest tests/test_tg_bridge.py tests/test_tg_bridge_instance_guard.py -q --basetemp=.orchestra/tasks/V-1279/tmp/bridge
nice -n 10 uv run --frozen python -m pytest tests/test_tg_bridge.py::TestTgLifecycleReliability::test_topic_create_timeout_is_not_blindly_retried -q -p mutation_probe --topic-mutation=retry --basetemp=.orchestra/tasks/V-1279/tmp/retry
nice -n 10 uv run --frozen python -m pytest tests/test_tg_bridge.py::TestTgLifecycleReliability::test_topic_create_timeout_is_not_blindly_retried -q -p mutation_probe --topic-mutation=forget-on-load --basetemp=.orchestra/tasks/V-1279/tmp/forget
```

The last two commands must fail. `timing_probe.py` and `mutation_probe.py` are opt-in
proof artifacts, not auto-loaded test fixtures. To reproduce the original failure,
restore only `fix.patch` on a disposable copy, then run the targeted test with
`-p timing_probe`; keep the preserved original failure log as the baseline evidence.

## Public-artifact sanitization follow-up

Identifying broker checkout paths in this report, the three failure logs and
validation-metadata.txt were normalized to `<CHECKOUT>`. Relative source paths,
traceback line numbers, exceptions, assertions, guard logs, timings and reproduction
commands are retained. The unnormalized logs were not duplicated into tracked files;
the actual failures and method remain in the sanitized evidence. Original and
sanitized content hashes are recorded in sanitization-manifest.json.

No product/test/dependency source changed during this follow-up. The existing
result-sha256.txt hashes were verified before and after the edits. No pytest rerun
was necessary for path-only evidence edits; the recorded test results are from the
previous run. A scan of every task artifact found no identifying absolute checkout
paths remaining.

No exact new HEAD is available inside the broker copy: `.git` is absent, and the
platform creates the result commit only after this turn ends. The orchestrator must
record that resulting full SHA after import. `2305b9fe` remains only the task-supplied
abbreviated source revision; it is not presented as a newly created HEAD.
