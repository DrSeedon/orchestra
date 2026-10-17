## Summary

Reviewed the complete diff between the pinned commits. The capability and isolation changes include a default prompt-module configuration that prevents normal workflow calls from reaching the adapter.

## Findings (blocking/suggestion/question)

### Blocking

- [scripts/wf_run.py](/home/kesha/v918-work/v918-bad-cand-59.r1-atcc0l1_/scripts/wf_run.py:37) names `communication-style`, `user-values`, and `knowledge-and-context` as default workflow modules, but those module files are absent from the pinned pipeline. [build_prompt_modules](/home/kesha/v918-work/v918-bad-cand-59.r1-atcc0l1_/app/pipeline.py:568) raises `FileNotFoundError` for a missing module, and `WorkflowEngine.agent()` calls it before dispatching the model. Consequently, default workflow agent calls fail before any adapter runs.

## Verdict

NEEDS WORK — remove or provide the missing default modules so ordinary workflow calls can dispatch.