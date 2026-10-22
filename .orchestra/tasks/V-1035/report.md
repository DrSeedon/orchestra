# V-1035: honest continuation after platform interruption

## Result

Implemented in the worker copy; ready for the platform to copy/commit to
`task-V-1035/fix-interrupt-honest`. Suggested commit header:
`V-1035: distinguish platform interruptions from user refusals`.
No service restart, deployment, provider call, git commit or push was performed.

## Source of the misleading refusal

The exact full text

> The user doesn't want to take this action right now. STOP what you are doing and wait for the user to tell you how to proceed.

is embedded in the installed Claude CLI 2.1.293 binary. A fixed-string,
read-only binary search found it three times; nearby embedded JavaScript assigns
it to `lE`. Before this change, that literal did not occur in Orchestra's Python
sources. `app/backend_claude.py::_make_auto_approve` denies only explicitly
blocked tools with its own reason; `_pretool_output` also supplies explicit
policy reasons. Neither contains this generic refusal.

The CLI binary is outside the supplied source and was not modified. Implemented
the requested fallback: every restart recovery notice explicitly explains that
this tool result immediately preceding the platform cut was caused by that cut,
not by the user. The exact CLI permission/control-channel cancellation branch
was not reproduced against a running provider; the binary evidence establishes
the literal's location, not a live shutdown trace.

## Changes

- `app/session_state.py`: one shared notice naming the interruption cause,
  denying any inferred user refusal, warning that the call may or may not have
  run, requiring effect/working-tree checks before repeating it, and instructing
  the worker to continue its bound task without waiting for its orchestrator.
  Legacy rows without a task binding say “your current task”.
- `app/manager.py`: restart notices use that explanation both with saved native
  history and before replaying an unsaved turn. Commands are no longer asserted
  to have definitely stopped. Existing direct delivery through
  `auto_resume_all` → `_inject_restart_notice` → `send(worker.id, ...)` remains;
  a manual stop during the stagger cancels automatic continuation. Failed
  delivery still signals the blocked worker to its parent.
- `app/limit_wake.py`: reset wake-ups explain the subscription interruption,
  carry the task reference from the current candidate (old timers need no
  schema/config migration), and continue to target the worker itself. A manual
  stop observed after loading also prevents a wake. Existing claims and token
  reconciliation remain intact.
- Non-obvious recovery bug: a `system/restart` or `system/runtime_reconnect`
  continuation that immediately hit the subscription limit was classified as
  an incidental system notice and excluded from the next reset wake. Those two
  provenance subtypes now remain eligible. Rules reminders and other incidental
  notices stay excluded; manual stops still win. Malformed legacy provenance
  does not crash the classifier.
- `app/session.py` and `app/session_hibernate.py`: listener and heartbeat
  reconnects deliver the same honest explanation and task reference.
- `tests/test_interruption_honest_v1035.py`: 19 regression tests using isolated
  SQLite and mocked delivery/provider boundaries. `tests/test_session.py`:
  updated two old literal-message assertions to check the new recovery semantics;
  their quota/history assertions remain unchanged. No frozen acceptance tests
  were changed.

## Checks actually run

1. Attempted `uv run --frozen --offline python ...`: unavailable. The installed
   `uv` is only a remote shim and returns exit 127: “uv: not found on the hub and
   not inside a Mutagen-synced project (cannot forward via on-remote)”. No local
   project `.venv`, pytest or Claude SDK was supplied.
2. Ran `.orchestra/tasks/V-1035/offline_checks.py --mutations` with an available
   maintenance virtualenv interpreter, bytecode writes disabled, nice=15 and a
   2 GiB process address-space limit. All 19 regression tests passed. See
   `offline-checks.log`, including the absolute path of the imported `app`.
   This runner imports real `db`, `events`, `limit_wake` and `session_state`.
   It compiles the exact recovery methods from the `manager`, `session` and
   `session_hibernate` source AST while omitting unrelated SDK/HTTP imports and
   class construction decorators. This is a limited behavioral check, not a
   successful full-module/pytest integration run.
3. All 13 in-memory mutations were killed by assertion failures: missing restart
   explanation, restart misrouted to parent, missing automatic restart wake,
   restart overriding a manual stop, missing limit explanation, limit wake
   misrouted to parent, missing task reference, restart→limit filtering regression,
   limit wake overriding a manual stop, duplicate wake after claim reconciliation,
   missing listener explanation, missing heartbeat explanation, and requiring optional heartbeat task metadata. Source files
   were not mutated on disk.
4. Syntax-compiled all eight changed Python files without writing bytecode.
   Reviewed the edited source and test sections. Scanned task artifacts using
   `app.secret_mask.mask_secrets`; no secret-shaped values needed masking.

Regression coverage includes native and unsaved sessions, ordered replay of only
the cut turn, idle workers, no parent present, delivery failure, legacy empty task
bindings, legacy limit-error rows, malformed provenance, Anthropic and OpenAI
reset delivery, stale turns, manual stops, claimed-delivery reconciliation and
unseen-claim retry. All databases were private test databases; no live service,
provider CLI or credentials were used by the checks.

## Remaining validation

Run in the complete project environment before acceptance:

```sh
uv run --frozen python -m pytest tests/test_interruption_honest_v1035.py tests/test_restart_continuation_919.py tests/test_limit_wake.py tests/test_session.py tests/test_session_hibernate.py -q
```

Full module imports, the existing regression suites and a real restart/CLI
cancellation were not validated here. The source changes are not evidence of
updated Python in the live process. Any eventual restart remains the owner's
separate decision. This private copy has no `.git`; the platform owns the commit
and branch placement.


## Follow-up: optional heartbeat task metadata

The orchestrator reported that its complete-environment run had 332 passing tests
and one failure in
`tests/test_session_hibernate.py::test_dead_listener_heartbeat_uses_session_reconnect_path`.
The fixture is a `SimpleNamespace` without `task_id`; direct access introduced by
this change raised `AttributeError` before `backend.send`. This was a regression
in the first delivery, not a provider or environment failure.

`app/session_hibernate.py` now passes `getattr(s, "task_id", "")` to the shared
notice formatter. Added a behavioral regression with absent metadata that checks
formatter delegation with an empty task reference, successful backend delivery,
and preservation of the active backend and running state. It does not assert
prompt wording. `CHANGELOG.md` records the fix under Unreleased / Fixed.

Re-ran the offline checks: 19 new tests passed, and all 13 mutations were killed.
The additional mutation restores direct `s.task_id` access and is caught by the
new test. Also executed the exact body of the reported existing heartbeat test,
extracted from its source with isolated runtime metadata: passed. This does not
claim a full pytest re-run; that still requires the complete project environment.
The private hub copy still has no `.git`, so the platform must create the commit.
