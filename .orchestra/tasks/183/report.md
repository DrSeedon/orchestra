# Task #183 — restore default Codex review mode

## Diagnosis

Codex CLI 0.146.0 treats `--uncommitted`, `--base`, `--commit`, and a custom
prompt as mutually exclusive review targets. Orchestra combined `--uncommitted`
with the stdin prompt sentinel, so argument parsing returned exit 2 before Codex
started a review.

This contract was verified in three places:

- installed `codex exec review --help` and a parser-only reproduction on 0.146.0;
- the current official [Codex CLI manual](https://learn.chatgpt.com/docs/developer-commands.md?surface=cli),
  which explicitly says the four targets conflict;
- [`openai/codex` `codex-rs/exec/src/cli.rs`](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs),
  where `ReviewArgs.uncommitted` declares
  `conflicts_with_all = ["base", "commit", "prompt"]`.

## Decision

Use the custom review prompt as the single review target and remove
`--uncommitted`. The prompt preserves caller-supplied PROJECT CONTEXT and directs
Codex to inspect staged, unstaged, and untracked changes with Git. The native
`--uncommitted` target cannot carry those custom instructions in this CLI version.

The custom review request is the sole target passed to the Codex review parser.

The existing `exec resume` path and `mode="exec"` already accept stdin prompts.
Their 0.146.0 help contracts allow an optional prompt, and both paths completed
live reviews during #182. They are unchanged in #183.

## Tests

- The generated-command test now rejects `--uncommitted` in review mode and
  requires the prompt to name staged, unstaged, and untracked changes.
- A parser-only test asks the installed CLI to parse the former incompatible
  combination and requires exit 2 with the conflict message. It skips when Codex
  is not installed; the generated-command assertion remains mandatory everywhere.
- The actual `--help` output cannot prove this constraint: with `--help`, Codex
  exits 0 before conflict validation and the rendered option list does not state
  mutual exclusion. The parser probe is therefore stronger than help-text matching
  and makes no network or model request.
- `uv run pytest -q tests/test_codex_review_sandbox.py tests/test_mcp_codex_review.py tests/test_codex_review_artifact.py`
  — 19 passed.
- Mutation restored `--uncommitted` beside the prompt; the review-mode test failed
  on the forbidden flag while the exec-mode case stayed green.

## Live acceptance

The patched wrapper was imported in a fresh Python process and invoked with the
default `mode="review"` against the real uncommitted worktree. The generated command
contained the custom stdin prompt and no `--uncommitted`. Codex CLI returned exit 0,
and the finalizer wrote `docs/tasks/183/live-review.md`.

The reviewer ran both targeted test files (`15 passed`) and supplied this exact
sentence, which was absent from the request:

> The custom review request is the sole target passed to the Codex review parser.

Evidence check:

```text
$ grep -F 'The custom review request is the sole target passed to the Codex review parser.' docs/tasks/183/report.md
The custom review request is the sole target passed to the Codex review parser.
```

After the parser test was isolated in a non-Git directory, the same review session
was resumed through the real `exec resume` path. Round 2 ran all three targeted files
(`19 passed`), reported no new findings, and returned:

> PASS — task #183 is ready.

The two live rounds therefore cover both the corrected fresh default command and its
unchanged resume command. `mode="exec"` remains unchanged and retains its #182 live
evidence.
