# wf-run-engine

- `claude -p --tools ''` consumes positional text as part of the variadic option; feed the prompt on stdin. A scratch cwd plus `--setting-sources '' --strict-mcp-config --mcp-config '{"mcpServers":{}}'` produced valid subscription cost JSON.
- Parallel `codex exec --ephemeral --ignore-user-config --ignore-rules --json -` calls shared the normal Codex home successfully; keep an explicit concurrency cap even though the two-call probe passed.
- Worktree lifecycle around `asyncio.to_thread` must drain the inner thread through repeated cancellation before propagating `CancelledError`; never hold `repo_mutation_lock` in the event-loop thread across an `await`, or parallel cleanup deadlocks.
