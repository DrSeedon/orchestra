## Summary

Reviewed the complete diff between the pinned commits and traced the modal’s dropdown loading and session creation paths. The hidden Role dropdown still gets populated from the selected pipeline, so its first option becomes the submitted role.

## Findings

### Suggestion

- With the default pipeline, roles are sorted alphabetically. `populateRoleDropdown()` therefore selects `full-cycle` first, and `createOrchestrator()` submits that value instead of its `'orchestrator'` fallback. New sessions can be marked `is_orchestrator: true` while carrying the `full-cycle` role, which has worker behavior. Set the hidden role explicitly to `orchestrator` (and ensure the selected pipeline provides that role), or choose an orchestrator-kind role as the default.

## Verdict

NEEDS WORK — the hidden Role control does not reliably produce the intended orchestrator default.