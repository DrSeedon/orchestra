## Summary

The argv-removal architecture is sound, and the quick pre-filter is a genuine superset of `_NAMED` for every `_SECRET_WORDS` entry, including `API_KEY`, `APIKEY`, and `PRIVATE_KEY`. I found four blocking issues: two masking bypasses and two config lifecycle/construction hazards.

## Findings

blocking: app/secret_mask.py:42 — quoted values terminate at the first quote even when it is escaped, so serialized JSON such as a secret containing `\"` masks only the prefix and leaves the remainder visible → parse escaped quoted forms with patterns such as `(?:\\.|[^"\\\r\n])*` and the single-quote equivalent; add tests where sensitive material continues after an escaped quote.

blocking: app/secret_mask.py:44 — bare values stop at `;`, although cookies and connection strings explicitly belong to the covered classes and commonly contain semicolons; only the first segment is masked and later segments remain visible → do not treat `;` as a universal bare-value delimiter, or introduce form-specific handling that masks the complete cookie/connection-string value; test multi-segment cookie and DSN forms.

blocking: app/backend_codex.py:1622 — MCP server names and environment keys are interpolated into TOML table/key syntax without quoting or validation, while custom MCP configuration is caller-supplied; punctuation, newlines, or TOML syntax can corrupt the generated config, inject fields, or prevent Codex from starting → serialize dynamic keys as quoted TOML keys, reject control characters, and escape all TOML string control characters rather than only backslashes and quotes.

blocking: app/backend_claude.py:212 — the config filename is stable per session, so an older backend’s `disconnect()` can unlink a newer reconnect’s config after both instances used the same path; subsequent MCP restarts then lose their configuration → give every backend instance a unique private filename, or remove the file only after verifying that it is still the inode/version written by that instance.

suggestion: app/backend_codex.py:1684 — concurrent `_prepare_codex_home()` calls can race between checking, unlinking/rmdir, and recreating `sessions`, producing `FileNotFoundError` or `FileExistsError`; config writing also exposes a temporarily truncated file → make preparation idempotent under concurrency and write `config.toml` through a private temporary file followed by atomic `os.replace()`.

suggestion: app/backend_codex.py:1655 — the empty-MCP branch deliberately returns the shared base home, which also restores every globally configured MCP server if such a backend is ever constructed outside the normal manager path → keep the per-agent-home invariant fail-closed, or assert that Orchestra-managed Codex backends can never reach this branch.

## Verdict

Not approved. The masking bypasses can leave portions of secrets in logs/SSE, and the TOML/config lifecycle issues can corrupt or silently remove runtime configuration.

## Round (2026-08-12T11:41:04Z)

## Re-review status

- FIXED — escaped quotes are now consumed inside the quoted value, preventing suffix leakage.
- FIXED — semicolons no longer truncate bare cookie/connection-string values.
- STILL BROKEN — TOML injection is closed, but hostile TOML input can still make the generated config unparsable.
- FIXED — per-instance Claude filenames prevent an older disconnect from deleting a newer backend’s config.

## New findings

blocking: app/backend_codex.py:1605 — `_toml_str()` escapes characters below U+0020 but leaves U+007F unchanged; TOML forbids DEL, and `tomllib.loads()` rejects a server name, env key, or value containing it, so caller-supplied MCP data can still crash Codex startup → escape U+007F as `\\u007f` too and add it to the hostile-input test.

suggestion: app/secret_mask.py:44 — removing `;` globally means a shell-style line such as `TOKEN=<value>; next-command` includes the semicolon in the masked value, slightly corrupting diagnostic text → document this deliberate ambiguity or add form-specific handling if preserving shell separators matters.

suggestion: app/backend_claude.py:188 — unique filenames safely fix reconnect races, but configs survive indefinitely when a process dies before `disconnect()` → add bounded stale-file cleanup during directory preparation, based on age and excluding the current instance.

## Verdict

Not approved: one blocking malformed-input startup failure remains. The other three round-one blockers are closed, and the focused suites pass: 52 tests.

## Round (2026-08-12T11:44:08Z)

## Re-review status

- Escaped quoted-value leakage — FIXED.
- Bare semicolon leakage — FIXED.
- TOML key injection — FIXED.
- U+007F/C1 TOML failure — FIXED. U+009F is escaped; U+00A0 is intentionally preserved and parses correctly.
- Claude reconnect filename collision — FIXED.
- Atomic private config writes — FIXED.
- Shared-home residual risk — documented and unreachable through the managed path.
- Stale Claude config cleanup — NEW BUG.

## New findings

blocking: app/backend_claude.py:76 — the sweep deletes every config older than 24 hours except the newly starting backend’s own filename; it has no knowledge of other live backends. A Claude connection can remain live for days, so any agent preparing a config after that threshold can delete another live agent’s config. If that runtime later restarts its MCP server, its required config is gone → do not sweep by age alone; track active paths centrally, refresh a lease, verify owning process/session liveness, or defer cleanup to service startup when no backends are active.

suggestion: app/backend_codex.py:1607 — lone UTF-16 surrogate code points from caller-supplied JSON remain unescaped and cause UTF-8 file writing to raise `UnicodeEncodeError` → explicitly reject surrogate code points with a clear validation error, or serialize them using a TOML-safe strategy.

## Verdict

Not approved. One blocking issue remains at the three-round ceiling: stale cleanup can delete another agent’s live Claude MCP configuration. All previously identified masking and TOML boundary vulnerabilities are fixed.
