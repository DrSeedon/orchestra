# Gemini Web prompt compaction

Source: helper task from Maxim, 2026-11-06. Authorized scope: format_prompt,
unit tests, focused pytest; no commit, push or deployment.

Finding: format_prompt retained earlier platform context refresh notes, truncated
only system content and placed tool definitions before the conversation.

Change: retain only the last refresh note, truncate every oversized string content
on a copy and place tool definitions after the conversation next to the response
instruction. Preserve JSON serialization, refusal filtering and input messages.

Validation: `.venv/bin/pytest tests/test_gemini_web_harness.py -q`:
124 passed in 4.99s. `git diff --check` passed.
Imported app: `/mnt/claude-data/astrahancev-maxim-911aird/orchestra/app/__init__.py`.
Coverage includes refresh deduplication, truncation at 12000/12001/37000 characters
for system/user/tool/assistant, input immutability and trailing tool definitions.
