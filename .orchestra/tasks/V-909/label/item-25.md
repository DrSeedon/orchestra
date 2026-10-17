# item-25

Commit under review (in /home/kesha/orchestra, read-only): `45e3bbcd9faa676c386ea2f4dab5e6d15876a0f3`
Subject / date:
#494: freeze capability and isolation oracles
2026-09-05

The diff reviewed is `git -C /home/kesha/orchestra show 45e3bbcd9faa676c386ea2f4dab5e6d15876a0f3 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the pinned commits. I found one blocking issue in the default workflow prompt modules.

## Findings

### Blocking

- [scripts/wf_run.py](scripts/wf_run.py:37): The default module list includes `communication-style`, `user-values`, and `knowledge-and-context`, but those files are absent from `.orchestra/pipelines/default/prompts/modules/`. Every `WorkflowEngine.agent()` call that uses the defaults passes these names to `build_prompt_modules()`, which raises `FileNotFoundError` before dispatch. This makes the default workflow path unusable.

## Verdict

NEEDS WORK — add the missing modules or change the defaults to modules present in the pipeline.
