# #434 — Codex thread resume latency

## Scope

Phase 1 only: identify the work performed by Codex CLI while restoring a saved
thread and estimate whether preserving the native thread is compatible with a
faster recovery. No production code was changed.

The harness is `measure_resume.py`. It speaks only `initialize`,
`initialized`, and `thread/resume` to `codex app-server --stdio`, measures each
RPC with `time.monotonic()`, and uses `sqlite3.Connection.backup()` for the
state databases. Production `~/.codex` files are read-only inputs; each run
uses a separate `/tmp` CODEX_HOME.

## Established

### Native path

`CodexBackend._connect_unlocked()` starts the native app-server, sends
`initialize`, then sends `thread/resume` for a saved `_thread_id`. The normal
resume includes `excludeTurns=true` (`app/backend_codex.py:1125-1131`), so the
large historical response is not sent back to Orchestra, but the CLI still
processes the persisted rollout before returning the resume response.

The installed binary contains `thread-store/src/local/rollout_migration` and
`thread_history` components (literal strings in the local 0.149.0 binary).
This establishes the existence of migration/projection code, not that it is the
cause of the observed delay.

The 0.150.1 pin guards Orchestra-rendered history imports during cross-runtime
handoff: `_verify_history_version()` rejects an exact-version mismatch when
`history_import` is present. Ordinary native resume does not perform this check;
the 0.149.0 scratch probe resumed a saved thread successfully, including a
state carrying migration row 51. The pin is therefore a compatibility/safety
and provider-fix contract for handoff/state seeding, not a prerequisite for
ordinary native resume.

### Size probes

Scratch resume probes with no production MCP server, same native CLI/model, and
`excludeTurns=true`:

| rollout | resume |
|---:|---:|
| 61,196 B | 2.243 s |
| 1,093,726 B | 4.202 s |
| 10,214,069 B | 3.362 s |
| 81,700,558 B | 9.068 s |
| 136,199,536 B | 17.870 s |

The upper tail grows with rollout size, but the 136.2 MB thread is still below
the reported two-minute wall in an untraced run.

### Migration hypothesis falsifier — rejected

The same 136,199,536-byte thread was resumed twice sequentially in the same
scratch CODEX_HOME:

| run | resume | state after run |
|---:|---:|---|
| A | 19.9795 s | `history_mode=legacy`, 0 `thread_history` rows |
| B | 18.3309 s | `history_mode=legacy`, 0 `thread_history` rows |

The second run did not become faster and no projection appeared. Therefore the
claim that the two-minute pause is a one-time legacy→thread-history migration
is **REFUTED**. The new-thread path does not prove the contrary: it avoids
resume, but the migration premise has no A/A support.

### Production MCP configuration probe

The exact managed worker config (runtime command, auth environment, and 41
Orchestra tools) was used in a fresh scratch CODEX_HOME. The same 136.2 MB
resume took 26.6361 s. The no-MCP A/A range was 18.3309–19.9795 s, so the
production MCP startup contribution in this probe was approximately 6.7–8.3 s,
not two minutes.

### Managed-state inventory

The current managed `state_5.sqlite` contains 876 unarchived threads: 812
`history_mode=legacy` and 64 `history_mode=paginated`. Their 812 legacy rollout
files total 1,938,578,855 B; median 671,147 B, p75 1,463,068 B, p90
4,166,398 B, max 136,199,536 B.

The supplied `/tmp/codexprobe-full` snapshot is older/different: its
`state_5.sqlite` contains 756 threads and does not contain the target row,
although the target rollout file is present. A separate full-test copy added
only the target row (757 total); the supplied snapshot itself was not modified.

### Scratch-to-production boundary

The scratch harness does not reproduce the production symptom: direct resume
results ranged from 7.2 to 19.98 s, while the production observation is a 131.9
s median (p75 186.8 s). The initial full/one-thread alternating sequence was
14.001/9.506/7.248/17.347 s; within-arm spread exceeded the apparent arm
difference. The planned extra series and 100-thread point were cancelled when
this non-reproduction was established. These values are diagnostic probes, not
evidence that global history scan is absent in the live path.

The provided full snapshot contains 756 `threads` rows, not 876. The current
managed state contains 876. This is a time-of-snapshot difference: the full
snapshot was captured earlier and must not be silently relabelled as the
current count.

### Initial syscall observation

A full strace of the 136.2 MB resume showed 167.309 s and 692 `execve` calls,
mostly repeated `lsb_release`, `getconf`, and `tr` probes. The broad trace also
captured 120,026 `futex` events and materially slowed the CLI. A narrowed trace
still showed 106.951 s and the same 692 `execve` / 584 environment-probe
pattern. These traces establish substantial process fan-out during the slow
run, but traced wall time is not an untraced latency estimate.

## Pending measurements

- One live production reconnect after restart, with the new stage logs, is the
  decisive measurement. It must identify the owner of the ~132-second wall
  before any treatment is chosen.
- The instrumentation logs one line per stage: `quota_gate`,
  `prompt_assembly`, `agents_sync`, `skills_sync`, `project_doc_sync`,
  `cli_spawn`, `cli_initialize`, `cli_thread_resume`/`cli_thread_start`,
  `mcp_<name>_<status>`, and `mcp_reload`.

## Rejected interpretations

- “The two-minute resume is the first migration of this target thread” — A/A
  19.9795 s then 18.3309 s, no projection rows, and `history_mode=legacy` both
  times.
- “MCP tool schemas alone explain the two-minute resume” — exact managed MCP
  config added only ~6.7–8.3 s in the 136.2 MB probe.
- “Rollout byte size alone is enough to predict the observed wall” — 136.2 MB
  was 17.870 s untraced, while the two-minute class requires another factor;
  the traced 106–167 s runs are confounded by syscall-trace overhead.
- “A scratch full-vs-one-thread comparison is enough to explain production” —
  its 7.2–19.98 s range does not reproduce the 131.9 s production median, so
  the live-path stage log is required.
