"""Capture SDKPartialAssistantMessage (StreamEvent) shapes from claude-agent-sdk.

Run: UV_CACHE_DIR=/tmp/uv-cache uv run python docs/tasks/83/capture_partial.py
Writes a sample dump to docs/tasks/83/partial_dump.jsonl
"""
import asyncio
import json
import os
import shutil
import time
from collections import Counter

from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions, StreamEvent,
    AssistantMessage, ResultMessage,
)

OUT = os.path.join(os.path.dirname(__file__), "partial_dump.jsonl")


async def main():
    cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
    env = {}
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
    env["DISABLE_TELEMETRY"] = "1"

    options = ClaudeAgentOptions(
        model="claude-haiku-4-5-20251001",
        cwd=os.getcwd(),
        cli_path=cli,
        permission_mode="default",
        include_partial_messages=True,   # ← the flag under test
        max_turns=1,
        env=env,
        system_prompt={"type": "preset", "preset": "claude_code"},
    )

    client = ClaudeSDKClient(options=options)
    await client.connect()

    # A prompt long enough to produce many text deltas; measure streaming cadence.
    await client.query(
        "Count slowly from 1 to 30, one number per line, with a short word after each. "
        "Do not use any tools."
    )

    event_types = Counter()       # inner Anthropic event['type']
    sdk_types = Counter()         # SDK message class names
    samples = {}                  # first sample of each inner event type
    n_partial = 0
    first_t = None
    last_t = None
    text_deltas = 0
    text_chars = 0

    f = open(OUT, "w")
    try:
        async for msg in client.receive_messages():
            now = time.monotonic()
            cls = type(msg).__name__
            sdk_types[cls] += 1

            if isinstance(msg, StreamEvent):
                n_partial += 1
                if first_t is None:
                    first_t = now
                last_t = now
                ev = msg.event or {}
                etype = ev.get("type", "?")
                event_types[etype] += 1
                rec = {
                    "sdk_class": cls,
                    "uuid": msg.uuid,
                    "session_id": msg.session_id,
                    "parent_tool_use_id": msg.parent_tool_use_id,
                    "event": ev,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if etype not in samples:
                    samples[etype] = rec
                # measure text delta cadence
                if etype == "content_block_delta":
                    delta = ev.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text_deltas += 1
                        text_chars += len(delta.get("text", ""))

            elif isinstance(msg, AssistantMessage):
                # full assembled message — what Orchestra uses today
                f.write(json.dumps({"sdk_class": cls, "blocks": [type(b).__name__ for b in msg.content]}) + "\n")

            elif isinstance(msg, ResultMessage):
                break
    finally:
        f.close()
        await client.disconnect()

    print("=== SDK message class counts ===")
    for k, v in sdk_types.most_common():
        print(f"  {k}: {v}")
    print("\n=== StreamEvent inner event['type'] counts ===")
    for k, v in event_types.most_common():
        print(f"  {k}: {v}")
    print(f"\nTotal StreamEvents: {n_partial}")
    print(f"text_delta events: {text_deltas}, total chars: {text_chars}")
    if text_deltas:
        print(f"avg chars/delta: {text_chars/text_deltas:.1f}")
    if first_t and last_t and last_t > first_t and text_deltas:
        span = last_t - first_t
        print(f"stream span: {span:.2f}s, deltas/sec: {text_deltas/span:.1f}")
    print("\n=== One sample of each inner event type ===")
    for k, rec in samples.items():
        print(f"\n--- {k} ---")
        print(json.dumps(rec, ensure_ascii=False, indent=2)[:1200])
    print(f"\nFull dump: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
