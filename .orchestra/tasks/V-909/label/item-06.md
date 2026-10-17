# item-06

Commit under review (in /home/kesha/orchestra, read-only): `a05b13d0ca26a88ce159f400fd02c19ac54a9f2b`
Subject / date:
#85: #85: add DeepSeek V4 Pro/Flash models
2026-06-12

The diff reviewed is `git -C /home/kesha/orchestra show a05b13d0ca26a88ce159f400fd02c19ac54a9f2b -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the specified commits. It adds DeepSeek model IDs, aliases, context limits, backend mappings, and token prices.

## Findings

### blocking

- `app/models.py:70-71` routes both DeepSeek IDs to the Claude backend. That backend passes the model ID directly to Claude Code via `ClaudeAgentOptions(model=self.model)` in [backend_claude.py](app/backend_claude.py:133). No DeepSeek provider configuration or routing is added, so selecting either model sends its ID to the Claude runtime and the worker cannot use DeepSeek. Add a compatible runtime/backend path and route these IDs through it.

## Verdict

NEEDS WORK
