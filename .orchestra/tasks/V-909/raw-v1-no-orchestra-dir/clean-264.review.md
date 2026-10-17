## Summary

Reviewed the complete requested diff between `8730552` and `e8f84bc`. The `.mcp.json` removal addresses the reported Grok name collision, and the revised check matches the observed Grok 1.0.3 notifications. One isolation gap remains in the new check.

## Findings

### Blocking

- **Same-name MCP substitution can pass conformance when Grok omits server identities.** In [backend_grok.py](/home/kesha/v909-work/v909-clean-264-24htdzpl/app/backend_grok.py:419), an expected server with no reported identity is accepted. The loaded-server count at lines 427–430 only compares totals, while readiness is inferred from a name in `server_status` at lines 684–691. A foreign server replacing `orchestra` under that name would have the expected count and could report ready with tools, passing the gate. Since the report notes this path has previously exposed third-party credentials, the launch should refuse when it cannot establish the expected server identity, or use an authenticated handshake that verifies it.

### Suggestion

- **The mutation script can delete an existing `.mcp.json`.** [mutation_check.py](/home/kesha/v909-work/v909-clean-264-24htdzpl/docs/tasks/264/mutation_check.py:54) overwrites the file, then unconditionally unlinks it at line 57. If run in a checkout where that file already exists, it destroys its prior contents. Preserve and restore the original file, or refuse to run when it exists.

## Verdict

NEEDS WORK — the missing identity check leaves a same-name substitution path through the MCP isolation gate.