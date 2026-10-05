# V-720: one-call dynamic workflows

## Result

Added the `dynamic_workflow` MCP tool in `app/mcp_stdio.py`. One call supplies task prompts, optional schemas and models, `parallel` or `chain`, budget/call/concurrency limits, task ID, and repository. The tool validates inputs and agent model flags, defaults each task to Luna, rejects Astra and both Sol IDs, then creates one existing durable `run` job. Its config carries the runner command, caller repository as cwd, manifest path, and a success check for `complete: true`; `bg_jobs` already delivers command output to the caller. No database schema or existing tool contract changed.

Extended `scripts/wf_run.py` with `--tasks-b64`, which accepts the complete declarative task spec in its CLI arguments. Parallel mode submits all prompts to the existing engine concurrently. Chain mode runs tasks in order and passes each preceding `WorkflowValue` as structured input. The engine journal, budget, result artifacts, and resume handling remain in use; the resume command carries the same encoded spec. The CLI appends a bounded summary with successful count, short textual answers when available, and result paths.

Rewrote `.orchestra/pipelines/default/prompts/modules/dynamic-workflows.md` in English: use the tool for similar one-shot batches and simple result-fed chains; use ordinary workers for ongoing or mergeable work; retain a workflow file for custom Python transformations, branching, or generated multi-stage fan-out. Thus the user-authored file is no longer needed for ordinary lists, while `wf_run` and its file mode remain useful for custom logic.

## Checks

- `uv run --frozen python -m pytest tests/test_dynamic_workflows.py tests/test_wf_run.py -q` — 55 passed.
- `uv run --frozen python -m pytest tests/test_bg_jobs.py -q` — 59 passed, 1 skipped. This covers existing required-artifact validation and background result delivery.
- `python scripts/check_instruction_contract.py` — passed.
- `python -m compileall -q app/mcp_stdio.py scripts/wf_run.py` and `git diff --check` — passed.
- Imported module paths during these checks: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-workflow-tool/app/mcp_stdio.py` and `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-workflow-tool/scripts/wf_run.py`.

## Live Luna runs

The first smoke job `bg-f9f983fc2c` (`V-720-live-two-luna`) used schema `{"type":"string"}` for both tasks and `max_calls=2`. Both Luna calls returned as model turns but their plain text did not parse as JSON strings; schema retries were deferred by the call limit. Its manifest had `complete=false`, `partial_reason=budget`, `dispatched_calls=2`, and `result=[null,null]`. This established the need to accept plain text for string schemas and to give retries room in the limit. Evidence: `data/workflow-runs/V-720-live-two-luna/journal.jsonl` and `manifest.json`.

After the string-schema fix, live job `bg-e46e480592` (`V-720-live-three-luna-2`) ran three Luna tasks with `max_calls=6`: two without schemas and one with `{"type":"string"}`. It completed with 3/3 successes. The following is the notification summary appended by `wf_run` and delivered verbatim by the background job:

```text
WORKFLOW_SUMMARY run=V-720-live-three-luna-2 successful=3/3 complete=true manifest=/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-workflow-tool/data/workflow-runs/V-720-live-three-luna-2/manifest.json
1. MAPLE
2. ORBIT.
3. CEDAR
```

The complete manifest and journal are in `data/workflow-runs/V-720-live-three-luna-2/` in this worktree.
