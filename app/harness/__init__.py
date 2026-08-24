"""Orchestra own agent harness — process-light, no daemon, OpenRouter-native.

A persistent in-process BackendLike object runs an OpenAI-format agent loop over
OpenRouter (httpx streaming), executes own
tools (bash/read/write/grep/glob) + MCP tools, and yields AgentEvents. Zero
background processes between turns — the cumulative cost lives in the object.
"""
