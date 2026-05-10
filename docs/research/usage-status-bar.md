# Research: Usage & Billing Data for Orchestra Status Bar

**Date**: 2026-05-10  
**Researcher**: usage-researcher agent

---

## 1. Anthropic OAuth Usage API (Subscription/Rate Limit)

### Endpoint
```
GET https://api.anthropic.com/api/oauth/usage
```

### Authentication
- **Bearer token** from `~/.claude/.credentials.json` → `claudeAiOauth.accessToken`
- Requires OAuth scope: `user:profile`
- Beta header: `anthropic-beta: oauth-2025-04-20`

### Live Response (Max 20x plan, 2026-05-10)
```json
{
  "five_hour": {
    "utilization": 24.0,
    "resets_at": "2026-05-10T16:20:00.995882+00:00"
  },
  "seven_day": {
    "utilization": 73.0,
    "resets_at": "2026-05-12T07:00:00.995907+00:00"
  },
  "seven_day_oauth_apps": null,
  "seven_day_opus": null,
  "seven_day_sonnet": {
    "utilization": 11.0,
    "resets_at": "2026-05-12T06:59:59.995927+00:00"
  },
  "seven_day_cowork": null,
  "seven_day_omelette": {
    "utilization": 0.0,
    "resets_at": null
  },
  "tangelo": null,
  "iguana_necktie": null,
  "omelette_promotional": null,
  "extra_usage": {
    "is_enabled": true,
    "monthly_limit": 20000,
    "used_credits": 0.0,
    "utilization": null,
    "currency": "USD"
  }
}
```

### Fields Breakdown

| Field | Description |
|-------|-------------|
| `five_hour.utilization` | Current 5-hour session usage % (0-100) |
| `five_hour.resets_at` | ISO timestamp when 5h window resets |
| `seven_day.utilization` | 7-day rolling all-model usage % (0-100) |
| `seven_day.resets_at` | When weekly window resets |
| `seven_day_opus` | Per-model Opus weekly cap (null if no Opus usage) |
| `seven_day_sonnet` | Per-model Sonnet weekly cap |
| `extra_usage.is_enabled` | Whether bonus credits are active |
| `extra_usage.monthly_limit` | Monthly limit in cents (20000 = $200) |
| `extra_usage.used_credits` | Credits used this month (in cents) |
| `extra_usage.currency` | Currency code |

### Token Resolution
```python
# From ~/.claude/.credentials.json
import json
from pathlib import Path

creds = json.loads(Path.home().joinpath('.claude/.credentials.json').read_text())
token = creds['claudeAiOauth']['accessToken']
plan_tier = creds['claudeAiOauth']['rateLimitTier']  # "default_claude_max_20x"
```

### Token Refresh
```python
import urllib.request, json

body = json.dumps({
    "grant_type": "refresh_token",
    "refresh_token": refresh_token,
}).encode("utf-8")

req = urllib.request.Request(
    "https://platform.claude.com/v1/oauth/token",
    data=body,
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    method="POST",
)
resp = urllib.request.urlopen(req, timeout=10)
new_token_data = json.loads(resp.read())  # has "access_token" key
```

---

## 2. Admin Usage & Cost API (Organization/API Key Billing)

### Endpoint: Usage Report
```
GET https://api.anthropic.com/v1/organizations/usage_report/messages
```

### Endpoint: Cost Report
```
GET https://api.anthropic.com/v1/organizations/cost_report
```

### Authentication
- **Admin API key** (`sk-ant-admin...`) — NOT OAuth token
- Header: `x-api-key: $ANTHROPIC_ADMIN_KEY`
- Header: `anthropic-version: 2023-06-01`

### Limitations
- **Only for API billing accounts** (organization-level)
- **Not available for individual subscription accounts** (Max plan)
- Requires admin role in the organization
- NOT what we need for Orchestra (we're on Max subscription)

### Query Parameters (Usage)
| Param | Description |
|-------|-------------|
| `starting_at` | ISO8601 start time |
| `ending_at` | ISO8601 end time |
| `bucket_width` | `1m`, `1h`, or `1d` |
| `group_by[]` | `model`, `workspace_id`, `api_key_id`, `service_tier`, `speed`, `inference_geo` |
| `models[]` | Filter by model |
| `api_key_ids[]` | Filter by API key |
| `workspace_ids[]` | Filter by workspace |
| `speeds[]` | Filter `standard`/`fast` (needs beta header) |

### Response includes per-bucket
- `input_tokens` (uncached)
- `input_cached_tokens`
- `cache_creation_tokens`
- `output_tokens`
- Has pagination: `has_more`, `next_page`

---

## 3. Claude Code's Built-in Status Bar

### How it works
Claude Code has a `statusLine` setting in `~/.claude/settings.json`:
```json
{
  "statusLine": {
    "command": "/usr/bin/python3 \"/home/maxim/.claude/claude-pulse/claude_status.py\""
  }
}
```

The CLI executes this command and renders its stdout as the bottom status bar. The command receives **stdin JSON** with session context:

### Stdin JSON from Claude Code (piped to status line command)
```json
{
  "data": {
    "model": {
      "id": "claude-opus-4-6",
      "display_name": "Claude Opus 4.6"
    },
    "context_window": {
      "used_percentage": 42.5,
      "total_input_tokens": 85000,
      "total_output_tokens": 12000,
      "context_window_size": 200000
    },
    "cost": {
      "total_cost_usd": 1.2345
    },
    "worktree": {
      "branch": "feat/my-feature",
      "name": "my-worktree"
    }
  }
}
```

### What claude-pulse shows
1. **Session bar** — 5-hour utilization % with countdown timer
2. **Weekly bar** — 7-day all-model utilization %
3. **Opus bar** — per-model weekly Opus cap (when present)
4. **Sonnet bar** — per-model weekly Sonnet cap (when present)
5. **Extra credits** — monthly spend vs limit (when enabled)
6. **Context window** — % of context used (from stdin)
7. **Model name** — active model (from stdin)
8. **Plan tier** — "Max 20x" (from credentials file)
9. **Effort level** — low/med/high/max
10. **Worktree branch** — active worktree name

### Data Sources Summary
| Info | Source |
|------|--------|
| Usage percentages | OAuth API `https://api.anthropic.com/api/oauth/usage` |
| Plan tier | `~/.claude/.credentials.json` → `rateLimitTier` |
| Context % | stdin from Claude Code CLI |
| Session cost | stdin from Claude Code CLI → `cost.total_cost_usd` |
| Model name | stdin from Claude Code CLI |

---

## 4. Claude Agent SDK — Per-Session Cost/Usage

### ResultMessage (end of query)
```python
@dataclass
class ResultMessage:
    total_cost_usd: float | None = None  # Session cost in USD
    usage: dict[str, Any] | None = None  # Token counts
    model_usage: dict[str, Any] | None = None  # Per-model breakdown
    duration_ms: int
    num_turns: int
```

### AssistantMessage (per-turn)
```python
@dataclass
class AssistantMessage:
    usage: dict[str, Any] | None = None  # Per-message token usage
```

### TaskUsage (for subagents)
```python
class TaskUsage(TypedDict):
    total_tokens: int
    tool_uses: int
    duration_ms: int
```

### RateLimitInfo (emitted on status change)
```python
@dataclass
class RateLimitInfo:
    status: Literal["allowed", "allowed_warning", "rejected"]
    resets_at: int | None = None
    rate_limit_type: Literal["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "overage"]
    utilization: float | None = None  # 0.0 - 1.0
```

### ContextUsageResponse (via client.get_context_usage())
```python
class ContextUsageResponse(TypedDict):
    categories: list[ContextUsageCategory]  # per-category breakdown
    totalTokens: int
    maxTokens: int
    rawMaxTokens: int
    percentage: float  # 0-100
    model: str
    apiUsage: dict[str, Any] | None  # cumulative API usage for session
```

---

## 5. Fallback: claude.ai Web API (scraping)

From `clawdbot` and the plasma widget, there's also a web API:
```
GET https://claude.ai/api/organizations/{orgId}/usage
```
- Auth: Cookie `sessionKey=sk-ant-...`
- First get orgId: `GET https://claude.ai/api/organizations`
- Returns same format as OAuth API (five_hour, seven_day, etc.)
- Used as fallback when OAuth token lacks `user:profile` scope

---

## 6. Recommended Approach for Orchestra Dashboard

### Global Status Bar (top of dashboard)

**Data source**: Call `https://api.anthropic.com/api/oauth/usage` directly from the Orchestra server.

```python
import json, urllib.request
from pathlib import Path

def fetch_subscription_usage() -> dict:
    """Fetch current subscription usage from Anthropic OAuth API."""
    creds_path = Path.home() / ".claude" / ".credentials.json"
    creds = json.loads(creds_path.read_text())
    token = creds["claudeAiOauth"]["accessToken"]
    
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())
```

**What to show**:
- 5-hour session bar with reset countdown
- 7-day all-model bar with reset date
- Per-model bars (Opus/Sonnet) when present
- Extra credits spent / monthly limit
- Plan tier badge ("Max 20x")

**Caching**: Cache for 60s (same as claude-pulse). The API supports polling once per minute.

### Per-Agent Cost Tracking

**Data source**: Already tracked via `ResultMessage.total_cost_usd` from SDK.

Orchestra already stores `cost_usd` per session. This is the virtual API-equivalent cost calculated by Claude Code CLI for each query response.

### Token Refresh Handling

The OAuth access token expires (see `expiresAt` in credentials). Implement refresh:
1. Check `expiresAt` before each API call
2. If expired, POST to `https://platform.claude.com/v1/oauth/token` with refresh_token
3. Use new access_token (don't write back to file — avoid race with Claude Code)

### Architecture

```
Orchestra Dashboard
├── /api/usage endpoint (new)
│   ├── Reads ~/.claude/.credentials.json (token + plan)
│   ├── Calls https://api.anthropic.com/api/oauth/usage
│   ├── Caches result for 60s
│   └── Returns merged data (subscription + per-agent costs from DB)
├── SSE stream (existing)
│   └── Push usage updates to frontend
└── Frontend component (new)
    ├── Global subscription bar (HTMX partial, auto-refresh 60s)
    └── Per-agent cost column (already exists)
```

### Important Notes

1. **No Admin API key needed** — The OAuth endpoint works with subscription credentials
2. **No token counting needed** — API returns utilization percentages directly
3. **Subscription vs API billing** — We're on Max 20x subscription. The Admin Usage/Cost API is for pay-per-token API accounts only
4. **Rate limiting** — The utilization % IS the rate limit. When `five_hour.utilization` hits 100%, new requests are rejected
5. **No per-session token breakdown from OAuth API** — It only gives aggregate windows. Per-session tokens come from the SDK's ResultMessage
6. **extra_usage.monthly_limit is in cents** — Divide by 100 for dollar amount ($200 = 20000)

---

## 7. stats-cache.json (Local Activity Stats)

Claude Code also maintains `~/.claude/stats-cache.json` with daily activity:
```json
{
  "version": 2,
  "lastComputedDate": "2026-03-19",
  "dailyActivity": [
    {
      "date": "2026-01-30",
      "messageCount": 1785,
      "sessionCount": 9,
      "toolCallCount": 375
    }
  ]
}
```
This is local-only activity counting (messages, sessions, tool calls per day). Not billing data, but useful for activity heatmaps.

---

## 8. Summary Table

| Need | API/Source | Auth | Latency |
|------|-----------|------|---------|
| Subscription usage % | `api.anthropic.com/api/oauth/usage` | OAuth Bearer | ~60s cache OK |
| Plan tier | `~/.claude/.credentials.json` | Local file | Instant |
| Per-session cost USD | SDK `ResultMessage.total_cost_usd` | Already tracked | Real-time |
| Per-session tokens | SDK `ResultMessage.usage` | Already tracked | Real-time |
| Context window % | SDK `get_context_usage()` | Session method | Real-time |
| Rate limit warnings | SDK `RateLimitEvent` | Session event | Real-time |
| Historical token usage | Admin API (org accounts only) | Admin key | 5min delay |
| Activity stats | `~/.claude/stats-cache.json` | Local file | Instant |
