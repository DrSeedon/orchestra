Targeted tests pass (`109 passed in 7.85s`), but the routing policy still permits author-controlled downgrading for high-risk surfaces not in the mandatory-Sol list, enabling the exact review bypass the contract prohibits.

Review comment:

- [P1] Define a non-author-controlled high-risk floor — /home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/pipelines/default/prompts/skills/codex-debate.md:30-32
  blocking: The policy says “Применяй сверху вниз; более высокий risk floor всегда побеждает дешёвый маршрут,” but outside the five mandatory-Sol surfaces it never defines who or what sets that floor. For high-risk concurrency, data-loss, external-contract, or load-bearing changes outside those categories, a Sol/Luna author can label the work `low/medium`, take Luna, and bypass the required Opus request. Make high-risk classification derive from an explicit surface taxonomy or an independent task/orchestrator classification rather than the author's report.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-16T11:49:10Z)

## Re-review status

- Prior P1 — **FIXED**. High-risk now derives from changed-consumer taxonomy or upstream orchestrator classification; ambiguity defaults to high-risk.
- High-risk, weak-oracle, and non-compact work routes directly to Sol before any Opus cross-family addition.
- **NEW BUG:** none.
- No new blocking regressions found in the scoped diff.

Evidence quote from the changed policy:

> “Автор может добавить класс риска, но не снять сработавший”

## Verdict

**APPROVED** — prior blocker is fixed; no blocking findings remain.
