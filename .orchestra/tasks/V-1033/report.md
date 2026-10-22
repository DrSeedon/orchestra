# V-1033: make worker model prompts follow model-routing

## Changes

- Replaced four stale worker-default statements with references to model-routing: the orchestrator role, the orchestration owner-decision paragraph, Step 0.5, and the critical delegation rule.
- Updated the dynamic-workflows module and the dynamic_workflow tool description to require model selection through model-routing while accurately documenting the existing omitted-model fallback.
- Added the local-work exceptions to the model-routing hub bullet: deployment or infrastructure on this host; secrets, credentials, client or personal data; and projects dedicated to a specific model, including model-evaluation sandboxes.
- Clarified that the workflow restriction on Astra and Sol concerns our own Codex pool, consistent with model-routing allowing hubsol.
- No execution logic, model aliases, configuration, tests, or frozen acceptance tests changed.

## Non-obvious behavior

The dynamic_workflow implementation still uses luna when a task omits its model and has no explicit stage model. Stage expansion obtains its fallback from stage.get in app/mcp_stdio.py:3417. Flat tasks use the default_model parameter in _normalize_dynamic_task at line 3567. A task-level model overrides the stage default. Normalization then resolves the alias and applies the existing manual-only and agent-admission checks; the fallback does not guarantee that the model is admitted.

This is an implementation-policy mismatch, preserved deliberately under the task instruction. The prompt now instructs callers to supply a model selected through model-routing. Changing the runtime fallback remains outside this patch.

Prompt assembly in app/pipeline.py:631 reads the role layers and shared modules from the pipeline files. The dynamic_workflow docstring is also tool-facing prompt text, so it was updated with the same truthful fallback description.

## Checks and limitations

- Inspected resumed files before editing; the reported contradictory lines were still present and no prior task artifacts or outbox were present.
- Searched all supplied files under .orchestra/pipelines/default and app with a case-insensitive multiline search for Luna followed by is the default. No matches remain, including the previously wrapped orchestration lines. The empty result is saved in stale-default-search.log. This was a manual source check; no prompt-wording tests were added.
- Reviewed all changed source regions and checked the five edited source files for trailing whitespace and conflict markers; none found. Changes contain only task prose, routing names and existing source references; no raw logs or credentials were copied.
- Rechecked task override, stage inheritance, omitted-model fallback, and admission behavior in the current code. No persisted state or recovery behavior changes are introduced.
- Attempted nice -n 15 uv run --offline --frozen python -m pytest tests/test_dynamic_workflows.py -q with temporary files directed inside this task directory. It exited 127 before Python started because uv is unavailable on this hub and cannot forward this checkout. The exact diagnostic is in pytest.log.
- The supplied copy also lacks scripts/, which the existing dynamic-workflow tests import. Runtime prompt assembly, workflow tests, and Python syntax/import checks could not run here and need verification in the full checkout.
- Imported app path: unavailable because no Python process was started. The inspected app source is <hub-user>/orchestra-ws/…/app

## Delivery

Suggested platform commit header: V-1033: make worker model prompts follow model-routing

Files were edited in place. No manual git operations, service restarts, deployment, external calls, or provider calls were performed. The platform owns copying and committing the result to task-V-1033/fix-prompt-defaults.
