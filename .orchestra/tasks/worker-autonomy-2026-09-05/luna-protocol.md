# Frozen Luna pilot

Compare old full-cycle at 7fb6dc66 and new at e5db9749 through Codex CLI 0.153.4,
gpt-5.6-luna/high, no Fast override, six fresh sessions maximum, 240 seconds per session.
Sequence: implementation old/new, frozen new/old, research old/new. Sequential under 2 GiB.
No model substitution or automatic retries after transport/runtime failure.

Primary outcome: executable requirements and protected-file preservation, plus a manual
evidence-grounded reading of the research answer. Report missing results, not just successes.
Secondary: unnecessary stops, model tool items, elapsed time, input/cache/output tokens and
flat API-equivalent using the existing Luna card (0.2/0.02/1.2 per million).
Do not call this a measured subscription debit or a statistically reliable speed ratio.

The evaluator and source revisions are frozen before model execution. Evaluator code is outside
the child's filesystem. Each run has only its own fixture, no shared git object database,
no other run's result, no host home or project mounts. Native Codex runs within outer bwrap;
the host filesystem is read-only except the explicit work/runtime mounts.
Authentication stays in a private scratch runtime; no raw log or credentials go to Git.
CLI executable and standard OS tools are available; no live Orchestra MCP or review service.
The same adaptation text explains this in both arms.

This is a small prompt-level pilot on synthetic tasks, not a production app-server/MCP test.
The lack of orchestration tools may particularly disadvantage a mandatory-delegation workflow.
One result per arm per task cannot separate random model variation from the prompt effect.
Research judgment is not blind: the evaluator authored the prompt change; expose the actual
answers and limitations rather than turning subjective interpretation into a numeric score.

Protected-file checks concern benign local sentinel/test fixtures, not adversarial security.
No claim of production safety or general model quality follows from these checks.
