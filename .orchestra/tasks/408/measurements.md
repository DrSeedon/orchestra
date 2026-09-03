# #405 — task-create timeout and rebuildable task projection

## Measurement boundary

- Input: real MCP `_api` client → ASGI HTTP `/api/tm/tasks` → real canonical `TaskStore`
  and runtime head writer → copied legacy SQLite writer.
- State: WAL-safe SQLite backups plus a private copy of the live canonical Git tree; the live
  service and live task data were never mutated by the benchmark.
- Corpus: 684 canonical task states, 540,897,280-byte `current.db`, 3,500-character description.
- Timing: wall-clock `perf_counter`; loadavg is printed for every accepted run.

The accepted comparison was interleaved A/B/A/B. A is the exact pre-fix full projection rebuild;
B is the receipt-sealing/retained-resource path. A compound attempt that buffered three completed
responses and timed out before emitting JSON was excluded in full.

## Before and after

| Path segment | A1 before, ms | B1 after, ms | A2 before, ms | B2 after, ms |
|---|---:|---:|---:|---:|
| MCP client + HTTP transport overhead | 5.603 | 6.109 | 5.852 | 3.294 |
| Canonical task store | 339.465 | 410.890 | 408.603 | 2,766.803 |
| Canonical Git commit | 502.941 | 463.252 | 288.184 | 260.461 |
| `current.db` projection step | 36,893.281 | 1,903.329 | 36,821.251 | 1,555.020 |
| Legacy SQLite write | 10.903 | 6.490 | 5.682 | 5.827 |
| HTTP route total | 39,870.444 | 3,138.099 | 38,022.916 | 4,780.446 |
| MCP end-to-end total | **39,876.047** | **3,144.208** | **38,028.768** | **4,783.740** |
| loadavg before → after | 2.013→2.447 | 9.360→9.360 | 13.802→8.320 | 4.726→4.587 |

The original projection rebuild consumed 36,893 / 39,876 ms = **92.5%** of the first complete
baseline. The fixed request is 8.0–12.7× faster and stays 6.3× below the unchanged 30-second
transport deadline even in the slower accepted B run. Startup sealing of the old same-head file
took 2,912 ms and 2,006 ms respectively; it validates existing payload hashes, canonical resource
descriptors, source content digests, and FTS identities, then writes only two receipts. It does not
rewrite the 516-MB projection.

The remaining 3.1–4.8 seconds is acceptable for this repair: it is far below the transport budget
and includes canonical generation of all task states plus verification of retained resources. The
second B run's 2,767-ms task-store outlier coincided with elevated 15-minute loadavg (14.5). Further
latency work would need a separate measurement/ticket; this task does not weaken projection
verification to chase it.

## Live incident timestamps

The production PID was still running code loaded before the retained-resource commits:

- call: `2026-08-26T08:58:07.437668Z`;
- canonical Git commit: `08:58:10Z`;
- MCP `ReadTimeout`: `08:58:37.497592Z`;
- legacy row finally written: `08:58:41.126870Z`.

Thus canonical work completed about three seconds after the call, but synchronous current-projection
work held the response beyond the deadline. A retry completed in 29.5 seconds only by landing just
inside the same deadline; increasing that deadline would only mask the rebuild.

## Deleted `task-current.db` probe

Command:

```text
PYTHONPATH=$PWD /mnt/data/Projects/Python/orchestra/.venv/bin/python3 \
  docs/tasks/408/measure_task_write.py --projection-delete-probe
```

The probe copied the live canonical task tree, deliberately provided no task projection, and ran an
idempotent production `_RuntimeTaskStore.link_commits_to_task` post-commit link:

| Fact | Result |
|---|---:|
| Canonical JSON files | 1,545 |
| Canonical task states | 684 |
| Projection existed before | false |
| Rebuild + idempotent link | 848.743 ms |
| Post-commit result | `ok=true`, `added=0` |
| Projection rows after | 684 |
| Projection exists after | true |
| Canonical/projection heads | equal (`sha256:52462f…`) |

No `POST_COMMIT_PARTIAL`-producing exception occurred: the missing cache was reconstructed from
canonical state before the idempotent link resolved.

## Frozen regressions and mutations

Initial frozen regressions at commit `5106573c`:

```text
2 failed in 2.88s
```

After implementation:

```text
2 passed in 3.15s
12 passed in 2.59s
```

Mutation 1 bypassed same-head receipt sealing. Marker counts were `1 → 1 → 1`; the mutant failed
the no-full-rebuild regression (`1 failed`), restoration passed (`1 passed`), exit codes `1 → 0`.

Mutation 2 removed only the post-commit projection-recovery call. Total recovery-call markers were
`6 → 5 → 6`, the unique link seam stayed `1 → 1`; the mutant failed because the deleted file stayed
absent (`1 failed`), restoration passed (`1 passed`), exit codes `1 → 0`.

Luna review then found two adjacent existing-file corruption paths. One added regression covers
both caches plus atomic interruption: a corrupt task projection rebuilds from canonical; a corrupt
current projection rebuilds through a temporary SQLite file; an injected failure before `os.replace`
leaves the prior file byte-identical, `quick_check=ok`, and no temporary file behind.

- Corrupt `task-current.db` mutation removed the `sqlite3.DatabaseError` recovery arm: `1 failed`;
  restoration: `1 passed` (`RC 1 → 0`, recovery marker present `1 → 1`).
- Corrupt `current.db` mutation changed the anchored rebuild catch to `OSError`: `1 failed`;
  restoration: `1 passed` (`RC 1 → 0`, mutant marker count 1, rebuild anchor restored).

Final focused compatibility run:

```text
46 passed in 2.33s
```

The older immutable T4 file has one pre-existing fixture error (`alternate-mode` is not created
before `write_text`); the same single test fails identically on an extracted clean `main` archive,
after all projection assertions have already passed. That acceptance file was not modified.

## Review disposition

- Risk route: persistence/rebuild path implies Sol; an additional Sol call was not authorized.
  One automatically allowed Luna session ran three code rounds (the executable-artifact ceiling).
- Round 1: two blocking cache-corruption paths; both fixed and regression/mutation checked.
- Round 2: prior blockers fixed; stale/empty task projection and current SQLite sidecars flagged.
  Empty/stale cardinality validation, WAL checkpoint, DELETE journal mode, `quick_check`, and atomic
  replacement were added. The unrelated #406 KB deletion suggestion was a stale-branch comparison
  artifact and was dropped by the reviewer after the diff was regenerated from merge-base.
- Round 3: prior blockers fixed; one new blocking remained because task projection recovery cleaned
  only the main file. After the round ceiling, recovery was changed to delete
  `-journal/-wal/-shm` before rebuilding. The committed sidecar regression was RED before the fix,
  GREEN after it, and a seam mutation produced `RC 1 → 0` on restore (marker `1 → 1 → 1`).

Final post-review-fix focused run: `46 passed in 3.56s`. No fourth review was run because the
`codex-debate` executable-artifact ceiling is three rounds. Full reviewer output is preserved in
`docs/tasks/408/codex-review-impl.md`; its final blocking is resolved by commit `3f244af2` plus the
sidecar mutation above, but there is no post-fix reviewer verdict after the ceiling.
