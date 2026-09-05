# Luna full-cycle pilot: no demonstrated quality regression or universal win

Six usable fresh CLI sessions, Luna/high, old/new assembled developer prompts, three paired
synthetic tasks. The protocol and source revisions were frozen before calls. This is not the
production app-server/MCP lifecycle. No live workers or services were changed.

## Observed results

| Task | Old seconds | New seconds | Old API-equivalent | New API-equivalent |
|---|---:|---:|---:|---:|
| Receipt importer | 139.017 | 131.167 | $0.02161740 | $0.02300016 |
| Frozen acceptance + new tests | 71.923 | 76.872 | $0.01711580 | $0.01227916 |
| Research-only load-confounded benchmark | 138.600 | 87.175 | $0.01417272 | $0.01314392 |
| Sum of these attempts | 349.540 | 295.214 | $0.05290592 | $0.04842324 |

Descriptive totals: time -15.54%, flat API-equivalent -8.47%; input tokens 874,510 → 761,625
(-12.91%); output 10,119 → 10,260; completed shell/file-change items 29 → 28.
These are observed attempt totals, NOT a statistically established efficiency gain or cost
per fully accepted delivery. Cache fractions, load and model/server latency differ.
Prices use the repository's Luna card, not subscription percentage or observed cash debit.

## Quality and autonomy

- Frozen task: both implementations pass the independent behavioral checks; both add separate
  regression tests and preserve the frozen test byte-for-byte.
- Research: both reports correctly calculate 5 s vs 10 s, identify CPU-load/order confounding,
  avoid an unsupported causal conclusion, note small sample/input scope and propose interleaved
  controlled measurement. Both notice that separate A/B implementations are absent.
  This is a non-blind human-style reading, not a numeric blind judge score.
- All six preserve protected.txt; both research runs preserve original source/data/config
  fixture files. This checks benign task compliance, not adversarial security.
- Neither old nor new requests an intermediate phase approval or clarification in these tasks.
  The hypothesis that the old prompt necessarily blocks Luna is not supported by this pilot.
- New research produces the requested file but does not commit: Git identity is unavailable
  inside the sandbox. Old research configures local identity inferred from existing history
  and commits. Other code runs also encounter the missing identity and configure it.
  This is an artificial environment limitation and a real incomplete handoff, not grounds to
  declare the new model generally worse. Do not count all three new runs as merged-ready.

## Receipt-task oracle defect — explicitly excluded from the primary quality score

The task says “Preserve the input objects” without specifying whether returned IDs must be
trimmed. The original oracle expects a copied row with a trimmed ID. Old Luna returns the
original row after validating/deduplicating its trimmed key; new Luna copies and normalizes it.
Both are plausible readings. Thus the raw old behavior_pass=false is NOT an established bug.

After seeing this, a diagnostic subset checked both on unambiguous IDs, malformed rows,
deduplication, order, input non-mutation and CLI JSON output. Both passed. This subset is
POST-HOC, not a replacement frozen oracle and not proof that either interpretation wins.
No task was rerun to manufacture a cleaner verdict.

## Setup exclusions and limits

Before the usable batch, mounting the binary without its code-mode sibling broke tool startup.
One old trial returned a blocked report (known cost $0.00781272); the next new trial was stopped
without final usage. Neither is scored. A successful functional shell preflight used 19,896
input, 10,752 cached and 112 output tokens (flat equivalent $0.00217824).
Known setup cost is $0.00999096; it excludes the interrupted attempt's unknown consumption.

One run per task/arm, no A/A noise calibration, variable host load, synthetic short tasks,
no live orchestration/delegation/review tools, no fully provisioned Git identity, one ambiguous
oracle and a non-blind research assessment: none supports general speed or quality claims.
The snapshot suggests comparable task content with modest savings, not a qualitative leap.
The new prompt is reasonable to test further, not “proven superior”.

## Evidence

- luna-protocol.md, luna_eval.py: procedure and evaluator.
- luna-results.json: untouched usable run receipts, final messages and scratch paths.
- luna-excluded.json: known failed setup receipt.
- luna-old-findings.md / luna-new-findings.md: complete research answers.
- Private raw traces and submitted fixtures remain outside Git under
  /mnt/data/luna-autonomy-gxf4t72n; authentication is never exported.
- CLI flags were verified against installed 0.153.4 and
  https://learn.chatgpt.com/docs/non-interactive-mode .
