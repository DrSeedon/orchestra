# #312 verification and review gate

## Canonical review inputs

- Changed artifacts/consumers: `docs/tasks/312/*` is consumed by the task reader and future KB users; `docs/kb/codex-runtime.md` is consumed at the memory gate. No production code/config/service consumer changed.
- Author metadata at frozen cutoff: session `1d0fc38f-23b6-4152-a1d4-a95c479abb86`, `backend_type=codex`, `model=gpt-5.6-sol`, `role=full-cycle`, `pipeline=default`, `effort=xhigh` from the WAL-safe backup.
- AC: answer whether 258,400→828,400 improved real work, raised latency/failures, or accelerated subscription use; provide exact change point, comparable reset/tariff/mix-aware windows, required row table, denominators/counter-evidence/UNKNOWN, sanitized scripts/evidence, KB update; perform no provider/model call or runtime mutation.
- Named check: `python3 docs/tasks/312/verify.py`.

## Review route

Review: none — the #312 assignment explicitly forbids auxiliary Sol/Luna/model calls. `codex-debate` fact extraction therefore ends at mechanical completeness rather than substituting another reviewer.

## Exact mechanical output

```text
PASS #312: backup=b938594cbb931e6505bc547e21ba6a76fb3f083a36f125c03c237841e823b821 rows=425 unique=425 rollout_complete=363 old/new=31/363 core=31/35 quota_delta=3/3 incident_rows=9 secret_scan_files=11
```

The check re-hashes the private backup, verifies `quick_check=ok`, unique rows and required columns, proves cached≤input for every row, proves old/new native ceiling ordering with no interleave, checks identical quota delta/revision, verifies interruption clusters/#240 coverage/image-incident counts, forbids `sessions.model` in the analyzer, and scans every tracked text/data artifact for credential-shaped values.
