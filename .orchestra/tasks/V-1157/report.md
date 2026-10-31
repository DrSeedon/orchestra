# V-1157 — Codex app-server model metadata

**Outcome.** Installed Codex CLI reports `codex-cli 0.166.0`; `/usr/bin/codex` resolves to the installed Node launcher. An app-server protocol `initialize` followed by one `model/list` page succeeded against a one-shot local app-server process. The already-running CLI app-server was observed but not restarted or contacted. Auth kind is `chatgpt_account` from the `auth_mode` discriminator only; account identity and credential values were not emitted or saved.

| Check | Actual | Coverage / result |
|---|---|---|
| `gpt-6.1-terra` catalog support | Present; exact `id` and `model` are `gpt-6.1-terra`; `hidden=false`, `isDefault=false` | `includeHidden=true`, page limit 200; one page, 10 model records, `nextCursor=null`; pagination complete |
| Default reasoning effort | `low` | Returned by model/list |
| Supported reasoning efforts | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` | Returned by model/list |
| Context window / effective budget | Not returned | Neither field exists on the Terra model/list record or its generated schema; unknown, not inferred |
| Inference / usable turn | Not tested | No thread, turn, or provider inference request made |
| Managed daemon version query | Red: exit 1, control socket absent | Exact stderr is in private evidence; no daemon was started |
| `model/list` protocol query | Pass | Initialize succeeded; exact request and response retained locally |

**Evidence.** Raw request, response, stderr, generated app-server schema, and safe CLI/auth/process metadata are in `.orchestra/private/V-1157/` (`model-list.input.raw.json`, `model-list.output.raw.json`, `model-list.stderr.raw.txt`, `schema/`, `codex-version.raw.txt`, `executable-realpath.txt`, `auth-kind.safe.json`, `active-cli-processes.safe.json`, `daemon-version.stderr`). Schema generation exited 0. The model/list stderr notes that Codex used its bundled bubblewrap because `bubblewrap` was absent from PATH; the query still completed. Raw files are local and ignored; no credentials or account identity are included in the tracked report.

**Limits.** This establishes metadata exposed by the installed CLI catalog, not inference access, effective context length, or an account entitlement beyond the returned `hidden` and catalog fields. No configuration, auth, installed version, service, or live CLI process was changed. No tests were run (metadata-only task).
