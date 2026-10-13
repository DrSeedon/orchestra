# V-826 — agent documentation checks

## Main baseline

The `main` worktree was clean at `74309e0106e1d41dc9d7960022a737b3fa86d102`. Existing KB inventory/index checking passed. Running the new reference checker against `/home/kesha/orchestra` found four unresolved relative file references, all in `.orchestra/kb/models-and-quotas.md`: `truncation-analysis.md`, `codex-resets-chronicle.txt`, `_internal/message_parser.py`, and `backend_codex.py`. These were stale or under-specified references; the worktree version now links to the existing V-548 analysis and reset chronicle, names `claude_agent_sdk._internal.message_parser` as a dependency module, and uses `app/backend_codex.py`.

An initial path-shaped-token pass produced 17 apparent missing references. Thirteen were not repository-relative files: four external `owner/repo` identifiers, five slash-command/API-route/MIME examples, an external bundled runtime path, one Git branch name, one placeholder, and a substring falsely extracted from `bench-models.md`. Refining candidate recognition reduced the main result to the four actual broken file references above. Three exact exceptions remain: the optional `.claude/AGENTS.md` hierarchy example, the unmerged branch-only `root-cause-plan.md`, and ignored generated `data/orchestra.db` (which `git check-ignore` can inspect when absent in a clean checkout). Absolute/home paths, URLs, placeholders, Git `revision:path` syntax, and slash identifiers are excluded as non-relative file paths.

## Implementation and checks

`check_instruction_contract.py` now runs the link checks alongside the root instruction and KB checks. KB topic inventory and index parsing continue to use `app.kb_index.kb_topic_files` and `kb_topic_index`; no second KB parser was introduced. Markdown links resolve relative to their containing file. Relative file paths in inline code resolve from repository root.

The check is available locally as `uv run --frozen python scripts/check_instruction_contract.py` and runs once in CI's test shard 0. Tests cover unindexed topics, missing KB index targets, broken Markdown and backtick paths, and Markdown-link examples inside code spans. `tests/test_instruction_contract.py`, `tests/test_knowledge_instruction_source.py`, and `tests/test_kb_index_injection_522.py` passed: 29 passed. The local contract command and `git diff --check` passed.
