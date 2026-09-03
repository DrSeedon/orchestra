# #240 architecture/config snapshot — 2026-08-23

## Production process

Read-only evidence from `systemctl`, `/proc`, the live session row, and the installed CLI:

```text
host=maxim-911aird
orchestra MainPID=2598034
orchestra ExecStart=/mnt/data/Projects/Python/orchestra/.venv/bin/python3 -u -m uvicorn app.main:app --fd 3
session id=1d0fc38f-23b6-4152-a1d4-a95c479abb86
session name=research-codex-latency
session model=gpt-5.6-sol role=full-cycle effort=xhigh backend_type=codex
thread=01a02e52-e1dd-7ad0-9fa6-dc2a64b055f8

node argv=node /home/maxim/.npm-global/bin/codex -c model_reasoning_effort="xhigh" -c features.multi_agent=false -c web_search="live" app-server --stdio
native argv=/home/maxim/.npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex -c model_reasoning_effort="xhigh" -c features.multi_agent=false -c web_search="live" app-server --stdio
native sha256=bbc3341e44c9ead340ed9570c17be936e37870f570751a941699ffd04d672827
CLI=codex-cli 0.149.0
```

`/home/maxim/.local/bin/codex` used by all benchmark arms is a 274-byte launcher that sources
the proxy client environment and `exec`s `/home/maxim/.npm-global/bin/codex`. Both report
`codex-cli 0.149.0`; therefore the provider executable/package is the same while the benchmark
keeps the standalone launcher behavior.

## Code call path

```text
AgentSession._make_backend
  app/session.py:791-837
    -> build_backend(runtime="codex", BackendBuildContext)
      -> _codex_factory
         app/runtime_registry.py:205-265
         -> CodexBackend(... system_prompt, resume_thread_id, MCP, effort)
           app/backend_codex.py:753-817
           -> asyncio.create_subprocess_exec(codex ... app-server --stdio)
              app/backend_codex.py:960-1079, 2230-2245
           -> initialize / initialized / thread/start or thread/resume
              app/backend_codex.py:1033-1079
           -> turn/start
              app/backend_codex.py:1096-1134
           -> JsonRpcStdioTransport._request/_write: newline JSON on stdio
              app/backend_jsonrpc.py:399-427
```

Repository search:

```text
rg "codex-sdk|openai.*codex|from openai|import openai" app pyproject.toml uv.lock
app/static/js/utils.js:79: UI label only
pyproject.toml: no Python OpenAI/Codex SDK dependency; claude-agent-sdk==0.2.114 is the only agent SDK
```

Verdict: production uses the installed Codex CLI app-server over Orchestra's Python JSON-RPC
stdio transport. It does not use a Python Codex SDK.

## Live managed configuration

```text
CODEX_HOME=/home/maxim/.orchestra/codex-home/1d0fc38f-23b6-4152-a1d4-a95c479abb86
config bytes=1757
config sha256=a444e8e4ef12472fd49a33156881cbce9fcd4728464f2b45e62b64378bcee5c6
project_doc_max_bytes=262144
model_context_window=872000
model_auto_compact_token_limit=784800
service_tier=<absent>
model_reasoning_effort=<absent; argv pins xhigh>
MCP servers=orchestra
enabled Orchestra tools=41
```

Model-visible static surfaces measured in a fresh interpreter:

```text
full-cycle role prompt=58188 bytes sha256=5e2be0dffc0c0f55ab3ae2fd6bb4913a3f91392b1ccc514b53ffb417f150190f
AGENTS.md=104615 bytes sha256=b21dc5d2a62561bacdab3ae744da3697138c20655f0644128c4e1f8904b70eea
project skills=40662 bytes (28399 codex-debate + 12263 html-artifacts)
Orchestra tools/list payload=41 tools, 32634 bytes by name+description+inputSchema+outputSchema
effective model window reported by app-server=828400 tokens
```

`AGENTS.md` is below the live 262144-byte cap; truncation did not occur in #240.

## Proxy identity

The shell, systemd MainPID, Node launcher, and native app-server had identical values:

```text
HTTPS_PROXY=http://127.0.0.1:12339 sha256=d2e39d68e15f1595dd7f8e0f5cd61eb35e627af613bdf0199f1290faeca9131a
HTTP_PROXY=http://127.0.0.1:12339 sha256=d2e39d68e15f1595dd7f8e0f5cd61eb35e627af613bdf0199f1290faeca9131a
NO_PROXY sha256=8464661ed438080491995e2c5377b21e75c6a5e57e55a221dd24108d6963a274
```

The standalone launcher's `client.env` produced the same three hashes, so the matched arms and
the production child used the same proxy route.
