# Codex startup blocker and guard audit

## Confirmed incident

Local native state inspection (read-only) returned 52 migrations, latest
`52 / projects recency / success=1`. The seed signatures in backend_codex.py were
captured from 0.150.1, but their dictionary key was CODEX_CLI_HISTORY_VERSION.
Commit d6155f9d changed that history-import constant to 0.153.4 without changing
the signatures. Thus a generation probe was treated as proof of a different DB schema.
The pin was used for two different contracts: importing history and cloning native state.

## Fix

- The historical seed signature remains labelled 0.150.1, its actual provenance.
- Other CLI versions use native startup/migrations without Orchestra inspecting or
  copying their state. Updating the history-import pin cannot relabel seed evidence.
- Failure to probe the optional seed version, inspect a seed candidate or find a donor
  skips only the optimization. It does not veto a safe provider-owned startup path.
- Once a state-copy operation begins, its validation/rollback errors remain fatal;
  those errors are not converted into permission to overwrite ambiguous history.
- Normal per-home locking and config refresh remain intact.

## Why it happened / wider scan

The primary cause is a code ownership error, not evidence that a prompt caused the bug.
#305 added protected state seeding; #503 later updated the shared version label as part
of Astra integration. The tests also used that mutable label as a fixture identity,
making a runtime-version update look like a request to bless old evidence again.

The prompt scan found an independent friction amplifier: orchestration Step 0 required
asking first whenever not 100% sure. It now requires repository investigation for
discoverable facts and reserves clarification for material scope/authority decisions.
The same module now scopes blocking checks to the action whose safety needs them.

Related version checks reviewed: Claude/Codex native history import and typed runtime/
task manifest versions. These protect format-dependent operations or owned canonical
data, unlike the startup seed optimization. They were not blindly removed.
This is an audit of this startup/version-check family, not a claim that every possible
development blocker in Orchestra has been eliminated.

## Validation and deployment boundary

132 tests passed in test_codex_managed_state.py + test_backend_codex.py before the prompt
wording change. The new cases cover the installed history version with migration 52,
an unknown future CLI, version-probe failure, and unsupported read-only seed inspection;
each reaches native connect without modifying the target database.
Existing tests retain WAL backup, corruption refusal, rollback and concurrent-home locks.
No native DB was edited and no service restarted. Python changes need an owner-initiated
restart after merge; VPS deployment is not authorized by this change.
