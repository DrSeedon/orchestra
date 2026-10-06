# V-738: staged dynamic workflows

## Implementation

Extended `dynamic_workflow` with `mode="stages"` and a `stages` argument while retaining the existing `tasks` + `mode="parallel"`/`"chain"` call shape. A stage may carry explicit `tasks`, or a shared `prompt` with an `items` list; each item is expanded into its own prompt by replacing `{item}` (string values stay plain text, other JSON values are serialized). Stage-level model/schema defaults apply to each expanded task.

The tool writes normalized, expanded JSON to `data/workflow-runs/<run-id>/request.json`; `wf_run` and its resume command receive only that file path. Limits are 20 stages, 1,000 expanded tasks, and 1 MiB of specification. Task count is checked before expanding each stage, and serialized prompt size is checked incrementally and again against the final JSON size.

The engine executes tasks within each stage through the existing `parallel` and `agent` methods. Each task receives all `WorkflowValue`s from the previous stage in `inputs`, which the engine serializes as structured data separately from the prompt. One engine instance owns the semaphore and `Budget` for the full run. If a stage has an incomplete task, later stages do not run; resume replays completed calls and can continue when the caller provides a sufficient budget/call limit. The manifest preserves per-stage results and the notification summary flattens them for delivery.

The MCP tool description includes a single-call MiroFish example: 50 personas read a page, react over three result-fed rounds, and one analyst writes a report. The prompt module now directs multi-stage jobs to the tool and keeps workflow files for custom Python branching or transformations.

## Verification

- `uv run --frozen python -m pytest tests/test_dynamic_workflows.py tests/test_wf_run.py -q` — 59 passed.
- `uv run --frozen python -m pytest tests/test_bg_jobs.py -q` — 59 passed, 1 skipped; existing durable run artifact validation and delivery remain green.
- `python -m compileall -q app/mcp_stdio.py scripts/wf_run.py` and `git diff --check` — passed.
- `python scripts/check_instruction_contract.py` — passed.
- The MCP construction test expands two object items, writes a spec larger than 64 KiB, and verifies the command contains its path without carrying prompt contents in argv.
- The engine tests verify every task in stage two receives both stage-one results, that budget spent in stage one blocks stage two, and that resuming with a higher cap reuses stage one and completes stage two.
- Mutation check: temporarily replacing the previous-stage `inputs` with an empty list made `test_stages_give_every_next_stage_task_all_previous_results` fail on the missing `Structured inputs`; restoring the implementation made that committed test pass.
- Compatibility tests exercise the existing MCP `parallel` and `chain` call shapes; CLI tests execute a file-backed parallel spec and verify resume retains its spec path.
- Imported app module path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-workflow-tool/app/mcp_stdio.py`.

No live model run was needed. Python changes require an Orchestra restart initiated by the owner before the new stages mode is available in the running MCP process.
