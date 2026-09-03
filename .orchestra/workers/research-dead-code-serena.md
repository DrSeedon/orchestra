# Research dead-code worker

- For reachability audits, Serena Python LSP `{}` is common on decorator/registry entrypoints (`@mcp.tool`, FastAPI routes) and intentional tombstones; always pair it with AST decorators, generated/source registries, dynamic strings, DOM/template, prompts, and external entrypoints.
- If `main` advances while a research worktree remains on an older commit, audit `git archive main` in a temporary directory and record both SHAs; do not silently present the branch snapshot as current main.
