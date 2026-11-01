# V-1066

- Route fully composed messages over the hub field limit through a checksum-named UTF-8 file in the existing private workspace; send a short instruction to read it in full. Keep the message and attachment intact, subject to the existing secret/history guard and 20 MiB workspace file bound.
- Cover first/resumed/fallback turns, live and pending steers, and safe no-work retries. Exclude transport files in both workspace directions, retain them until workspace release, and verify publication atomically before any MCP submission.
- Preserve thread identity on invalid parameters, uncertain sends and failed replacement launches. Acknowledge pending steers only after a confirmed run; retain newly arriving steers.
- No deployment, restart, live recovery, provider call, auth change or changes to another project.
