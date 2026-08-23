# research-codex-transport

- Codex injects absolute `$CODEX_HOME/skills/...` paths into model-visible skill instructions. In
  controlled A/A or A/B work, random per-run home paths change context/token counts; recreate fresh
  state at one fixed home pathname and verify rollout prefix hashes before timing.
