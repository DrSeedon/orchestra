## Summary

APPROVED. `open_fan` is included in the Codex allowlist and rendered TOML. The registration-derived guard detects missing and stale entries while preserving exactly the two intentional exclusions.

## Findings

None.

## Verdict

APPROVED

`uv run pytest -q tests/test_backend_codex.py` → **78 passed in 7.86s**.
