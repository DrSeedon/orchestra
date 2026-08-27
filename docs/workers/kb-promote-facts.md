# kb-promote-facts

- Flat `canonical/evidence/<project>/*.json` records are `resource` inventory, not fact
  provenance. A promotable reference must be owned `task.evidence`; use the proof-bound
  `import_evidence` path added in #409, never write canonical files directly.
- `knowledge` mutations are orchestrator-only. A worker can build and dry-run a batch, but a
  live `promote` call returns 403 before payload validation; hand the exact apply command to the
  orchestrator.
- Any new `_RuntimeTaskStore` mutation wrapper must call `_ensure_task_projection` before its
  owner operation: an idempotent owner noop will not otherwise rebuild a deleted projection.
