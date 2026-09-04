# #511 — decisions and evidence for the public status table

Artifact: `README.md`, section `## What Orchestra does, doesn't, and refuses to do`
(replaces `## Orchestra vs. the field`). `FEATURES.md` was cancelled mid-task by the user —
"может лучше в реадми чтобы сразу видели" — because GitHub renders only README on the repo
front page. One owner file, no link-outs.

## Two facts that changed rows, found while checking anchors

**1. Cross-model review is NOT a code-enforced merge gate.** The brief (and the #505 promo frame)
said "review as a mandatory merge gate". The code says otherwise:

```
$ grep -c review app/merge_operations.py
0
```

Review is required by role prompts in five files (`base.md`, `roles/worker.md`,
`roles/full-cycle.md`, `modules/orchestration.md`, `skills/codex-debate.md`). Receipts exist as a
table (`review_receipts`, `app/db.py:145`) and are written by `record_review_outcome`
(`app/mcp_stdio.py:3536`), but nothing reads them on the merge path. What the platform *does*
enforce at merge: frozen acceptance oracle (`app/acceptance.py:349` via
`app/merge_operations.py:1666`), mapped test subset (`:1728`), insertion budget
(`app/diff_budget.py:16`), task/session/branch provenance.
→ Row status 🚧, with the grep printed in the row. Also softened the `### 🔀 Cross-Model Review`
feature blurb, which claimed the step outright.

**2. `CLAUDE.md` is 189 851 bytes, not 171 419.** The brief quoted the older number.
`wc -c CLAUDE.md` on this branch, 2026-09-03. The table states the measured value, and
`check_table.py` fails if the file and the README disagree.

## What is verified and how

- **Our anchors.** Every `app/…:line` in the section resolves to a non-blank line; checked by
  `.orchestra/tasks/511/check_table.py` (28 rows, RC=0). The script also fails on a missing status
  mark, an empty anchor cell, the banned string "5 593", and on the two live claims above.
- **Vendor docs, re-fetched raw 2026-09-03**, not from memory and not through a summarizer:
  `curl -sL https://code.claude.com/docs/en/sub-agents.md` (111 863 B),
  `…/agent-teams.md` (40 760 B),
  `curl -sL https://learn.chatgpt.com/docs/agent-configuration/subagents.md` (22 084 B).
  Competitor READMEs via `gh api repos/<o>/<r>/readme -q .content | base64 -d`.
  All 14 quoted fragments matched after whitespace/`>` normalization; two failed on first pass and
  were rewritten rather than kept: `**` inside Orca's bolded phrase, and a lower-cased "works".
- **Star counts, 2026-09-03:** Orca 60 526, cmux 26 737, oh-my-pi 29 216, Orchestra 5.
- **Our own numbers** are the #503 measurements on the primary database, 2026-09-02: worker
  sessions n=431 (median 0.8 h, p90 130.6 h, max 531.8 h, 81 over a day); sub-agents median 12.5 s,
  p90 75.1 s, 0.0 % over ten minutes; tool-call latency 3 667.6 µs external vs 20.2 µs in-process
  (`fork+exec` alone 2 170.0 µs), 40 interleaved reps.

## Rows deliberately absent

Per the ban on unconfirmed claims about other products: isolation and inter-agent messaging for
cmux, review for Orca, nesting for Codex sub-agents. Their primary sources do not answer these, and
absence of a sentence in a README is not evidence of absence of a mechanism (#503). The footnote
under the table says which questions were dropped and why, so the gap is visible rather than
silently filled.

LangGraph / CrewAI / AutoGen were removed with the old table: they are a different category (SDKs
for building agent graphs), and no cell about them could be sourced without a fresh pass over three
more doc sets.

## Review (codex-debate route 5: docs → mechanical checks, then one Luna pass)

Round 1 (Luna, `gpt5.6luna`): **7 blocking, all verified in code, all accepted.** Three anchors did
not support the sentence beside them (`transcription.py:72` for "dashboard and Telegram control";
one-sided `no-store`; oracle described as unconditional). One row was factually wrong the other way:
`spawn_worker` has **no role gate** — `_ORCH_ROLES` guards only `_acceptance_command_from_caller`,
and `app/manager.py:660` gates by quota level — so "workers cannot spawn workers" is a prompt rule,
not a code rule, and the row moved from 🚫 to 🚧. One row contradicted a surviving README line
(the OpenRouter Harness counted as a "CLI agent" while the Stack section calls it in-process).
One 🚫 clashed with its own legend (the vector implementation still ships), which is why the legend
now reads "never built, **or built and then retired**". One sentence had crept back into marketing
in reverse — an uncited claim that sub-agents are "cheaper and better".

Round 2 (resume, same output): six FIXED, finding 4 STILL BROKEN (dashboard had no anchor of its
own → `app/routes/system.py:77` added), two NEW BUGS, both correct and both fixed:
`app/merge_operations.py:1728` is the *import* of `evaluate_test_gate` while the blocking logic is
at `:1737`, and "a guaranteed merge conflict" overstates what two disjoint branches do.
Verdict counted: the reviewer quoted a line it read while checking anchors ("Every worker gets its
own git worktree — a full copy of the repo on its own branch."), present once in README.md.

Round ceiling for prose is 2 and it is reached. The last two fixes were verified directly in the
code instead of buying a third round; nothing is left open.

Artifact: `.orchestra/tasks/511/codex-review-readme.md`.
