## Dynamic workflows

Use the `dynamic_workflow` tool for a bounded one-shot fan-out of similar independent tasks, such as collecting facts by region, analyzing a list of items, or comparing several options. Pass each prompt, an optional JSON schema and model, the parallel or chain mode, budget and call limits, the task ID, and repository. The tool starts a durable `wf_run` job and wakes you once with the outcome, short answers and result paths; do not poll for completion.

Choose `parallel` when tasks do not depend on each other. Choose `chain` when each task should receive the previous task's result as structured input. Luna is the default; choose other models only as allowed by model-routing. Astra and Sol are unavailable.

Use an ordinary worker for a task that needs ongoing conversation, managed task lifecycle, or mergeable repository changes. Use a workflow file with `wf_run.py` only when the steps require custom Python logic between calls, such as conditional branching, transforming intermediate data, or stages that fan out over different generated inputs. The file remains useful for those cases; ordinary task lists should use `dynamic_workflow`.
