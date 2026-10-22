# V-1027 — model picker request regression

Replaced the literal `JSON.stringify` source assertion in
`tests/test_frontend.py::test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result`
with execution of the production picker and reason helper in the project's
`dashboard_browser` fixture. Clicking a picker item captures the real `api` call and parses
its serialized body. The three cases verify the endpoint, POST method, selected
`model`, current `scope`, and `model_reason` for hub Claude. Own Claude and hub Sol
must send no reason and must not prompt for one. All nine remaining source assertions
are unchanged. No production code changed.

The `dashboard_browser` fixture causes collection to mark these three cases as browser tests.
Updated `test_browser_inventory_is_explicit` from 102 to 105 frontend cases to
account for that required change: collection recognizes both `browser` and
`dashboard_browser`, so switching fixtures does not change the count. The project
fixture starts an isolated dashboard server. Picker calls are intercepted by the
test's `api` stub and never call real providers or open a production database.

Follow-up after orchestrator rejection: the first version requested `browser`
at the top of the module. The orchestrator measured 9 failed / 122 errors on the
full file (`Runner.run() cannot be called from a running event loop`), while the
picker passed on its own. Changed to `dashboard_browser` and moved the picker
test into the browser section, after every async test in this file. Placement
matters because `dashboard_browser` also keeps sync Playwright alive for its
module lifetime; just renaming the fixture at the top would still start its
loop before the async tests. The payload assertions and cleanup are unchanged.

Local check: `node .orchestra/tasks/V-1027/check-picker.cjs` passed all three
model selections and rejected missing-model, missing-scope, and missing-reason
mutations. This supplemental offline check executes the test's own JS setup and
production functions using a minimal DOM. Raw output: `offline-check.log`.
It is not a Chromium or pytest result.

Attempted:
`uv run --frozen python -m pytest tests/test_frontend.py::test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result -q`.
Exit 127: the hub's uv shim reports uv unavailable; raw output: `pytest.log`.
Python did not start, so no `app` module was imported and no imported path can be
reported. Playwright execution, serial full-file regression and browser inventory
collection remain for the orchestrator's environment as agreed in the assignment.
The local follow-up check verifies fixture selection, placement after all async
tests, inventory fixture recognition and the unchanged expected count of 105;
it does not claim that pytest collection or Chromium execution passed.
Follow-up output is in `followup-check.log`. Attempting the serial command
`uv run --frozen python -m pytest tests/test_frontend.py tests/test_merge_test_gate.py::test_browser_inventory_is_explicit -q`
again exited 127 before Python started (`followup-pytest.log`).

No Git metadata is present in this worker copy. Per the hub-copy rules, no commit
was attempted; the platform imports and commits changed files on the assigned branch.
Suggested commit header: `#V-1027: verify model picker request payloads`.

The change is confined to tests and task evidence. There is no service restart or
deployment requirement. Task artifacts contain synthetic model/scope/reason inputs
and local tool errors only; no secrets or raw production data were used.
