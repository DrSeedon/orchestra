# V-1037: edit temporary rules in place

Suggested implementation commit subject: `V-1037: allow editing temporary rules in place`.
The worker did not commit or push: the platform imports the changed files into
`task-V-1037/feat-temp-rule-edit`. No services were restarted.

## Changes

- `app/mcp_stdio.py`: optional nullable `text`, `reason`, `targets`, `mode` parameters;
  supplied empty strings/lists are forwarded, omitted/null optional fields stay unchanged.
- `app/routes/temp_rules.py`: matching update model and forwarding to the storage API.
- `app/temp_rules.py`: shared create/update text, reason and deadline validators;
  atomic partial edits preserve id, author, creation time, project and unrelated fields.
  Update uses the existing file lock, write/commit and rollback path. Its automatic
  commit subject starts with `V-1037:` and commits only `.orchestra/temp-rules.yaml`.
- `tests/test_temp_rules_v927.py`: regressions for identity, next prompt assembly,
  targets/reason, invalid updates without writes/commits, mode changes, authority,
  isolated commits with unrelated staged changes, rollback and concurrent partial edits.
- `tests/test_mcp_stdio.py`: MCP protocol forwarding and old keep/date calls.

## Contract details and compatibility

- Existing `expires_at` and `keep=true` calls remain supported for dated rules.
- `mode=permanent` or `keep=true` clears the inherited deadline. Supplying a date
  with permanent, or keep=true with another mode, is refused.
- A transition to expires/review reuses an existing future date; a permanent rule
  requires a supplied date to become dated again. Supplying a date alone on a
  permanent rule is refused, matching creation validation.
- Text/reason/targets-only edits of overdue review and expired rules keep the old
  deadline. Review rules remain active; expired rules remain inactive until extended.
  This permits correcting old rules without unintentionally extending their lifetime.
- The notice state key is (scope, rule id, due_at). Content-only edits preserve that
  key; date extension changes it, preserving the existing reminder rearming behavior.
- Own-project access still comes from `_visible`/`_locate`; global edits still require
  both the Orchestra orchestrator name and Orchestra scope. Authorization is checked
  again for the actual entry under the mutation lock.

## Checks actually run

1. Attempted the required command offline:
   `uv run --frozen python -m pytest tests/test_temp_rules_v927.py tests/test_mcp_stdio.py -q`
   with `UV_OFFLINE=1`, downloads disabled, nice=15 and scratch files inside this task.
   Exit 127: `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
   pytest, FastAPI and MCP are not installed in the available interpreter. No packages
   were downloaded. See `pytest-attempt.log`.
2. Created a temporary task-local venv without pip, using available system-site YAML.
   Executed `offline_checks.py` with that venv, PYTHONPATH=., bytecode disabled and nice=15.
   **9/9 checks passed**. Storage checks execute the actual `app/temp_rules.py` source,
   with db/prompting imports stubbed, real YAML files and fake git results. The real MCP
   function and HTTP handler bodies execute after AST extraction, without their frameworks.
   These wiring checks do not validate FastAPI/Pydantic or MCP schema/protocol integration.
3. **8/8 deliberate source mutations killed**: id replacement, accepting an empty reason,
   bypassing global authority, accepting a missing deadline, accepting a permanent date,
   ignoring targets, skipping persistence and broadening the commit path. Mutations run
   in memory; source files on disk remain unchanged. See `offline-checks.log`.
4. Compiled all five modified source/test files plus the offline runner; checked trailing
   whitespace. Reviewed modified code and new artifacts for accidental secrets.

Imported app: `<hub-workspace>`.

## Handoff / remaining verification

Run the two pytest modules in the complete project environment before acceptance.
Full HTTP proof/Pydantic behavior, FastMCP registration/protocol behavior and real-git
isolated commit/hook rollback tests are supplied but were not executable here.
The offline checks use fake git responses and do not claim real-git verification.
The full suite and root instruction contract script (not supplied in this worker copy)
were not run. Python changes have not been loaded into a live service.

To reproduce the supplemental checks in the full environment:
`PYTHONPATH=. uv run --frozen python .orchestra/tasks/V-1037/offline_checks.py`.
All scratch repositories/files and the bootstrap venv were removed after checks.
