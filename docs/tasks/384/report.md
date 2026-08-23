#384 — literal-argv acceptance command contract

## Implementation

- `app.acceptance.parse_acceptance_command` is the single parser used before persistence and
  by `run_command`. It returns the exact `shlex.split` argv passed to `subprocess.run(...,
  shell=False)`.
- Non-shell commands reject unquoted shell operators, redirections, command/variable
  substitution, backticks, newlines, and malformed quoting. Quoted ordinary arguments remain
  argv data.
- Shell execution is an explicit three-element argv only: `bash`/`sh` plus `-c`/`-lc` plus one
  non-empty script argument. The runner never changes to `shell=True`.
- Task create and update validate in `app.tm` before their INSERT/UPDATE. REST validation errors
  include a stable `reason`; explicit `clear_acceptance_command=true` still maps to an empty
  command, while a legacy empty update remains omitted.
- Proof-bearing MCP creation now has the same authoritative project binding as update: an explicit
  `project` or `scope` must resolve to the caller session's project.
- An invalid legacy row returns `status=inconclusive`, `reason=invalid_acceptance_command`, the
  validator-specific `validation_error`, and `guidance=FIX_ACCEPTANCE_THEN_RETRY`; the merge
  response keeps the same repair action and does not call the merge executor.

## Reported command

Rejected before persistence:

```text
test "$(find . -type f | wc -l)" -eq 7 && python3 check.py
```

Reason: `shell_syntax_requires_explicit_shell`. The error explains that the runner has a
literal-argv contract under `shell=False` and gives the repair form `bash -lc '<script>'`.

## Verification

- RED before implementation: the five new focused cases failed (missing parser/error type, the
  stored command ran as literal argv, and proof-bound create accepted a foreign project).
- `uv run pytest -q tests/test_acceptance.py tests/test_tm.py tests/test_mcp_proof.py
  tests/test_mcp_stdio.py` → `158 passed in 41.18s` after the review fixes.
- `uv run pytest -q tests/test_merge_test_gate.py tests/test_acceptance.py` →
  `42 passed in 22.97s` after the review fixes.
- `uv run python -m py_compile app/acceptance.py app/tm.py app/routes/tm.py` → exit 0.
- `uv run ruff check ...` was unavailable because `ruff` is not installed in the project venv;
  this was not reported as a passing check.
- Read-only compatibility probe against the live DB: 14 non-empty stored acceptance commands;
  13 validate and one existing command (`scope:/home/kesha/katya-work #3`) is intentionally
  classified `shell_syntax_requires_explicit_shell`. No task row was changed.

## Mutation seams

Three independently named tests replace the canonical parser with a sentinel rejection at create,
update, and runner. Each proves its own consumer calls the validator; the runner test also proves
`subprocess.run` is not reached after validation failure.

## Review

Route: Sol, because the diff changes persistence validation, an external REST error contract, and
proof-bound authorization. Author metadata: `gpt-5.6-sol` on the Codex runtime. Reviewer:
`gpt-5.6-sol` in a fresh independent `codex_review` thread recorded in
`codex-review-impl.md`; independence is a separate reviewer thread and artifact, not a different
model family.

Round 1 found two blockers: basename-based shell recognition falsely rejected `./bash --check`,
and a quoted empty executable (`''`) passed persistence. Both were reproduced, fixed, and covered
with regression assertions. The permitted resume round verified both as `FIXED`, found no new
issues in the seam, ran `uv run pytest -q tests/test_acceptance.py --tb=short` (`17 passed in
15.57s`), and returned `APPROVED` with a literal changed-file quote.

## Pre-mortem

- A quoted ordinary argument containing `|`, `>`, `$HOME`, or spaces is falsely rejected → parser
  assertions preserve all four as literal argv data.
- A lookalike executable such as `./bash` is mistaken for an opted-in shell, or a standard absolute
  shell path bypasses structural validation → assertions cover `./bash --check`, valid
  `/bin/sh -c`, and invalid `/bin/bash script.sh`.
- An invalid combined update changes title/revision before failing command validation → direct-core
  and public-route tests compare title, command, and `sync_revision` before/after rejection.
- #383 recovery regresses so omission clears a command or explicit clear is rejected → existing
  core, REST, and MCP clear/omission tests are included in the 158-test focused suite.
- A proof-bearing orchestrator writes acceptance into a foreign project → create and update proof
  tests assert the foreign row is absent/unchanged.
- A legacy invalid row reaches `subprocess.run` or the merge executor → independent runner wiring
  and merge-spy tests assert structured guidance and zero executor calls.
