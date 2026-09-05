# Knowledge delivery — bounded evaluation

## Design and scope

Base 74692c2c; ten question/answer criteria frozen in 57352851 before instruction edits.
The first instruction-owner migration (2847a2c5) preserved the entire old guide in AGENTS.md;
the later bounded candidate was evaluated at 03db3de8. Model: GPT-6 Astra, medium,
same CLI invocation for both arms, tools disabled, documents supplied explicitly as data.
No provider configuration, credentials, live services or project data were changed.

Old packet: original CLAUDE.md, original KB index and six relevant full topics.
New packet: bounded AGENTS.md, short index and current-operations pointers/facts.
This evaluates answer retention for these supplied packets, NOT autonomous retrieval,
full coding tasks, all facts in the library, or all Claude/Codex configurations.

Sequence: old/old A/A control, new/old, old/new. All six calls completed.
The evaluator's expected answers were not included in model input. Answers were manually
checked against the frozen criteria; this is an internal check, not independent judging.

## Paired results (ten original questions)

| Quantity | Old | New |
|---|---:|---:|
| Supplied JSON document packet | 363951 bytes | 20194 bytes |
| Reported input, including Codex harness | 89735 tokens | 18475 tokens |
| Required answers satisfied, each run | 10/10 | 10/10 |
| Critical permission errors | 0 | 0 |
| Invented quota/font answers | 0 | 0 |

Input reduction in this packet replay: 79.4%; correctness improvement was NOT observed,
because the old arm already answered all ten correctly. The original two A/A wall times
were 38.24 and 37.13 seconds. Paired median wall times were 37.39 and 31.25 seconds, but
output length and cache hits differed; do not claim a general latency improvement.

Loss of detail is real: the new index answer refuses to infer current.db's exact type
without opening its owner, while the old packet quotes the historical FTS correction.
Both satisfy the question about whether a directory name proves its type. A question
asking for today's actual schema requires an additional read in the new approach.

## Final revision follow-up

Manual source review restored two explicit obligations to the bounded guide:
recover workers named in cut_names after a restart, and do not kill full-cycle workers
just because a merge finished. Index descriptions were repaired after mechanical shortening.
Two extra regression questions were added separately, after the first results; they
are NOT represented as part of the frozen original ten-question comparison.

Final packet: 20874 bytes, sha256
afdae1b3b47b7346dd1b1fc291115fe29782fa212f7ade6bf75a7d5b33dbc391.
Two final-only runs: 12/12 required answers each; input 18647 tokens each.
These runs are in answer-replay-final.jsonl; first paired data are in answer-replay.jsonl.

## Native loading and executable checks

Both actual CLIs recovered the same unique canary from a scratch AGENTS.md:
Codex read it directly; Claude read the project containing only the @AGENTS.md adapter.
The value was not included in the question. All model tools were disabled.
Codex: native-probe.jsonl; Claude: native-probe-claude.jsonl.
The first Claude probe failed before a model call because variadic --mcp-config consumed
the prompt. Adding the argument separator fixed the probe, not the production client.

Workspace tests preserve foreign tracked rules and prevent an adapter from overwriting
its own import target. A missing canonical target is an explicit failure. Migration's
fake-SSH test checks that AGENTS.md arrives before the Claude adapter; no SSH was executed.
The compatibility fallback test executes the generated rg command against a temporary KB.
The repository KB validator accepts historical sections without weakening evidence checks.

Final selected regression run: 548 passed, four ownership checks skipped, one known
environment-dependent CLI-directory check deselected after reproducing its failure on main.
The archive-preservation assertion uses the frozen SHA-256 rather than requiring the
historical Git object at test runtime, so shallow CI checkouts can execute it.
README checker: 29 rows / 34 anchors passed. Secret-shape scan of rules, archived source
and model-output artifacts returned success without findings.

The bounded root owner plus Claude adapter is 10809 bytes (previous owner: 224719).
KB index: 4875 bytes (previous: 11750). These are byte counts, not token estimates.

## Limits / remaining external validation

- The initial work excluded merge/restart/VPS deployment. The user subsequently authorized
  main merge only; restart and VPS deployment remain unauthorized.
- No proof of quality for unseen questions or every rare historical instruction.
- Autonomous retrieval usage/cost was not measured; only controlled supplied packets.
- Four existing ownership tests require passwordless sudo and were skipped.
- The existing live CLI-directory encoding test fails identically on unchanged main
  for two Cyrillic paths. No encoding logic was changed; this separate issue was not fixed.
- One accidental default-phase replay launch was stopped before its first result;
  no answer or token-usage receipt was produced and it is excluded from all numbers.

## Merge validation

Integrated main through 2101da4d, including #506 review-size gating. Its new pytest
import rule was retained in AGENTS.md with the full explanation in test-oracles.md;
CLAUDE.md remains an adapter, not a restored copy of the old guide.
Merged-tree check: 556 passed, 4 ownership checks skipped, 1 pre-existing live-directory
check deselected. Imports resolved under /mnt/data/Projects/Python/orchestra-knowledge-delivery/app/.
README symbol anchors were refreshed for the new mcp_stdio.py lines.
