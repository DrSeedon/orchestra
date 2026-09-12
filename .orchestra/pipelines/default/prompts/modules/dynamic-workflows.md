## Dynamic workflows

Use scripted workflows for bounded one-shot steps with explicit inputs and machine-checkable
outputs: parallel extraction, comparisons, then dependent stages. Ordinary `spawn_worker`
is for continued conversation, managed task lifecycle and mergeable implementation work.
Only spawn-capable roles launch workflows; terminal workers ask their parent.

Write a Python workflow file under the assigned task. It supports top-level await:
```python
result = await parallel([
    lambda: agent("First complete task and input", model="luna"),
    lambda: agent("Second complete task and input", model="luna"),
])
assert all(value is not None for value in result)
```
`agent(..., schema={...})` validates JSON and retries at most twice; success is a
WorkflowValue (`.data`, `.result_path`, `.workspace_path`), failure can be `None`.
`pipeline(items, stage1, stage2)` passes each stage's results to the next stage.

Launch through `bg_create(type="run", command=...)`, then end the turn. Use absolute paths:
`uv run --frozen --project /home/kesha/orchestra python /home/kesha/orchestra/scripts/wf_run.py /absolute/task/workflow.py --repo /absolute/target/repository --run-id TASK-unique --budget-usd 1 --max-calls 6 --max-concurrency 2`.
Set `ORCHESTRA_TASK_ID` and `ORCHESTRA_SCOPE` in the command to the assigned task/project;
redirect output to its task directory. The runner is in the Orchestra installation, even
when the target project is elsewhere. `--repo` must be the primary Git root, not a linked
worktree; calls start from that repository's current committed branch. Quote shell paths. These are subscription CLI calls;
`budget-usd` is an API-equivalent stopping estimate, not a hard spending or quota reservation.
Choose limits for the task. Luna is the default; Astra only for complex work that Luna
cannot handle, with explicit approval for that additional Astra run. Sol is not a workflow
destination. The model-routing module owns exceptions and auxiliary-model approvals.

Read `data/workflow-runs/<run-id>/manifest.json` under the runner installation: require
`complete=true`, successful steps and the expected result. Exit code alone is insufficient.
Use the manifest's `resume_command` after interruption; completed steps are replayed from
journal, ambiguous dispatched steps are not blindly rerun. Keep workflow inputs stable.

Each call is ephemeral: no session conversation/history, agent messaging lifecycle or
automatic merge. Writable calls get isolated worktrees; inspect their archived results
before integrating. No automatic recovery from arbitrary external side effects. Defaults
include tools/network/MCP and four workflow rule modules, not the full role prompt; supply
all task context explicitly. Restrict capabilities only with `capability_reason`.
