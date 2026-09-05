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
the host project/home filesystems are absent; only read-only OS directories and explicit
work/runtime mounts are exposed. An initial shell-only preflight failed creating /work on
a read-only root; the mount layout was corrected before any model call or result.
Authentication stays in a private scratch runtime; no raw log or credentials go to Git.
CLI executable and standard OS tools are available; no live Orchestra MCP or review service.
The same adaptation text explains this in both arms.

This is a small prompt-level pilot on synthetic tasks, not a production app-server/MCP test.
The lack of orchestration tools may particularly disadvantage a mandatory-delegation workflow.
One result per arm per task cannot separate random model variation from the prompt effect.
Before the usable batch, the old implementation trial could not launch the code-mode host:
the native executable was mounted without its required sibling binary. Excluded result and
known usage are in luna-excluded.json; the next trial was interrupted and has no final usage.
The mount now exposes the complete vendor runtime. A separate functional preflight executed
python3 through the actual Luna shell tool (633947, exit 0); its usage was 19,896 input,
10,752 cached, 112 output. These setup attempts are not treatment results. This correction
changes neither task, prompt nor evaluator; the usable batch starts fresh in a new scratch.
Research judgment is not blind: the evaluator authored the prompt change; expose the actual
answers and limitations rather than turning subjective interpretation into a numeric score.

Protected-file checks concern benign local sentinel/test fixtures, not adversarial security.
No claim of production safety or general model quality follows from these checks.
