# V-760 — model-specific Claude cache pricing

## Findings

Source search across `app/` found two cost calculators using `TOKEN_PRICES`: `ClaudeBackend._convert()` calculated each turn's `cost_usd_cached`, and `app/routes/system.py::_cost_cached_for()` recalculated the agent-cost dashboard from `sessions` token totals. `session_cost.py` accumulates the backend result, and session serialization persists that aggregate; neither contains another pricing formula. `usage_analytics.py` reads `turn_usage.cost_usd` as recorded and does not consult `TOKEN_PRICES`. Codex, Grok, and Harness use separate price paths and remain unchanged.

`turn_usage` stores one row per completed turn with its model and raw input, output, cache-read, and aggregate cache-create counts. Existing rows are not updated by this change. The CLI usage payload also provides the nested `cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens` counts. Live Claude's configured cache duration is one hour; the turn calculator now uses the split when present and treats legacy aggregate-only counts as 1h writes.

## Pricing source and implementation

Anthropic's [pricing table](https://platform.claude.com/docs/en/about-claude/pricing) lists 5m cache writes at 1.25× input, 1h writes at 2×, and cache reads at 0.1× by default. The same page specifies 0.025× reads for Fable 5.1, 0.05× for Opus 5.5 and Sonnet 5.5. Haiku 5.5 prompts over 100,000 tokens use rates 5× higher for input, both cache-write durations, cache reads, and output. For example, Haiku's base rates $0.10/$0.50 become $0.50/$2.50; its cache writes become $0.625/$1.00 and reads $0.05 per MTok. The rates were checked against the page's model table and prompt-cache section on 2026-10-08.

`ModelSpec` now stores the model-specific read multiplier, both write multipliers, and an optional prompt threshold/tier multiplier. `_token_prices_for()` projects those fields into the existing `TOKEN_PRICES` view. Proxy reconstruction preserves the declared metadata for exact selectable Claude IDs, so an enterprise model refresh does not reset Haiku's threshold or Fable/Opus/Sonnet cache-read rates. `calculate_cached_cost_usd()` is the shared formula used by backend turns and the dashboard.

Haiku's threshold is evaluated only from unique per-request `AssistantMessage.usage` records. `sessions` and `turn_usage` both aggregate API requests, so neither can reconstruct the prompt tier. The dashboard retains the backend's stored `sessions.cost_usd_cached` for tiered models and does not rewrite `turn_usage`. Existing session totals created before per-request costing remain at their stored estimate; their aggregate `turn_usage` rows cannot safely reconstruct the tier. No schema migration was needed.

## Acceptance calculations

The committed Sonnet 5.5 backend test supplies 100 input, 200 cache-read, 100 5m-write, 300 1h-write, and 500 output tokens. Manual pricing is `(100×2 + 200×2×0.05 + 100×2×1.25 + 300×2×2 + 500×10) / 1,000,000 = $0.00667`. The previous formula returns $0.00624.

The committed Haiku 5.5 backend test supplies a 100,031-token prompt: 100,001 input, 10 cache-read, and 20 1h-write tokens, with 30 output. Base cost is `(100001×0.10 + 10×0.10×0.1 + 20×0.10×2 + 30×0.50) / 1,000,000 = $0.0100192`; the >100k tier gives **$0.050096**. The previous formula gives $0.0100177. A separate test confirms that exactly 100,000 input tokens remains at base rates ($0.010015).

The dashboard test stores a 120k aggregate Haiku turn with backend-calculated `$0.012242` and confirms it is not multiplied by five; it also verifies the persisted `turn_usage.cost_usd` remains `$0.123`. The existing dashboard repricing test for flat-price models calculates cache-read and 1h-write components from registry metadata.

## Per-request tier follow-up

Using system Claude CLI `2.1.293`, one live Haiku 5.5 query made three separate `Read` tool calls. The CLI emitted 11 JSON events. The three tool-use assistant events shared message ID `msg_011Cfp4nehJu5kTXwsCHai3u` and identical usage; the final text assistant response had the distinct ID `msg_011Cfp4npUB8FnNJTLJVeC8p` and its own usage. Thus content-block events for one assistant response must be deduplicated by `message_id`. The exact stdout is attached unmodified in [haiku-multi-tool-cli.json](haiku-multi-tool-cli.json); stderr is in [haiku-multi-tool-cli.stderr](haiku-multi-tool-cli.stderr).

Probe command:

```text
DISABLE_NON_ESSENTIAL_MODEL_CALLS=1 claude -p --model claude-haiku-5-5 --tools Read --allowedTools Read --permission-mode dontAsk --no-session-persistence --output-format json --verbose 'Use exactly three separate Read tool calls: read lines 1-20 from app/models.py, lines 1-20 from pyproject.toml, and lines 1-20 from .orchestra/tasks/V-760/report.md. Do not call any other tools. Then return only the three file names and the number of lines read from each.'
```

The two unique assistant usages from the raw CLI output were:

```json
{"message_id":"msg_011Cfp4nehJu5kTXwsCHai3u","model":"claude-haiku-5-5","usage":{"input_tokens":2,"cache_creation_input_tokens":9387,"cache_read_input_tokens":3756,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":9387},"output_tokens":4}}
{"message_id":"msg_011Cfp4npUB8FnNJTLJVeC8p","model":"claude-haiku-5-5","usage":{"input_tokens":2,"cache_creation_input_tokens":2318,"cache_read_input_tokens":13143,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":2318},"output_tokens":1}}
```

`ResultMessage.usage` reported aggregate `input_tokens=4`, `output_tokens=484`, `cache_read_input_tokens=16899`, and `cache_creation_input_tokens=11705`; its `iterations` array had just one row, with `input_tokens=2`, `output_tokens=57`, `cache_read_input_tokens=13143`, and `cache_creation_input_tokens=2318`. The unique assistant records' input/cache totals match the result, but their output total is 5 rather than 484. The turn calculator therefore verifies per-request prompt totals separately from output totals: when prompt totals reconcile but output does not, it prices input/cache components per request and applies the common base output rate to the aggregate output. It applies Haiku's tier to output only if per-request outputs also reconcile. If prompt totals are absent/incomplete, it prices the aggregate at base rates and sets `price_may_be_understated=true` when a >100k prompt is possible; the session's durable turn-end status logs “цена API-эквивалента может быть занижена”. This live turn's two prompts were 13,145 and 15,463 tokens, below the tier threshold, and the reconstructed cached API-equivalent price matches the CLI's `costUSD=0.0027523900000000004`.

The new regression turn has two unique 60k-token Haiku requests and a Result aggregate of 120k input tokens. The first assistant response is represented twice with the same message ID to cover CLI block events. The test makes Result output exceed the sum of per-request outputs (as in the live probe); cost is $0.012242 at base rates, not the $0.06121 produced by applying the tier to the aggregate. A separate high-prompt test with unreconciled output applies the tier to known input/cache components, leaves output at base rates, and sets the uncertainty flag. Another regression verifies that a 120k aggregate with no per-request usage falls back to base cost ($0.01202) and sets the uncertainty flag. That flag is exposed in the durable `turn ended` log as `[price_may_be_understated]`; the status-log test checks the marker when true and its absence when false.

## Verification

The app imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-codex/app/__init__.py`.

All 15 pricing/session test files were run, covering the 13 test files found with `rg -l 'TOKEN_PRICES|cost_usd_cached' tests --glob '*.py'`, plus the turn-end status and session lifecycle tests:

```text
uv run --frozen python -m pytest -q \
  tests/test_backend_claude.py tests/test_backend_codex.py \
  tests/test_backend_grok.py tests/test_backend_routing.py \
  tests/test_cache_tokens.py tests/test_catalog_api.py \
  tests/test_model_catalog.py tests/test_model_flags.py \
  tests/test_model_gates.py tests/test_model_registry_503.py \
  tests/test_models.py tests/test_p4_cost.py tests/test_session.py \
  tests/test_toggle_live_agent.py tests/test_turn_ended_no_quota_suffix.py
575 passed in 50.94s
```

The full output is in [pricing-tests-final5.log](pricing-tests-final5.log). `git diff --check` passed. No `turn_usage` records were rewritten and no Orchestra restart was performed.
