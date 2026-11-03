# V-1257 — discovery notes

2026-11-03 UTC. Worker remains hubsol; no inference, delegation, account inspection, source edits, deployment or model switch.

Observed limitations requiring root decision before implementation:

- Live `orchestrator_capabilities` identifies `gemini-4-argon`, label `Gemini 4 Argon`, provider instance/driver `antigravity`; it does not expose funding, tools, image modalities, file access or Antigravity runtime modes. Provider-level child support is advertised, but Argon is absent from every delegation category.
- Orchestra `ensure_hub_worker_allowed(model)` has no design context parameter. The session persists role, pipeline and task identity; the task schema has free-text description/tags but no typed design admission. Treating any reason/tag/name containing “design” as authorization would create a new policy contract and an escape from the current rule.
- `hub_pool.provider_for_model()` maps only Claude/Codex instances. Adding an Antigravity model mapping alone would skip its capacity check. Current Hub `billing_mode="free"` and zero recorded cost are broker accounting, not evidence of the upstream plan or credit settings.
- Frozen Antigravity runtime tests describe an older, optional native backend and skip when it is absent. They do not establish Hub Argon support or permission to implement a new native route.

Verification blocker found immediately after the prescribed uv run: four failures depend on `.orchestra/pipelines/default/pipeline.yaml`, which is absent from the supplied copy. Do not create a replacement manifest, modify tests or borrow protected files. Details in checks.log; results summarized in discovery.md. Other checked source files remain unchanged.
