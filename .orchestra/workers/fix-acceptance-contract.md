# fix-acceptance-contract

- Acceptance commands are stored as text but executed as one `shell=False` argv; validate shell control tokens both when persisting and immediately before merge execution so legacy rows cannot bypass the contract.
- In the MCP `task_update` tool, ordinary text fields retain `""` = unchanged; only `acceptance_command` uses `None` = omitted and `""` = explicit clear.
