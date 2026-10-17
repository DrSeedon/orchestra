# V-925 — workflow sparse worktree task directory

`wf_run` now loads the default pipeline's worktree configuration and passes the parent `ORCHESTRA_TASK_ID` into sparse pattern generation independently of the workflow branch name. The workflow branch remains `feat/...`; its sparse checkout includes only the parent task's `.orchestra/tasks/<id>/` directory. The `dynamic_workflow` description now states that tasks see only files committed at `base_commit`.

Regression coverage creates a workflow worktree from a fixture repository with reports for V-925 and V-924, then verifies V-925 is present, V-924 is excluded, and the branch remains under `feat/`.

Check:

```text
$ uv run --frozen python -m pytest tests/test_wf_run.py tests/test_sparse_worktree_v821.py -q
....................................................................................... [100%]
87 passed in 19.95s
```

Imported `app`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-wf-sparse/app/__init__.py`.

Restart required: yes. Python changes in `app/workspace.py` and `app/mcp_stdio.py` require an Orchestra restart for the running process to load them. No live worktree or process was touched.
