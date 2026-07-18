# Codex Pro usage source

Checked against Codex CLI 0.144.5 on 2026-07-18.

- `codex --usage` does not exist, and there is no top-level `codex usage` command. The interactive TUI exposes `/usage` and `/status`.
- The generated app-server protocol has `account/rateLimits/read` and `account/rateLimits/updated`. The read response includes `rateLimits`, `rateLimitsByLimitId`, primary/secondary windows, percentage used, window duration, reset epoch, plan type, credits, and reset credits.
- A live ChatGPT-auth call returned the `codex` bucket with plan `prolite`, a 10,080-minute (7-day) primary window, and no secondary window. The UI must therefore render windows by their reported duration rather than assume that primary always means 5h.
- Codex internally uses `/wham/usage`, but that is not a documented public API contract. Calling it directly would require handling private ChatGPT credentials and duplicating Codex's response normalization.
- Standard OpenAI API `x-ratelimit-*` headers describe API-key RPM/TPM quotas, not ChatGPT subscription windows. Codex traffic carries `x-codex-*` metadata and streamed rate-limit events, but the app-server method already merges those into the subscription snapshot needed by the dashboard.
- `~/.codex/sessions/**/rollout-*.jsonl` stores `token_count.rate_limits` snapshots after turns. These are useful for diagnostics or fallback, but can be stale when no recent turn has run. `state_5.sqlite`, config, and cache files do not provide a simpler current-limit contract.

Decision: query `account/rateLimits/read` through the installed `codex app-server`, normalize it in `/api/usage`, cache it for five minutes, and fail soft so Codex availability never breaks the existing Claude display.
