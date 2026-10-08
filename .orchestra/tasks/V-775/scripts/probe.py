"""V-775 probe: does prompt caching work with no console switch? tiny cost."""
import os, sys, json
from pathlib import Path
import anthropic
for l in Path("/home/kesha/orchestra/.env").read_text().splitlines():
    if l.startswith("ORCHESTRA_CLAUDE_CREDIT_API_KEY="):
        key = l.split("=", 1)[1].strip().strip('"\'')
c = anthropic.Anthropic(api_key=key)
sysmsg = "You are a terse assistant. " + ("Reference text about nothing in particular. " * 400)
for i in range(2):
    r = c.messages.create(model="claude-haiku-5-5", max_tokens=20, system=sysmsg,
        messages=[{"role": "user", "content": "Say ok."}], extra_body={"cache_control": {"type": "ephemeral"}})
    u = r.usage
    print(i, "in", u.input_tokens, "cw", u.cache_creation_input_tokens, "cr", u.cache_read_input_tokens, "out", u.output_tokens)
