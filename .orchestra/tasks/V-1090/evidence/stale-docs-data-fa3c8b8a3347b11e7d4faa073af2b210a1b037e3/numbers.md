# numbers

All values come from runs.jsonl (320 planned runs). Percentages: one decimal, (numerator/denominator).

## Choice shares
- `S-file`: 90.1% (649/720), 95% CI [85.7, 94.0]
- `S-file-claude`: 86.4% (311/360), 95% CI [79.7, 92.3]
- `S-file-codex`: 93.9% (338/360), 95% CI [90.7, 96.7]
- `S-code`: 4.2% (30/720), 95% CI [1.7, 7.3]
- `S-code-claude`: 7.5% (27/360), 95% CI [3.1, 13.2]
- `S-code-codex`: 0.8% (3/360), 95% CI [0.0, 2.2]
- `S-neither`: 5.7% (41/720), 95% CI [3.3, 8.6]
- `S-neither-claude`: 6.1% (22/360), 95% CI [3.0, 9.8]
- `S-neither-codex`: 5.3% (19/360), 95% CI [2.7, 8.0]
- `P-file`: 3.2% (23/720), 95% CI [1.8, 4.8]
- `P-file-claude`: 1.4% (5/360), 95% CI [0.3, 2.6]
- `P-file-codex`: 5.0% (18/360), 95% CI [2.2, 8.1]
- `P-code`: 91.4% (658/720), 95% CI [88.7, 94.1]
- `P-code-claude`: 94.4% (340/360), 95% CI [91.9, 96.9]
- `P-code-codex`: 88.3% (318/360), 95% CI [84.8, 91.8]
- `P-neither`: 5.4% (39/720), 95% CI [3.5, 7.5]
- `P-neither-claude`: 4.2% (15/360), 95% CI [2.2, 6.5]
- `P-neither-codex`: 6.7% (24/360), 95% CI [4.0, 9.6]

## Conflict reported in the final reply (conflict judge)
- `S-report`: 50.6% (81/160)
- `S-report-claude`: 98.8% (79/80)
- `S-report-codex`: 2.5% (2/80)
- `P-report`: 100.0% (160/160)
- `P-report-claude`: 100.0% (80/80)
- `P-report-codex`: 100.0% (80/80)
- valid runs without a judge label: 0
- `S-file-reported`: 86.6% (316/365)
- `S-file-reported-claude`: 86.2% (307/356)
- `S-file-reported-codex`: 100.0% (9/9)
- `S-file-notreported`: 93.8% (333/355)
- `S-file-notreported-claude`: 100.0% (4/4)
- `S-file-notreported-codex`: 93.7% (329/351)

## Categories, condition A (follow_file share per category and agent)

| category | Claude Code file | Claude Code code | Codex CLI file | Codex CLI code |
|---|---|---|---|---|
| LOG | 83.3% (20/24) | 0.0% (0/24) | 91.7% (22/24) | 0.0% (0/24) |
| PATH | 100.0% (24/24) | 0.0% (0/24) | 91.7% (22/24) | 0.0% (0/24) |
| EXC | 81.8% (18/22) | 9.1% (2/22) | 95.5% (21/22) | 0.0% (0/22) |
| ERR | 90.9% (20/22) | 0.0% (0/22) | 81.8% (18/22) | 0.0% (0/22) |
| TFILE | 90.9% (20/22) | 9.1% (2/22) | 100.0% (22/22) | 0.0% (0/22) |
| TSTYLE | 100.0% (22/22) | 0.0% (0/22) | 100.0% (22/22) | 0.0% (0/22) |
| REC | 100.0% (22/22) | 0.0% (0/22) | 100.0% (22/22) | 0.0% (0/22) |
| NAME | 90.9% (20/22) | 0.0% (0/22) | 86.4% (19/22) | 0.0% (0/22) |
| OPT | 100.0% (24/24) | 0.0% (0/24) | 100.0% (24/24) | 0.0% (0/24) |
| IMPORT | 100.0% (22/22) | 0.0% (0/22) | 100.0% (22/22) | 0.0% (0/22) |
| GENERIC | 95.5% (21/22) | 0.0% (0/22) | 95.5% (21/22) | 0.0% (0/22) |
| FMT | 100.0% (24/24) | 0.0% (0/24) | 100.0% (24/24) | 0.0% (0/24) |
| DOCSTR | 100.0% (22/22) | 0.0% (0/22) | 100.0% (22/22) | 0.0% (0/22) |
| MONEY | 31.8% (7/22) | 18.2% (4/22) | 81.8% (18/22) | 0.0% (0/22) |
| CONFIG | 13.6% (3/22) | 86.4% (19/22) | 77.3% (17/22) | 13.6% (3/22) |
| ENUM | 100.0% (22/22) | 0.0% (0/22) | 100.0% (22/22) | 0.0% (0/22) |

- `kinds-file-majority`: 14 (of 16): LOG, PATH, EXC, ERR, TFILE, TSTYLE, REC, NAME, OPT, IMPORT, GENERIC, FMT, DOCSTR, ENUM

## Tests (existing tests and held-out feature test all pass)
- `S-tests`: 89.4% (143/160)
- `S-tests-claude`: 100.0% (80/80)
- `S-tests-codex`: 78.8% (63/80)
- `P-tests`: 100.0% (160/160)
- `P-tests-claude`: 100.0% (80/80)
- `P-tests-codex`: 100.0% (80/80)

## Choice shares per condition and agent (Figure 5a; 95% CI, 2,000 bootstrap resamples by repository)

| condition | agent | follow file | follow code | neither | choices |
|---|---|---|---|---|---|
| A | Claude Code | 86.4% (311/360) [79.7, 92.3] | 7.5% (27/360) [3.1, 13.2] | 6.1% (22/360) [3.0, 9.8] | 360 |
| A | Codex CLI | 93.9% (338/360) [90.7, 96.7] | 0.8% (3/360) [0.0, 2.2] | 5.3% (19/360) [2.7, 8.0] | 360 |
| B | Claude Code | 1.4% (5/360) [0.3, 2.6] | 94.4% (340/360) [91.9, 96.9] | 4.2% (15/360) [2.2, 6.5] | 360 |
| B | Codex CLI | 5.0% (18/360) [2.2, 8.1] | 88.3% (318/360) [84.8, 91.8] | 6.7% (24/360) [4.0, 9.6] | 360 |

## Efficiency table

| condition | agent | tests all pass | median tool calls | median seconds | valid runs |
|---|---|---|---|---|---|
| A | Claude Code | 100.0% (80/80) | 10 | 54.2 | 80 |
| A | Codex CLI | 78.8% (63/80) | 9 | 108.4 | 80 |
| B | Claude Code | 100.0% (80/80) | 9 | 51.0 | 80 |
| B | Codex CLI | 100.0% (80/80) | 8 | 94.9 | 80 |

## decisions-per-cell (choices judged; valid runs x decisions of the task)
- `decisions-per-cell` Claude Code A: 360 (valid runs: 80; planned decisions: 360)
- `decisions-per-cell` Claude Code B: 360 (valid runs: 80; planned decisions: 360)
- `decisions-per-cell` Codex CLI A: 360 (valid runs: 80; planned decisions: 360)
- `decisions-per-cell` Codex CLI B: 360 (valid runs: 80; planned decisions: 360)

## Runs
- Claude Code A: planned 80, valid 80, invalid 0
- Claude Code B: planned 80, valid 80, invalid 0
- Codex CLI A: planned 80, valid 80, invalid 0
- Codex CLI B: planned 80, valid 80, invalid 0
- runs with at least one failed attempt: 1 (R293: sandbox)
- valid runs that edited the instruction file: 7 (R003, R004, R092, R120, R129, R148, R308)

## n and versions
- `n`: 39 tokens (tiktoken o200k_base; sentence: "When a repository's documentation and its existing code disagree, follow the conventions used in the existing code, and in your final reply point out each inconsistency you found between the documentation and the code.")
- Claude Code version (as recorded in each valid run): 2.1.302 x160
- Claude Code model (as recorded in each valid run): claude-sonnet-5-5 x160
- Codex CLI version (as recorded in each valid run): 0.163.0 x160
- Codex CLI model (as recorded in each valid run): gpt-6-sol x160
