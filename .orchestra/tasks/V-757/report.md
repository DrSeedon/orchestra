# V-757 — Claude Haiku 5.5

## Result

`haiku` now resolves to selectable `claude-haiku-5-5`; Haiku 4.5 is absent from the selectable registry, while its captured CLI output remains in the parser test as historical input. The registry sets a 1,000,000-token context and the base input/output rates. The model list, frontend color map, Telegram short name, session-switch test, and model catalog tests use Haiku 5.5. `model-routing.md` and `pipeline.yaml` were left unchanged as requested.

`claude-agent-sdk` moved from 0.2.114 to 0.2.164 in `pyproject.toml` and `uv.lock`. No other package versions changed. SDK 0.2.164 adds `jsonschema` as a dependency; that package was already present in the lock for another dependency. The project `exclude-newer` pin moved to 2026-10-07 to admit the SDK release. The SDK 0.2.164 source pins its bundled Claude CLI to 2.1.292. The bundled executable itself reports `2.1.292 (Claude Code)`. The system CLI reports `2.1.293 (Claude Code)`.

The app uses the system CLI in its normal Claude backend path: `ClaudeBackend._make_client()` sets `cli_path=shutil.which("claude") or ...` in `app/backend_claude.py`. The direct SDK probe below left `cli_path` unset, so it specifically exercised the bundled 2.1.292 binary. On that path, Haiku 5.5 returned the requested answer and appeared in `modelUsage`. It also reported `contextWindow: 200000`, despite Anthropic's model overview listing a 1M context window. The system CLI 2.1.293 was version-checked locally, but a separate model call through that binary was not made; the probe therefore does not establish the context reported by Orchestra's normal system-CLI path.

## Live SDK probe

One direct SDK query used model `claude-haiku-5-5` and prompt `Return exactly one word: HAIKU55_OK`. It returned `HAIKU55_OK`. The relevant output was:

```text
[claude-code:unrecognized_model] {"model":"claude-haiku-5-5","query_source":"sdk"}
{"bundled_cli_version": "2.1.292", "modelUsage": {"claude-haiku-4-5-20251001": {"cacheCreationInputTokens": 0, "cacheReadInputTokens": 0, "canonicalModel": "claude-haiku-4-5", "contextWindow": 200000, "costBasis": "list", "costUSD": 0.000973, "inputTokens": 903, "maxOutputTokens": 32000, "outputTokens": 14, "provider": "firstParty", "thinkingTokens": 0, "webSearchRequests": 0}, "claude-haiku-5-5": {"cacheCreationInputTokens": 9888, "cacheReadInputTokens": 0, "canonicalModel": "claude-haiku-5-5", "contextWindow": 200000, "costBasis": "unknown", "costUSD": 0.079332, "inputTokens": 2, "maxOutputTokens": 128000, "outputTokens": 11, "provider": "firstParty", "thinkingTokens": 0, "webSearchRequests": 0}}, "result": "HAIKU55_OK", "sdk_version": "0.2.164"}
```

The direct probe did not set Orchestra's `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`; its output includes both an `unrecognized_model` diagnostic and separate usage attributed to Haiku 4.5. The requested Haiku 5.5 call nevertheless completed. The model usage and context discrepancy are reported verbatim; the probe did not establish why the additional Haiku 4.5 usage appeared.

## Official model details and accounting limit

Anthropic lists API ID `claude-haiku-5-5`, a 1M-token context window, and 128K maximum output in its [models overview](https://platform.claude.com/docs/en/models/overview). Its [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) gives, per million tokens, $0.10 input and $0.50 output for prompts up to 100k tokens; prompts over 100k are $0.50 input and $2.50 output. The `ModelSpec` price fields are flat, so the registry stores the base $0.10/$0.50 rates and cannot encode the long-prompt tier. The UI and stored API-equivalent cost for prompts above 100k will therefore understate the official rate. The SDK's reported 200k context is also at odds with Anthropic's documented 1M and remains a limitation of the bundled CLI probe.

SDK release 0.2.164 records bundled CLI 2.1.292 in the [tagged SDK source](https://github.com/anthropics/claude-agent-sdk-python/blob/v0.2.164/src/claude_agent_sdk/_cli_version.py) and its [release changelog](https://github.com/anthropics/claude-agent-sdk-python/blob/v0.2.164/CHANGELOG.md). The installed system CLI was already 2.1.293 and is the binary selected by Orchestra's backend.

## Claude history pins

`CLAUDE_SDK_HISTORY_VERSION` now pins 0.2.164 and `CLAUDE_CLI_HISTORY_VERSION` pins the installed system CLI 2.1.293, which is what Orchestra passes to the SDK. The exact installed-version canary passed. The non-live backend, history renderer, resume, session, and SDK-importing tests passed. The focused pytest command deselected three live-probe cases by default; the installed-version canary was then run separately. The long semantic history-recall canary was not run as part of this task.

## Verification

The app imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-codex/app/__init__.py`.

The focused command covered all eight files found by `rg -l 'claude_agent_sdk' tests`, plus model registry, API, history, session, pipeline, and workflow tests:

```text
uv run --frozen python -m pytest -q \
  tests/test_backend_claude.py tests/test_backend_stream.py \
  tests/test_compact_gate_438.py tests/test_fd_adopt.py \
  tests/test_model_text_control_flow.py tests/test_rate_limit_capture_441.py \
  tests/test_session.py tests/test_subagent_routes.py \
  tests/test_native_history_import.py tests/test_runtime_history.py \
  tests/test_models.py tests/test_catalog_api.py tests/test_model_flags.py \
  tests/test_model_gates.py tests/test_pipeline.py tests/test_wf_run.py
536 passed, 3 deselected in 104.97s
```

`uv run --frozen python -m pytest -q -m live_probe tests/test_runtime_history.py::test_installed_claude_history_versions_match_pins` → `1 passed in 6.37s`. This canary checks installed versions only and does not make a model request. `uv lock --check` and `git diff --check` passed. The full pytest output is in `sdk-backend-tests-final.log`.

The first focused run had `535 passed, 1 failed, 3 deselected`: the old session-switch test still expected a 200k Haiku target. It now checks that 300k of existing Claude context fits Haiku 5.5's 1M catalog window, while the narrow 256k harness target still refuses the same handoff. The rerun above passed; the first output is retained in `sdk-backend-tests.log`.

No Orchestra restart was performed. The new registry and dependency take effect in the running Python service after the owner-authorized restart.
