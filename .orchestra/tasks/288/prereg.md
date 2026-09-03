# #288 — preregistration of the OpenSpec reconstruction

Recorded before reconstructing a completed Orchestra ticket.

## Corpus

- OpenSpec baseline: `Fission-AI/OpenSpec` v1.9.0, default `spec-driven` schema as fetched on 2026-08-16.
- Orchestra baseline: `main` at `2e3d6276b6bc3118d1943225bca6a9aab4697f03`.
- Completed ticket: #214 (`status=done`, completed 2026-08-12), using the tracker record returned by `task_get(214)` and `docs/tasks/214/report.md` from that `main` commit.
- Reconstruction scope: the smallest truthful default OpenSpec change bundle for the final shipped behavior of #214: `.openspec.yaml`, `proposal.md`, one delta spec, `design.md`, `tasks.md`; after archive, the unchanged bundle is moved under `changes/archive/` and one canonical capability spec exists under `specs/`.
- Excluded from the per-ticket bundle: repository-wide `openspec/config.yaml` and generated agent skills/commands. Their bytes are reported separately.

## Metrics fixed before reconstruction

1. **UTF-8 bytes:** `wc -c` per reconstructed file and summed for (a) the archived change bundle and (b) bundle plus canonical spec.
2. **Approximate context tokens:** `ceil(bytes / 4)`. This is a deterministic planning estimate, not a provider billing count.
3. **Atomic fact inventory:** independently testable or normative propositions needed to describe #214's final intended behavior. A fact counts as present in a file only when the proposition is explicit; inference and headings do not count.
4. **Duplication:** for each fact, count the number of current Orchestra surfaces and reconstructed OpenSpec surfaces that state it. Report total fact occurrences and redundant occurrences (`occurrences - unique facts`). Tracker metadata and implementation evidence remain distinct surfaces even when they agree.
5. **Unique value:** facts represented by the OpenSpec bundle that are absent from both the tracker record and the existing durable task report.

## Decision criteria

- **Full adoption is not justified** if the reconstruction creates a second writable owner for task state, plan/gates, or canonical behavior, or if it adds no unique load-bearing fact to the completed ticket.
- **A narrow pilot is eligible** only if it keeps Orchestra's tracker, gates, worktrees, runtime/session state, and evidence artifacts authoritative; has one derived or separately scoped artifact; and measures a real cross-runtime handoff outcome against the current workflow.
- Any pilot stops on lost/overwritten facts, conflicting task completion state, archive/spec drift, tool-generated files outside the declared scope, or median prompt/context overhead above 10% without a correctness gain.

No OpenSpec package is installed and no runtime, prompt, config, task record, or production file is changed by this experiment.
