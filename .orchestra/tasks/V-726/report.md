# V-726 — Codex CLI update and GPT-6.1 Sol

## Result

| Requirement | Result | Evidence |
|---|---|---|
| Update Codex CLI through its existing installer | Done | Before: global npm `@openai/codex@0.156.1`, `/usr/bin/codex` → `/usr/lib/node_modules/@openai/codex/bin/codex.js`. npm latest tag at the update was `0.160.0`. Updated outside the Orchestra cgroup with `ssh -o BatchMode=yes kesha@localhost 'sudo -n npm install -g @openai/codex@latest'`; output: `changed 2 packages in 25s`. After: `codex-cli 0.160.0`, npm global package `@openai/codex@0.160.0`. |
| Check model list and run one-word inference | GPT-6.1 Sol available | `codex app-server` `model/list` with `includeHidden:false` listed `gpt-6.1-sol` as visible and default. Full response is `evidence/model-list-default.json`. The app-server list is a catalog rather than an account entitlement check in OpenAI's sign-in-with-ChatGPT documentation; the actual inference probe below confirmed this account can use the model. |
| One-word `codex exec` probe | Passed | Command: `codex exec --ephemeral --sandbox read-only --color never -m gpt-6.1-sol --output-last-message .orchestra/tasks/V-726/evidence/codex-exec-gpt-6.1-sol.txt 'Reply with exactly one word: yes.'` Exit 0; final message file contains `yes`. CLI reported model `gpt-6.1-sol`, provider `openai`, and 4,440 tokens used. This was the only inference request. |
| History compatibility and pin | Compatible; pin updated | CLI 0.160.0 accepted a synthetic history made by `render_codex_history()` on a separate, isolated `CODEX_HOME`: `thread/resume` returned no error, `cliVersion=0.160.0`, `preview=synthetic history format probe`, `status=idle`, and `historyMode=paginated`; the isolated rollout contains the synthetic user message. No live thread was resumed. `CODEX_CLI_HISTORY_VERSION` and the mocked version-acceptance test now use 0.160.0. Evidence summary: `evidence/history-format-0.160.0.json`. |
| V-723 | Ready for owner-run measurement | GPT-6.1 Sol is listed and completed an inference under this account. |

## Exact probe outputs

Relevant `model/list` fields (full raw response at `evidence/model-list-default.json`):

```json
{"displayName":"GPT-6.1-Sol","hidden":false,"id":"gpt-6.1-sol","isDefault":true,"model":"gpt-6.1-sol"}
```

The `codex exec` final-message output file contains the exact one-word response:

```text
yes
```

The history-probe summary is recorded verbatim in `evidence/history-format-0.160.0.json`; `thread/resume` returned no error and stored the synthetic input in the isolated rollout. It reported `historyMode=paginated`.

Official OpenAI documentation lists `gpt-6.1-sol` for Codex CLI and says availability depends on account/client rollout: [Models](https://learn.chatgpt.com/docs/models). Its app-server page cautions that `model/list` may return a bundled catalog rather than confirm entitlement; a successful inference verifies access for that request: [Codex app-server sign-in](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server). The documented npm update route is `npm install -g @openai/codex@latest`: [Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex).

## Process and restart boundaries

The service account is `kesha`; the system-installed npm package is owned by `root:root`. Four existing `codex` processes were present before updating (PIDs 3807986, 3810654, 3811641, 3813517). They were not signaled, changed, or restarted. Orchestra was not restarted. The full isolated history-probe `CODEX_HOME` remains on disk for evidence; its generated runtime databases are excluded from Git by this task's evidence-local `.gitignore`, while the concise probe result and full model-list response are tracked.

## Tests

`/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_backend_codex.py::test_history_import_accepts_verified_0160_0_pin -q` → `1 passed`. The pin check uses a mocked `--version` response. No real Codex CLI call was run by pytest; CLI probes above were separate, explicit task steps. No apt, `needrestart`, or Orchestra restart command was run.

Mutation check: changing the pin back to 0.156.1 made this committed test fail with `NativeHistoryUnsupported: native Codex history requires CLI 0.156.1, got codex-cli 0.160.0`; restoring 0.160.0 returned it to `1 passed`.
