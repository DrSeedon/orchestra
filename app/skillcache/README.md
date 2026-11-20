# SkillCache v1

The same runner serves the Orchestra MCP, the local CLI, and the Kesha SDK and
stdio MCP bridge. Capsule execution is opt-in. A manifest selects only reviewed
read-only operations. It cannot name commands, credentials, source URLs, or
workspace paths. Unavailable, revoked, stale, and failed verification statuses
lead back to the original skill.

## Provisioning

Point `ORCHESTRA_SKILLCACHE_CONFIG` to a mode-0600 file owned by the server user.
The file has three top-level keys.

- `private_dir` is an absolute, owner-only directory for expiring run reports
  and state. The registry stores references and request MACs in Orchestra's DB.
- `scopes` maps a scope to its approved skill names. A skill entry has
  `skill_path`, optional `scripts` for transitive dependency paths, and optional
  `mcp_schema_paths` for the normalized input/output schema exports or digest files.
  For Kesha, point `KESHA_SKILLCACHE_SCHEMA_DIR` at a mode-0700 directory. The
  launcher updates the per-server files when `tools/list` returns. The digests
  cover the transformed input, upstream output, and transformed output schema.
  Configure one canonical schema publisher for each directory if multiple
  runtime profiles publish different schema shapes.
- `grants` maps a host-owned principal such as `orchestra:<session-id>` or
  `kesha:<chat-id>` to a scope, a `skills` list, a `bindings` map by skill,
  and a `sources` map. Scope, principal, source configuration, and workspace
  bindings are never accepted from the model.

Set `ORCHESTRA_SKILLCACHE_RECEIPT_KEY` in the service environment. The Kesha
callback uses a separate shared key, `ORCHESTRA_SKILLCACHE_KESHA_KEY` on Orchestra
and `KESHA_SKILLCACHE_KEY` on Kesha. Both keys must have at least 32 bytes.
`KESHA_SKILLCACHE_TRACE_DB` opts in to an owner-private metadata-only journal.

Source configuration depends on the granted operation.

- Mail needs `bindings.kesha-mail.sources` set to `["mailru","gmail"]` plus
  `mailru_user`, `mailru_password_env`, and `gmail_access_token_env` in sources.
  The configured environment variable names point to credentials. Provision a
  Gmail read-only OAuth access token through the host.
- Direct needs `direct_access_token_env` and a `direct` map containing approved
  `campaigns`, `goals`, `attributions`, `currency`, and `timezone`. Currency
  and timezone are properties of the provisioned account. The adapter validates
  the campaign, date and goal/attribution columns, then compares daily data with
  a separately requested period total.
- Sleep uses `wellness_root`, the root containing the synchronized `sleep-log`
  and `activity-log` directories. The skill key is `wellness-dashboard`.
- CDP uses `cdp_pages`, a map of approved page keys to URLs, and a Playwright
  Chromium installation accessible to the service. Select read-only page
  targets. The browser uses an isolated headless context.

After initializing the isolated/service DB, run
`.venv/bin/python scripts/orch-capsule-run qualify --scope <scope> --skill <skill>`
as the host operator. The qualification subprocess requires Linux and libseccomp.
It has synthetic fixture sources and denies file opening, network, and process
creation syscalls before replay. Successful qualification records baseline,
changed-input and stale-output cases. Requalification is explicit after changes.

The MCP takes one object named `request`. The local CLI reads the same JSON from
stdin under `orch-capsule-run run` or `continue`. A CLI caller needs the trusted
`ORCHESTRA_SESSION_ID` and `ORCHESTRA_MCP_PROOF` channel. Use the MCP when those
credentials are only available inside the harness MCP subprocess. For each
transition supply a unique `request_id`. A continuation includes `run_id`,
`revision` and only the requested `bindings`. After a lease expires, recovery
can repeat read operations from the last committed revision.

