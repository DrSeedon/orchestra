# fix-compact-95

- Claude SDK `autoCompactThreshold` is a token count, not a percentage; convert it using the current `max_tokens` before applying a percentage gate.
- Keep compact prompt requirements in a source-owned helper so tests can build the exact prompt and extract the required phrase from that source.
