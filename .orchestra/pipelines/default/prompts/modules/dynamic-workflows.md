## Dynamic workflows

Use the `dynamic_workflow` tool for bounded one-shot batches: independent tasks, result-fed chains, or multiple stages with parallel tasks. A stage can list full prompts or provide one prompt with an `items` list and `{item}` placeholder. Every task in a stage receives all results from the previous stage as structured inputs. Use this for generated rounds, simulations, and final analysis. Limits are 20 stages, 1,000 expanded tasks, and a 1 MiB specification. The tool saves the specification outside the command line, starts a durable `wf_run` job, then wakes you with the outcome, short answers and result paths; do not poll for completion.

Choose `parallel` when tasks do not depend on each other. Choose `chain` when each task should receive the previous task's result as structured input. Choose `stages` when each task in a stage should receive all results from the preceding stage. Luna is the default; choose other models only as allowed by model-routing. Astra and Sol remain owner-selectable for manual orchestrator sessions, but dynamic-workflow tasks using either are refused.

Claude API credits are opt-in per task (or as a stage default): set `billing: "api_credit"` only when explicitly requested; without that field, Claude tasks use the subscription route. Exhausted or expired credits refuse the selected task and never switch it to subscription.

Use an ordinary worker for a task that needs ongoing conversation, managed task lifecycle, or mergeable repository changes. Use a workflow file with `wf_run.py` only when the steps require custom Python logic between calls, such as conditional branching or transforming intermediate data. The file remains useful for those cases; ordinary task lists and multi-stage batches should use `dynamic_workflow`.
