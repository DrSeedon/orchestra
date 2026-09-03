# Task #233 — default-off switch for the Claude Bash hook

## Result

`ClaudeBackend._make_client()` installs the managed Bash `PreToolUse` hook only
when `CLAUDE_BASH_HOOK_ENABLED` is exactly `1`. With the variable absent or set to
another value, `options.hooks` is `None` and `can_use_tool` keeps the pre-#228
allow behavior for Bash payloads. The flag is read when the client is built, so a
restart/reconnect applies a change without reverting or redeploying code.

This switch does not broaden the #228 grammar. Enabled mode uses the same hook
factory and classifier for background Bash, recursive `rm`, world-writable
`chmod`, and direct `curl | sh/bash`; a safe command remains undecided by the hook.

## Oracle and implementation

The acceptance oracle was committed RED in `cc134ec7` before implementation and
was not modified by the Luna executor. Its first run failed for the missing
default-off behavior:

```text
F                                                                        [100%]
1 failed in 1.30s
E assert {'PreToolUse': [HookMatcher(...)]} is None
```

Luna implemented the production change in its commit `9251d206`; Orchestra merged
it as `11de3f05`. The production diff is `+3/−1` in
`app/backend_claude.py`. The executor changed no tests, fixtures, configuration,
or documentation.

## Verification

Author-side acceptance and focused regression after merge:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q \
  docs/tasks/233/acceptance/test_bash_hook_flag.py
1 passed in 1.26s

/home/kesha/orchestra/.venv/bin/python -m pytest -q \
  tests/test_backend_claude.py \
  docs/tasks/233/acceptance/test_bash_hook_flag.py
25 passed in 7.99s

CLAUDE_BASH_HOOK_ENABLED=1 \
  /home/kesha/orchestra/.venv/bin/python -m pytest -q \
  docs/tasks/228/acceptance/test_payload_hooks.py \
  docs/tasks/228/acceptance/test_payload_hooks_followup.py
6 passed in 2.49s
```

The oracle covers both directions in one test:

- flag absent → `hooks is None`; all four formerly blocked payload classes are
  allowed by `can_use_tool`;
- flag `1` → exactly one Bash matcher; all four payload classes are denied and a
  safe Bash command receives no permission decision.

Mutation used one `cp → mutate → pytest → mv → touch → grep → green repeat`
command. Replacing the flag condition with `if True` failed the default-off
assertion (`1 failed in 1.44s`, exit 1). After rollback,
`restored_marker_count=1` and the same oracle returned `1 passed in 1.15s`.

## Review

The single shared-runtime Codex round reviewed the complete diff, reran the focused
command, and returned the verbatim verdict **`APPROVED.`** with no findings. Its
qualifying evidence was:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_backend_claude.py docs/tasks/233/acceptance/test_bash_hook_flag.py
25 passed in 8.06s
```

The full verdict is recorded in `docs/tasks/233/codex-review-impl.md`.

## Breaking / rollout

Default behavior changes relative to merged #228: the hook is off until the
operator explicitly sets `CLAUDE_BASH_HOOK_ENABLED=1` and restarts/reconnects.
Changing the flag still requires restart/reconnect, but disabling no longer needs
a code revert or deploy.

Until #233 reaches `main`, the closest restart for any reason still activates the
unconditional #228 hook. This is a bounded rollout window, not a measured incident:
#228 is fail-open and had zero historical false positives on 2,374 Bash calls, but
the activation would be unplanned. This task does not restart the service, change
live environment/settings, or touch live sessions.

## Files

| File | Change | Purpose |
|---|---:|---|
| `app/backend_claude.py` | +3/−1 | default-off flag at client construction |
| `docs/tasks/233/acceptance/test_bash_hook_flag.py` | +50/−0 | frozen two-state oracle |
| `CHANGELOG.md` | +1/−1 | operator-visible flag and apply boundary |
| `docs/tasks/233/report.md` | new | evidence and rollout boundary |
| `docs/tasks/233/codex-review-impl.md` | new | one-round evidence-backed verdict |
