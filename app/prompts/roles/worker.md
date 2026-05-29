---
name: worker
label: Worker
model: sonnet/opus
when: Clear task for a known module, implementation from detailed spec, bug fix with known repro
not_for: Tasks needing research or unknown scope — use full-cycle
description: >
  General-purpose worker. Implements tasks directly, no pipeline gates.
  For system workers (permanent, module-scoped) and disposable one-shots.
prompt: worker.md
---
