# #506 T1 oracle-command correction

Superseded command:

```text
uv run pytest -q .orchestra/tasks/506/test_t1_review_size_gate.py .orchestra/tasks/506/test_t1_review_size_gate_edges.py
```

Observed import path in every failure traceback:

```text
/mnt/data/Projects/Python/orchestra/app/mcp_stdio.py
```

Cause measured from the worker process:

```text
PYTHONPATH=/mnt/data/Projects/Python/orchestra
```

Corrected command and RED result:

```text
uv run python -m pytest -q .orchestra/tasks/506/test_t1_review_size_gate.py .orchestra/tasks/506/test_t1_review_size_gate_edges.py
FFFFFFFF                                                                 [100%]
E       AssertionError: T1 missing complete-diff review size gate
E       AssertionError: T1 missing fail-safe numstat parser
8 failed in 0.63s
```

Observed corrected import path:

```text
/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/review-policy/app/mcp_stdio.py
```

Oracle files stayed byte-identical to `25c3b4f8` and `c25e6632`; only the named command changed.
The complete command output is preserved verbatim in `.orchestra/tasks/506/red-command-output.txt`.
