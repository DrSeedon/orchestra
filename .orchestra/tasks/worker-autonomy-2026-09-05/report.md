# Worker autonomy — 2026-09-05

## Approved contract

The owner approved removing method-level bureaucracy, not authority boundaries.
One agent owns an approved outcome and chooses investigation, planning, implementation,
verification and useful delegation. Research-only requests remain research-only.

## Changes

- Full-cycle no longer requires three phases, two approvals, frozen RED tickets and child
  implementation for every task. Plans and intermediate artifacts are proportional to need.
- Clarification is not model failure. Ordinary correction does not force a new model/session.
- Workers may edit necessary code, tests, fixtures and shared config in their own worktrees.
  Explicit exclusions and independently frozen acceptance criteria remain binding.
- owned_dirs retains its existing storage/API shape but becomes advisory. Spawn, reassignment,
  branch transition and legacy-path migration no longer reject overlapping labels.
- Reassembly upgrades the exact old generated ownership suffix; custom complete prompts and
  explicit task exclusions remain untouched. Stored old task messages are not rewritten.
- Research methods are guidance: no mandatory execution of every rejected alternative, fixed
  source quota or fixed repeat count. Claims still require relevant evidence and calibration.
- Prompt owners, role metadata and tool descriptions were updated together. No additional
  tools, permissions, models, services or configuration flags were introduced.

## Why the previous design caused friction

Narrow incidents became universal rules: frozen acceptance protection expanded into a ban on
all test edits; coordination metadata became a directory reservation; avoiding repeated failed
attempts became refusing to answer questions. Full-cycle mandated every stage even when the
user said not to wait. The replacement scopes checks to their concrete risk.

Old prompt-policy tests that required these abolished restrictions were replaced with delivery
checks for autonomy AND authority boundaries. They do not pretend to measure model quality.
Runtime tests exercise overlapping creation, persistence, concurrent updates, branch switching,
legacy path migration and prompt refresh with a preserved custom-override control.

## Static prompt measurement

Measured with build_system_prompt("default", role), without task, project rules or tool schemas:

| Role | Before bytes | After bytes |
|---|---:|---:|
| full-cycle | 72,475 | 59,501 |
| worker | 36,005 | 34,834 |
| orchestrator | 68,152 | 66,922 |

Full-cycle is 17.90% smaller. This is not a measured speed, cost or quality improvement.
No paid model A/B benchmark was run.

## Verification

Tests run with the main venv interpreter importing app from this worktree, under
MemoryMax=2G and nice=15, with NOTIFY_SOCKET removed. The initial focused integration
passed 529 tests. The expanded run caught a missing run_fan delivery hint (665 passed,
one failed); the hint is restored conditionally, not as mandatory delegation.

Negative control: injected the original HEAD ownership validator into an isolated test
process (no file or service mutation). Both overlapping-area behavioral tests failed
with the original ValueError, including the concurrent update case; pytest exit 1.
Thus these tests detect the removed runtime blocker, not just new prompt wording.
Final expanded rerun: 666 passed in 43.90 seconds. Two multiprocessing fork warnings
from the cross-process merge arbitration test remain; no test failed.
Instruction-contract checker and git diff --check passed.

No auxiliary Sol review was launched: no explicit additional Sol-run authorization.
Verification is deterministic tests, negative control and self-review, not a claimed
independent model approval. Task Observer informed the grouping of repeated process
errors; no new skill or global dotfile was created.

## Deployment boundary

Worktree: /mnt/data/Projects/Python/orchestra-worker-autonomy.
No service restart, main merge, VPS deployment, live DB rewrite or worker interruption.
The running server does not execute this branch. Python changes require explicit deployment
and restart; prompt refresh then upgrades generated overlays. A complete custom prompt or an
old explicit task exclusion still needs an intentional owner revision.
