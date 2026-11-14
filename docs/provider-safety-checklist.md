# Subscription OAuth Provider Safety Checklist

Every subscription OAuth provider (`claude`, `codex`, `grok`, `antigravity`, and any future
consumer/subscription CLI) MUST satisfy all six runtime invariants enforced by
`app/provider_safety.py` and verified by `tests/test_provider_safety_contract.py`.

## 1. Fail-Closed Residential Proxy Egress
- Register the runtime in `SUBSCRIPTION_OAUTH_RUNTIMES` and `PROVIDER_PROXY_ENV_KEYS` in `app/provider_safety.py`.
- Call `await verify_provider_egress("<provider>")` at **every** outbound launch/turn/probe boundary (`connect`, `send`, `reconnect`, review jobs, manual usage probes).
- Never allow fallback to raw datacenter egress (`Contabo AS51167`, `Hetzner AS24940`, `OVH`, `DigitalOcean`, `AWS`, `GCP`, `Azure`) or blocked geographies (`RU`, `BY`). If `ORCHESTRA_RESIDENTIAL_PROXY_URL` / `<PROVIDER>_PROXY_URL` is missing, unreachable, or resolves to a datacenter ASN, fail closed immediately (`EgressSafetyError`).

## 2. Sanitized Transport & Billing Environment
- Build CLI environments exclusively through `build_provider_env("<provider>", base_env, extra_env=...)` (or `build_claude_sdk_env_overlay` for `claude-agent-sdk`).
- Strip untrusted `.mcp.json` / repo-local overrides (`*_PROXY`, `NO_PROXY`, `*_BASE_URL`, `*_API_KEY`, `SSL_CERT_*`, `NODE_EXTRA_CA_CERTS`, `NODE_OPTIONS`, `LD_PRELOAD`) **before** pinning proxy vars.
- Keep loopback (`localhost,127.0.0.1,::1,[::1]`) in `NO_PROXY`/`no_proxy` and strip wildcard `*`, `/0` CIDRs, and vendor domains. Local Orchestra HTTP clients (`app/mcp_stdio.py`) must set `trust_env=False` so `INTERNAL_TOKEN` never traverses any proxy.
- Never mix paid API keys (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) into subscription OAuth sessions.

## 3. Zero Worker-Tool Bandwidth Leakage on Residential Proxy
- Worker shell/Bash tools (`git`, `uv`, `pip`, `npm`, `curl`, `playwright`) must **never** inherit `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`GRPC_PROXY`:
  - Codex (`app/backend_codex.py` & `codex_review` in `app/mcp_stdio.py`): enforce `shell_environment_policy.exclude`, `analytics.enabled=false`, `feedback.enabled=false`, `check_for_update_on_startup=false`.
  - Claude (`app/provider_safety.py`): set `CLAUDE_ENV_FILE` to unset proxy vars inside Bash subshells and set `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_AUTOUPDATER=1`, `DISABLE_TELEMETRY=1`, `DISABLE_ERROR_REPORTING=1`.

## 4. Zero Idle / Night Quota Polling & Piggyback First
- Background loops (`_usage_snapshot_loop`) must run with `respect_idle=True`: **0** external HTTP/CLI requests while a provider has no running sessions or recent turn activity.
- Prefer zero-network piggyback (`RateLimitEvent` in `ClaudeBackend`, rollout `token_count.rate_limits` in `CodexBackend`) over active polling.
- Never read or exchange single-use OAuth `refresh_token`s in Python (`V-958`). Keep `_USAGE_CACHE_TTL >= 1800`s and `_USAGE_FAILURE_TTL >= 900`s.

## 5. Atomic Ban Circuit-Breaker Latch
- Route terminal/probe errors through `classify_and_trip_if_banned("<provider>", ...)`.
- Unambiguous ToS/account-disabled responses (`violation of terms of service`, `has been disabled in this account`, `account has been disabled`, `account_deactivated`) must atomically persist `set_provider_disabled(provider, True)` (`flock` + `fsync` + `os.replace` + SQLite KV), record a deduplicated critical incident, and never be masked by partial stream output or retried via `resume || fresh`.
- Never trip permanent provider disablement on `401` token expiry or `429` rate limits.

## 6. Verification Before Deploy
- Run `pytest tests/test_provider_safety_contract.py` plus the provider's focused backend/usage tests and `scripts/check_instruction_contract.py`.
