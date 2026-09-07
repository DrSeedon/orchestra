# #534: browser fixture stdout backpressure

## Question

Context: browser tests stall at changing positions within `tests/test_frontend.py`.
Change under test: remove accumulated server-output backpressure, compared with the
existing undrained subprocess pipe. Outcome: reproduce a blocked writer and unavailable
HTTP, recover the same process by draining output, then run three consecutive normal
suites plus reverse and seeded random order. No changes outside `tests/` are authorized.

## Hypotheses and falsifiers

- Server logging fills its undrained stdout pipe and blocks the HTTP event loop.
  Falsifier: the server remains responsive while blocked, or draining the pipe does not
  restore HTTP. Direct intervention refuted both falsifiers (see evidence.txt).
- Browser contexts/pages accumulate until the browser stalls. Falsifier: stable resources
  before the failure and HTTP recovery without restarting or changing the browser.
  Baseline teardown samples stayed at at most one context/page; the pipe intervention
  restored HTTP without touching Chromium. This does not exclude unrelated browser bugs.
- Database growth/port collisions cause the stall. Falsifier: the same DB and bound port
  answer after only pipe drainage. That happened. Baseline DB samples were 651264 bytes,
  logs table empty; reverse repeat had two usage snapshots instead of one.

## Confirmed mechanism

`_start_dashboard_server` used `stdout=subprocess.PIPE`, merged stderr into it, and only
read output after startup failure. Successful startup left the pipe unread throughout
both consumers (`test_frontend.py`, `test_system_chat_entry.py`). The helper dates to
commit 740d749a (git log -S 'stdout=subprocess.PIPE' -- tests/test_frontend.py).

Controlled capacity 4096 bytes, unread 3934 bytes: server PID 1175249 was in `pipe_write`.
An HTTP request timed out in 2.039 seconds. Reading 3934 bytes from that pipe, without
restarting either server or Chromium, restored HTTP 200 in 0.313 seconds. The remaining
162 bytes were insufficient for the pending write; unread bytes need not equal capacity.
The pipe blocked again after further output. The reproduction was explicitly stopped by
exact descendant PIDs at 181.4 seconds; exit -9 is intentional, not a test pass.

CONFIRMED — direct measurement establishes this fixture defect. LIKELY — this mechanism
explains the historical migrating stalls, but their original blocked-process snapshots
were not retained here, so identity with every historical stall is not proven.

## Counter-evidence and limits

The original helper passed normal runs in 136.74 and 132.85 seconds and a reverse-order
repeat in 494.39 seconds. These runs did not naturally fill the pipe; a green run alone
cannot establish absence of the defect. `reverse2` is a misleading old directory name:
its collected order was normal; `reverse_actual2` actually reverses and repeats twice.

Module-scoped Playwright stays intact: it fixes the independent asyncio loop conflict
recorded in #318. Test post-teardown resource sampling cannot see every transient page;
the controlled failure run eventually had three contexts/pages after test failures.
No claim that every leak or every browser test is fixed follows from this investigation.

## Implementation and focused checks

The server writes to a temporary regular file in the isolated DB directory, preventing
pipe-capacity backpressure. Diagnostic reads seek to the final 4000 bytes. Existing
startup-failure and teardown paths close the handle; Popen launch failures also close it.
Files disappear on close. Disk-full errors remain possible, unlike bounded-pipe deadlock.

Regression tests launch an isolated HTTP subprocess through the real fixture helper,
write 256 KiB before accepting HTTP, and verify responsiveness/cleanup. A second child
writes the same amount and exits 7: its error status and bounded diagnostic tail survive.
These guard subprocess lifecycle and diagnostic delivery, not document wording.

`uv run --frozen python -m pytest tests/test_dashboard_server_output.py -q`:
`2 passed in 5.81s`. Restoring the original helper made both committed tests fail:
`2 failed in 15.85s`. Imported app module:
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-browser-fixture/app/__init__.py`.

## Browser validation

Job bg-110876868a runs both consumers in fresh processes: normal three times, reverse,
random seed 534. The runner uses nice 15, ulimit -v 17179869184 KiB (Chromium reserves a
large virtual address space), an RSS-tree limit of 2 GiB, exact descendant PIDs, and
180-second individual test timeout. The virtual-memory limit is not the RSS protection.
All five runs: `105 passed, 1 skipped, 7 deselected`. Pytest times: normal
161.01 / 159.67 / 181.95 s; reverse 148.33 s; seeded random 186.36 s.
The recorded START lists mechanically confirm three identical normal orders, an exact
reverse, and a random permutation of the same 106 nodes. No sampled pipe_write after
the fix. This covers both shared-helper consumers, not all browser files in the repo.
Full-set inventory collection is checked separately.

## Review and pre-existing inventory mismatch

Author: native Codex GPT-6 (session metadata). Consumers and AC are listed above.
Review: не требуется — правки только в tests/ (прямое решение оркестратора).
Luna review artifact is `review.md`: no actionable findings; focused regression command
reported 2 passed. Platform completion separately says `review artifact is blind:
execution never happened`; therefore this report does not claim unconditional approval.
No second review is requested merely to repeat an unchanged diff.

Reviewer found inventory expected 104 frontend browser nodes but collection has 105.
The pre-fix baseline already ran 104 passed + 1 skipped = 105, and neither the marker nor
inventory file changed in this branch. The parent authorized closing this mismatch. The omitted retained node is
`test_mobile_voice_input_records_transcribes_and_cancels`, explicitly skipped since
937ea848 because #365 replaced its synchronous voice-input contract. The same skip
already existed in 067679f3, where #515 introduced inventory. No missing credentials or
browser executable cause the skip. Inventory counts collected nodes, including skips:
104 passing nodes + 1 retained skipped node = 105. The expected count is corrected;
rewriting the obsolete voice contract test remains outside this task.

## Evidence and handoff

`evidence.txt` contains selected raw command outputs and computed RSS/resource maxima.
Raw local runs remain in ignored subdirectories of `tests/.diag534/`.
Tier 1: measured pipe snapshot, HTTP recovery, regression/mutation and browser logs.
Tier 2: actual fixture and consumer source. No external sources used.
KB/personal-memory files are outside the explicit tests-only boundary; parent should
preserve the reusable finding: an undrained long-lived child pipe can stall otherwise
unrelated later tests; measure pipe occupancy and writer wait state before blaming them.

## Completion

Final command: `uv run --frozen python -m pytest tests/test_dashboard_server_output.py
 tests/test_merge_test_gate.py::test_browser_inventory_is_explicit -q` →
`3 passed in 26.58s`. Browser inventory is green and still checks exact per-file counts.
The change does not require an Orchestra restart: only test code and evidence changed.
`git diff --check` and secret-form scanning of the tracked evidence/report/review passed.

Personal-memory check: yes, the pipe occupancy/writer-state/drain intervention is reusable.
No `.orchestra/workers/` edit was made because the assignment explicitly restricts writes
to `tests/`; the memory/KB conclusion above is handed to the orchestrator for persistence.
