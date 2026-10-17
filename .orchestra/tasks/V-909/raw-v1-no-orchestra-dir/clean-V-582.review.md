## Summary

Reviewed the complete diff from `f9b0fbf8f72c78f57480bd3341bcd6dccc107eeb` to `0c104cb21b0d00346947ca3cf13e30d585e97e31`. No files were changed.

## Findings

### Suggestion

- [scripts/probe_free_models.py](/home/kesha/v909-work/v909-clean-V-582-nfubss6c/scripts/probe_free_models.py:182): `--model` accepts IDs absent from the fetched `:free` routes and probes them anyway. A typo or paid model ID could therefore send a request outside the script’s advertised free-route scope. Reject IDs that are not in the fetched candidate catalog.
- [scripts/probe_free_models.py](/home/kesha/v909-work/v909-clean-V-582-nfubss6c/scripts/probe_free_models.py:190): The time budget is checked only before each route. A route already in progress can exceed it by up to the request timeouts and retry delay. If the budget is intended as a hard wall-clock limit, enforce it within probing or before each request.

## Verdict

APPROVED — the suggestions do not block the change.