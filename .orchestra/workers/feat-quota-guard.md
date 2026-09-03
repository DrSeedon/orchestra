# feat-quota-guard — personal memory

- If `codex_review` cannot read the workspace because its `bwrap` sandbox fails, resume the **same**
  review session with a bounded self-contained evidence packet and tell it not to execute commands.
  This preserves debate context and can still produce a falsifiable technical verdict.
- In async singleflight code, recompute freshness time after acquiring the shared lock. A timestamp
  captured before waiting can be older than the winner's cache write and falsely trigger one refresh
  per waiter; test this with all waiters queued before releasing the first fetch.
