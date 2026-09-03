# #106 Q6 — validator + 23 new fixtures

**$0 model spend.** No generation run. Production untouched.

## (a) Self-consistency validator — `validate_fixtures.py`

Enforced at build time: `build_fixtures.py` raises `SystemExit` and writes no
`fixtures.json` if any fixture is self-contradictory.

Five rule families, wider than the one defect we had already seen:

| Rule | Catches |
|---|---|
| `contradiction_errors` | a pending action prohibited by the fixture's own forbidden claims |
| `seeded_file_errors` | a pending read of a file the fixture never seeds; `expected_files` naming an unknown path |
| `anchor_errors` | anchor/recent/pending counts drifting from the declared budget |
| `gap_errors` | an `expected_gap_ids` entry that is actually paired with a `TOOL_RESULT`, or absent entirely |
| `secret_errors` | a declared fake secret that appears in neither transcript nor seeded files |

**Proof it catches the real defect.** Run against the actual discarded Q5
fixture from `q5/fixtures.json`:

```
CAUGHT: pending action 'Read docs/runbook-state.md' is prohibited by forbidden
        claim 'file was read' (shared action: ['read'])
```

Its dev twin `q5-dev-unchanged-no-read` is caught by the same rule. Both would
have failed at build time in Q5, before any judging spend.

**Proof it blocks the build.** Re-inserting that fixture into
`build_fixtures.py` makes the build exit non-zero:

```
exit code: 1
self-contradictory fixtures:
  q6-poison-contradiction: pending action 'Read docs/poison.md' is prohibited by
  forbidden claim 'file was read' (shared action: ['read'])
```

**Proof it is not over-eager.** Zero false positives across all 23 shipped
fixtures. Each of the other four rules was probed individually against a
synthetic defect and stayed silent on the legitimate control case.

Regression tests added (`test_q6.py`): the contradiction case, the unseeded-read
/ anchor-drift / paired-gap cases, and a guard that the shipped corpus stays
self-consistent. **11 passed.**

## (b) 23 newly authored fixtures

2 dev + 21 holdout, covering all 21 scenario classes. Written as new
**situations**, not renamed old ones — different domains, different tools,
different files.

| Class | Q5 situation | Q6 situation |
|---|---|---|
| decision-reversal | canary rollout rule | audit-log retention window |
| unmatched-tool-event | archive fetch | point-in-time restore replay |
| targeted-idempotent-write | `docs/continuity-state.md` billing owner | `docs/oncall-handover.md` pager owner |
| command-sequence | lease test | slow tenant search / index advisor |
| partial-success | linux-arm64 vs amd64 build | de-DE vs pt-BR localisation |
| file-decoys | `Config/limits.yaml` | `Schema/Orders.sql` charset conflict |
| mixed-git-state | working-tree capture | merge conflict + two stashes |
| parallel-blockers | index cutover | payment-gateway PCI + acquirer freeze |
| temporal-blocker | certificate rotation (Tuesday) | export quota (Thursday) |
| durable-user-preference | UTC timestamps in incident reports | rollback script in migration reviews |
| one-off-format | semicolon export | Friday digest grouping |
| secret-in-recent-tail | sandbox webhook | partner webhook signature |
| secret-in-tool-history | object store | container registry |
| secret-and-file-prohibition | mirror credential | offsite backup key |
| temporal-state | Monday/Tuesday imports | March/April inventory |
| conflicting-evidence | eager cache eviction | link prefetch: synthetic vs field |
| long-tool-output | heartbeat verification log | dependency scan |
| numeric-qualifiers | queue limits | ingest caps (MB/min vs GB/hour) |
| exact-paths | `Config/API.toml` | `Docs/Runbook.md` |
| ordered-next-actions | migration order | cutover: freeze/drain/DNS/re-enable |
| negative-deployment-state | release candidate | `rc-88` reproducible-but-unsigned |

### Verified

- **23 fixtures**, 2 dev / 21 holdout, 21 classes — all present.
- **Validator: 23/23 PASS**, zero failures.
- **Every holdout carries exactly 8 exact anchors**, 3 recent messages, 1 pending action.
- **Every anchor string actually appears in its own transcript** (0 missing) — an
  anchor that cannot be found is an unscoreable fixture.
- **Independence vs all 51 prior fixtures** (#106 original, Q4, Q5):
  **0 ID overlap, 0 byte-exact transcript overlap**
  (`results/corpus-independence.json`).
- **No reused file paths** except `CLAUDE.md` / `TODO.md` / `BUGS.md`, which are
  constant by design — they are the note names the prohibition tests — and the
  `git` tool. 15 new tool commands, none shared with Q5.
- **`test_q6.py`: 11 passed.**

### Stated limitation, per the standing agreement

Exact ID/transcript non-overlap proves **exact** non-overlap only. It does not
prove semantic independence, and it cannot prove that prior fixture content did
not influence my authoring — I wrote these having read the Q5 corpus. Recorded
in `results/corpus-independence.json` as `scope_limit`.

## Standing limitations

- **G7 remains UNDECIDED** — Codex judge unavailable until 2026-08-08.
- **G5 remains absolute.** Not softened.

## Not done — needs your go

The full Q6 has **no preregistration lock yet**. Before spending against the $30
ceiling it needs: a full `protocol.md` (currently pre-gate scope only), a fresh
`preregistration-lock.json` committed before the first model call, and a pilot
on the 2 dev fixtures. Job count is now **126** primary outputs (21 holdout x 2
variants x 3 reps), not 132 — cost scales to roughly **$14.8** generation plus
judging.
