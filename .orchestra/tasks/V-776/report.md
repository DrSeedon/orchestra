# V-776 — Dynamic workflow chat card

## Result

The dashboard now renders mcp__orchestra__dynamic_workflow as a workflow card instead of raw JSON and a queued-run line. The header shows mode, task/stage counts, models, budget, call/concurrency limits, task ID, and repository. Task prompts are expandable. Similar prompts collapse to one shared template and list only their differing values; stages declared as one prompt plus items show the template once and list the items.

The card fetches status from GET /api/bg/workflows/{run_id}. It shows completed, running and failed counts, cost against budget, elapsed time and per-task errors. After the journal is finalized, it shows short answer previews; full answers load on expansion through a second read-only route scoped to the run and result index, so repeated status polls do not retransmit outputs. The card polls while a run is active and retains the original call arguments if the run files are missing or the new endpoint is not available yet.

New run specs retain card metadata and a stable label for every task. The runner carries that label into journal events and the manifest so live events map back to the correct prompt, including parallel stages. The read-only endpoint accepts only a validated run ID under data/workflow-runs; a resolved symlink outside that directory is rejected. It reads only the known request, manifest, journal and step-result files.

Before the server restart, the hot-loaded frontend can already show launch parameters, collapsed prompt/template and values; the live section says run files are unavailable. After the restart adds the endpoint, opening the chat history again loads saved runs, and active cards poll for updates.

## V-167 source data

The supplied run directory exists in the shared data store. Its request has mode parallel, 10 tasks, and gpt-6-luna for each task. Their prompts differ at the run-number value and share the rest of the text. The manifest records complete=false, partial_reason=error, spent_usd=0, dispatched_calls=0, and 10 prepare_failed steps. The journal has 10 prepare_failed events; the recorded error says the supplied repo path was a linked worktree rather than a primary Git repository. Thus the requested screenshot demonstrates the actual saved V-167 run and its preparation failure, not a currently running job.

Screenshot: [workflow-v167.png](workflow-v167.png).

## Verification

- node --check app/static/js/chat.js, Python compileall for changed modules/tests, and git diff --check — passed.
- uv run --frozen python -m pytest tests/test_workflow_cards.py tests/test_dynamic_workflows.py tests/test_routes_surface.py tests/test_wf_run.py -q — 68 passed. Coverage includes the endpoint's valid, missing, and symlink-escape run IDs; result retrieval; full answer expansion; the missing-file fallback; active journal labels; repeated prompts; prompt-plus-items stages; runner label persistence; and the new route surface.
- Imported app module: /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py.
- Imported app module: /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py.

The screenshot uses V-167's saved request, manifest and journal, rendered through the same backend detail projection used by the endpoint. It shows one prompt template and the full differing run numbers 8401–8410, along with the actual ten preparation errors.
