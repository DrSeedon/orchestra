## Summary

Implementation satisfies task #233:

- Hook defaults OFF when the flag is absent.
- Only the exact value `CLAUDE_BASH_HOOK_ENABLED=1` enables it; other truthy-looking values do not.
- The flag is read from the parent process environment when building the Claude client.
- Disabled mode installs no hook and preserves the existing `can_use_tool` allow path.
- Enabled mode reuses the existing hook factory and classifier unchanged.
- The oracle covers default-off behavior and all four enabled-policy payload classes.

## Findings

No blocking issues, suggestions, or questions.

## Verdict

APPROVED.

Evidence:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_backend_claude.py docs/tasks/233/acceptance/test_bash_hook_flag.py
25 passed in 8.06s
```
