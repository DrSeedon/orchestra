## Summary

Reviewed the complete diff pinned between `1f05e9c…` and `4725a81…`. The KB index is added to the shared system prompt using the agent’s project scope, including on prompt reassembly. The contract checker and prompt builder share the same parser.

## Findings

### Suggestion

- [app/kb_index.py](/home/kesha/v918-work/v918-clean-17.r0-8xzu92dg/app/kb_index.py:43): `read_text(encoding="utf-8")` can raise `UnicodeDecodeError`, which is not caught by the `except OSError` in `kb_index_block`. A README with invalid UTF-8 therefore aborts prompt assembly and can prevent an agent from spawning, despite the comment saying an unreadable index should not take down every spawn. Consider handling decode errors like other unreadable-index failures, or reporting them as an explicit invalid-index error.

## Verdict

APPROVED — one resilience improvement noted.