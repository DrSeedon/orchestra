# knowledge-pipeline

- `bg_create(type="run")` starts commands from the main checkout, not this worker worktree; invoke worktree-local scripts by absolute path. #454's relative runner resolved to `/mnt/data/Projects/Python/orchestra/.orchestra/tasks/454/...` and failed before the model.
