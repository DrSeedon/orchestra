<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

Apparently, “$0 at fetch time” has been promoted to a payment firewall. 😏

## Summary

Mechanical checks pass:

- `SECRET_SCAN PASS`
- Matrix: 30 runs, 88 attempts, 88 allowed guard rows, `fatal=null`
- Account: `total_credits=97`, `is_free_tier=false`
- Required 14-column table and five model rows present
- Mandatory sections present
- `git diff --check` clean
- No Phase 2 implementation exists in the inspected seams

Evidence that the document was read: “Changing it after seeing output would be p-hacking; the raw artifact is preserved and the 0.75 score stands.”

Secondary review route: none — `codex_review` is unavailable in this session.

## Findings

- `blocking:` [docs/tasks/236/research.md:241](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:241) — The free-only guard cannot make paid requests impossible for unsuffixed routes such as `stealth/ox-alpha`. All-zero metadata is a preflight snapshot that may change before the POST; the `usage.cost` tripwire detects payment only afterward. Either exclude unsuffixed routes or add a provider-side spending restriction that rejects paid requests atomically.

- `blocking:` [docs/tasks/236/research.md:250](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:250) — The proposed transaction remains local to one SQLite database, while the account is shared by the laptop, Contabo, and possible external clients. Independent contours can each reserve under 20/min and 1,000/day simultaneously, so the policy does not deliver the stated account-global accounting. Specify a single admission broker or deterministic per-contour allocation.

- `blocking:` [docs/tasks/236/research.md:263](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:263) — The preferred-pool conclusion considers only four available models even though the catalog identifies nineteen tool-capable free routes. No frozen screening rule explains why the remaining fifteen were excluded, so the matrix cannot establish that Ultra maximizes useful free capacity. Add a complete screening table or run every candidate passing a preregistered filter.

- `blocking:` [docs/tasks/236/research.md:158](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:158) — The in-scope evidence cannot verify that protocol commit `9e814761` preceded inference. E5 points outside `evidence/`, and the evidence package contains neither the frozen tasks/graders/runner nor their hashes and ordering timestamps. Acceptance currently depends on narration rather than a self-contained artifact.

- `blocking:` [docs/tasks/236/research.md:72](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:72) — E1 is an already-filtered, normalized 20-row subset. It cannot independently prove that the source response contained 422 rows, that exactly twenty routes met the free predicate, or that normalization preserved every pricing dimension. Preserve a sanitized full response or a verifiable count plus deterministic selection transcript.

- `blocking:` [docs/tasks/236/research.md:41](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:41) — The preserved limits excerpt proves 20 RPM, 1,000 RPD, and the 10-credit threshold, but contains no UTC reset statement. Therefore “per UTC day” and the UTC reset policy are not supported by the cited primary evidence.

- `blocking:` [docs/tasks/236/research.md:128](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:128) — The allowed seams confirm `HarnessBackend → AgentLoop → OpenRouterClient → POST`, but not the preceding `Session._make_backend`/registry wiring or the repository-wide assertion that no second OpenRouter POST owner exists. C2 cites files outside the review package, so the conclusion that `llm.py` is the sufficient last-line guard remains unsupported.

- `blocking:` [docs/tasks/236/research.md:275](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-openrouter-free/docs/tasks/236/research.md:275) — The end-of-day rule is qualitative rather than deterministic. It defines neither trigger time, remaining-budget threshold, reservation for active work, backlog ordering, concurrency, nor stop condition. Consequently two orchestrators can make different choices and the policy cannot reliably maximize useful daily allowance.

## Verdict

**NEEDS WORK — 8 blocking findings.** The measurements and mechanical matrix arithmetic are internally consistent, but the paid-safety guarantee, account-global coordination, candidate selection, evidence provenance, UTC boundary, production call-path proof, and end-of-day policy are not yet sufficient for Phase 1 approval.

A screenshot of zero pricing is still not a padlock on the wallet. 🙃

## Follow-up attempt log

- Sol resume `bg-69900d3fdd` was launched before the user's model-policy correction.
- It timed out after 10 minutes with tool execution only and no reviewer agent message,
  no `## Round 2`, and no verdict. Under the codex-debate non-response rule this is an
  attempt, not a completed review round.
- The user subsequently forbade any additional Sol review/eval/provider call without a
  separate approval. No Sol retry will be made. Closure evidence for all eight findings
  is preserved in the changed research/evidence package; the permitted final closure
  audit is Luna-only and uses a separate artifact.
