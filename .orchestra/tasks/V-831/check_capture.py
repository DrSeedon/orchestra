"""Feed a real CLI stream-json capture through ClaudeBackend._convert (V-831)."""
import json, sys
from claude_agent_sdk._internal.message_parser import parse_message
from app.backend_claude import ClaudeBackend

b = ClaudeBackend(model="claude-haiku-5-5", cwd="/tmp")
live, final, thinking, thinking_final = {}, {}, "", ""
for line in open(sys.argv[1]):
    try:
        msg = parse_message(json.loads(line))
    except Exception:
        continue
    if msg is None:
        continue
    for ev in b._convert(msg):
        if ev.type == "tool_input_stream":
            live.setdefault(ev.metadata["tool_use_id"], []).append(ev.content)
        elif ev.type == "tool_use":
            final[ev.metadata["tool_use_id"]] = ev.content.split(": ", 1)[1]
        elif ev.type == "thinking_stream":
            thinking += ev.content
        elif ev.type == "thinking":
            thinking_final += ev.content
for tid, parts in live.items():
    print(tid, "deltas:", len(parts), "chars:", sum(map(len, parts)),
          "equal_to_final:", json.loads("".join(parts)) == json.loads(final[tid]))
print("thinking streamed chars:", len(thinking), "final chars:", len(thinking_final),
      "equal:", thinking == thinking_final)
