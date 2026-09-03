# #395 — live mismatch observed while merging T1

Date: 2026-08-27. Read-only queries only; no live row/file was changed.

- `tm_tasks` contains one row with `par_number=409`, `id=608`,
  `project_id=/home/kesha/orchestra`, `status=done`, created
  `2026-08-27T12:07:17.526251+00:00`.
- The Git-canonical task tree contains zero `state.json` records with display number 409.
- Runtime debt contains one blocking record:
  `candidate_write_failed`, `ValueError`, message `409 not found`, file
  `debt/ce43c5d82d4c5738703e9c755443685d572d82938fdd21cd83840c40497e6007.json`.

Measurement shape:

```text
SQLite (mode=ro): SELECT ... FROM tm_tasks WHERE par_number=409 → 1 row
canonical/tasks/**/state.json parsed as JSON, display_number=409 → 0 rows
debt/*.json parsed, reason=candidate_write_failed and message contains 409 → 1 row
```

This is a concrete T2 recovery case: the compatibility SQLite projection accepted/closed an
identity that the canonical owner never committed, and durable debt is the only join witness.
T2 must reconcile from owner receipts and stored identity rather than allocate a replacement task.
