# V-1066 — DONE (implementation; integration belongs to the platform)

The composed hub input now reaches the same existing worker/thread intact through the existing SSH workspace transport when it exceeds the message field limit. The attachment limit remains 65,536 UTF-8 bytes. No instructions or attachment are shortened. The repository CHANGELOG and this task's CHANGELOG are updated.

## Cause and evidence boundary

`mcp_stdio.send_message` reads at most 65,536 bytes of UTF-8 text, appends its header and full content, and submits that combined message to durable delivery. `AgentSession.send` can prepend refreshed role instructions/context and a conversation handoff. `HubBackend._prompt` then joins pending steers and the message and adds the first-turn preamble or resumed uv instructions. The hub constructor's `system_prompt` argument was already unused by the trimmed hub design; this fix transports the actual outbound composition without changing prompt policy.

There was no transport for a fully composed message beyond the hub's 120,000-character field validation. `_start` treated every nonretryable `MultiCodeError`, including JSON-RPC invalid parameters (`-32602`), as an unusable thread: it cleared the thread id, prepended another preamble and attempted a still larger launch. `_prompt` also consumed early steers before upload/submission succeeded.

The incident evidence supplied to this worker is only the delivery `5bd4f4a6-4925-4192-9711-ff2eff94bc2c`, the 53,710-byte public-document attachment, no output, and a `t3_thread_launch` rejection at `message`. Its real final prompt size, exact earlier calls and live state are unknown. The following reproduction proves the code defect and a matching failure sequence with synthetic content; it does not invent the missing incident payload or claim a live-provider result.

## Reproduction and length units

`reproduce.py` calls the real native attachment composer with a mocked durable API, then models Session's rules/context injection and uses the real `_prompt`. HTTPX MockTransport enforces a 120,000 UTF-16-unit field limit and returns JSON-RPC `-32602`. The legacy comparison is the original no-effort send/fallback branch reconstructed from inspected code; the fixed comparison calls the actual modified `_start` and executes the actual SSH shell command locally in an isolated workspace.

| Synthetic component | Python code points | UTF-16 units | UTF-8 bytes |
| --- | ---: | ---: | ---: |
| Attachment (includes Cyrillic, emoji and CRLF) | 53,698 | 53,699 | 53,710 |
| Native accepted message with header | 53,777 | 53,778 | 53,789 |
| Injected rules/system block | 42,019 | 42,019 | 42,019 |
| Injected context block | 30,021 | 30,021 | 30,021 |
| Pending steer | 1,029 | 1,029 | 1,029 |
| Composed resumed send, including separators | 126,852 | 126,853 | 126,864 |
| Legacy fallback launch, including added preamble | 128,017 | 128,018 | 128,029 |
| Fixed short message pointing to complete file | 387 | 387 | 387 |

Legacy: send and launch both reject, with the thread cleared. Fixed: one send to the existing thread, a complete 126,864-byte UTF-8 file, exact decoded-content equality, and preserved thread identity. Actual output is in `reproduction.log`.

The implementation counts UTF-16 code units conservatively for the JavaScript hub schema. This is distinct from Python `len`, UTF-8 byte size and model tokens. The private hub schema implementation was not supplied, so its exact internal string-length function was not independently inspected. The conservative route stays within 120,000 for both code-point and UTF-16 interpretations. Tests cover 119,999 / 120,000 / 120,001 ASCII units, Cyrillic at/over the limit, and 60,000 emoji (120,000 units) plus the crossing character.

## Change and state safety

- `_wire_message` applies the existing history masking and strict outbound credential guard before either route. Small inputs remain inline. Large inputs use `HubSsh.put_prompt`; the MCP message instructs reading the complete file, in chunks if necessary.
- Full input is UTF-8 in `.orchestra-hub-inputs/<sha256>.txt` inside the existing worker workspace. This uses the existing SSH transport and normal file-reading tools, without a new external API or splitting one task into multiple provider turns. The existing 20 MiB per-file workspace bound applies to the complete input; there is no new restriction on legitimate sub-64-KiB attachments.
- Publication uses a private local scratch file, a remote random temporary file, restrictive permissions, SHA-256 verification and an atomic rename. The remote command pins and checks its physical working directory before writing, rejects a directory symlink and replaces a destination symlink rather than following it. Input text never enters a shell command or argument.
- `PROMPT_DIR` is excluded from source uploads, remote result packing and result imports, including tar snapshots that contain it. Files are retained until the existing workspace-release cleanup, so pending/uncertain steers and no-work retries retain their input. Repeated identical content uses the same filename; different concurrent inputs use different filenames. Long-lived workspaces can retain multiple bounded files until release.
- First turns, resumed sends, explicit refused-thread fallback, live steers and allowed no-work retries all use the same route. Fallback rechecks length after adding the preamble, avoids duplicating an already present preamble, and keeps the old thread id until a replacement actually returns its thread id. A returned thread id is saved even if the run id is missing, for reconciliation.
- JSON-RPC invalid parameters, HTTP validation failures and tool-result validation failures are classified separately. They do not queue another internal steer, clear the thread, launch a replacement or authorize workspace-loss recovery. The same guard protects model retarget/configure. Retryable transport errors still propagate without automatic replay.
- Early steers are a snapshot: `_prompt` does not consume them. Only a confirmed start acknowledges that prefix. Failure preserves it; steers arriving during submission remain queued for the next turn. No change to durable delivery identity/state transitions or workspace reconstruction policy was needed.

## Checks actually run

All Python commands used the provisioned **uv 0.11.28**, `uv run --frozen`, the default `.venv` and locked dependencies. Test temporary directories were inside this task folder; provider MCP/SSH and native delivery APIs were mocked/local. Tests ran at nice=15, sequentially. No live provider CLI/API, real SSH, Telegram, production database or user attachment was used.

Imported `app`: **`/remote/workspace/app/__init__.py`**, an absolute path normalized from the actual worker checkout. Checkout paths and account labels in saved evidence are normalized to `/remote/workspace`; it is not a claim about the server's deployment path.

- Expanded hub regressions: **386 passed, 4 failed, 2 subtests passed**, 92.04 s. Files: `test_hub_message_v1066`, `test_backend_hub`, `test_multicode_client`, `test_hub_workspace`, `test_hub_uv`, `test_hub_inputs_v1062`, `test_hub_inputs_v1063`, `test_hub_download_v1064`, `test_hub_switch_orphan`, `test_hub_effort`, `test_hub_pool`, `test_v1028_hub_outbox_report` (all under `tests/`). See `regressions.log`.
- Final combined verification of the message regressions, backend, MCP client and **entire** native MCP stdio test file: **242 passed**, 11.96 s. See `final-tests.log`. No test was deselected. This includes the four added recovery/history/file-bound controls after the expanded run.
- After the final physical-directory hardening, all **41 V-1066 cases passed**, 4.92 s. See `final-shell-tests.log`.
- Offline synthetic before/after reproduction passed: `uv run --frozen python .orchestra/tasks/V-1066/reproduce.py`.
- Six independent in-memory mutations were killed: missing spill transport; forgotten invalid-parameter classification; code-point-only boundary; prematurely consumed steers; raw large prompt on no-work retry; removed transport-directory exclusion. Each selected test failed with exit 1, after its unmodified control passed in the final suites. See `mutation-*.log` and `mutation_checks.py`. No source was left mutated.
- Checks exercise upload failure, checksum corruption, uncertain send, cancellation, failed replacement launch, missing launch run id, concurrent file publication, directory/destination symlinks, source/result exclusion, exact Unicode/CRLF content, history masking, secret refusal, file bound, late steer retention and same-thread no-work recovery. Existing upload provenance, uv provisioning, download bounds, watch/retry and outbox guards are included in the expanded run.

The four expanded-run failures are copy-environment blockers, not waived assertions:

1. `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`: `.orchestra/pipelines/default/prompts/hub/worker.md` is absent, so the existing fallback preamble lacks the role-specific labels the test requires.
2. `test_retarget_resolves_target_policy_and_claude_option` and both `test_hub_policy_matches_native_claude` cases: `.orchestra/pipelines/default/pipeline.yaml` is absent.

`uv run --frozen python scripts/check_instruction_contract.py` also exits 1 because the copied workspace has no `CLAUDE.md` symlink. That pre-existing copy omission was preserved, not repaired by changing instructions. See `instruction-contract.log`. These checks must be repeated in the complete integration checkout. The full repository suite was not run in this partial copy.

Initial test-fixture mistakes (empty fake secret, non-broker fake path, swapped import arguments) were corrected in the new tests before the final green runs; acceptance assertions were not weakened. Existing supplied tests were unchanged.

## Recovery for the existing source task — instructions only

After integration and **after the existing idle watcher has loaded the new Python**, the orchestrator should:

1. Read the receipt for `5bd4f4a6-4925-4192-9711-ff2eff94bc2c`, the existing target worker/task binding, saved hub workspace/thread mapping and recent native run/activity. Establish whether any submission actually started or remains active. The supplied trace alone is insufficient to determine the receipt's current state. Preserve the existing worker/workspace; do not reset auth, replace its workspace or create a parallel worker.
2. If queued/quota-held, let durable delivery resume. If `FAILED_BEFORE_SUBMIT`, repeat the exact original `send_message` with the same delivery id, text, file path/header and unchanged attachment bytes; the existing delivery owner permits that retry. A repeat with changed content must not be passed off as the same accepted delivery.
3. For `DISPATCHING`/`DELIVERY_UNKNOWN`, repeat the same id only to retrieve the existing receipt and reconcile native evidence; do not automatically create a new id. `DELIVERY_UNKNOWN_ORPHANED` also requires reconciliation.
4. `HubBackend.send` accepts locally before its events start a provider run, so the old receipt may already say `SUBMITTED` despite the later field rejection. Repeating that id returns its receipt and does not force a new turn. Only after confirming no native acceptance/work occurred, submit one explicit recovery delivery containing the complete original accepted message/attachment to the same existing worker with a new delivery id. A bare “continue” is insufficient when the rejected turn never supplied the attachment. Preserve the source task binding and inspect the resulting native run rather than treating an accepted local receipt as completion.
5. Verify one accepted native send to the existing thread, no validation-triggered launch, and that the worker reads the complete broker input and continues the source task. Reconcile missing/ambiguous thread mapping before recovery instead of editing state manually.

No recovery, merge, push, deployment, auth/state operation on a live service or restart was executed. This copy has no `.git`; the platform owns importing/committing the changed files on `task-V-1066/fix-hub-message`. Integration still needs its normal diff review and the missing-resource checks. Live provider consumption/file reading is unverified by design; the offline checks establish full-content availability and submission/state behavior.

## Host acceptance, 2026-10-24

Orchestra read this entire report, the production diff and all new committed tests. On the VPS full fourteen-module selection completed: **575 passed, 2 subtests passed**, two fork deprecation warnings, 30.17s. This includes all four missing-resource cases from the remote copy, prior V1062/V1063 input/provenance protections, V1064 bounded download and merge-operation neighbours, and all native MCP stdio tests. Instruction contract also passed in the complete checkout. Absolute imported app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-hub-message/app/__init__.py`.

Two independent host mutations were caught by committed tests after their green controls: removing the SSH checksum verification made corrupt-transfer refusal fail; moving the inline field limit to120001 made the ascii-over boundary case fail. Mutations ran in isolated processes; source files were never edited. Actual stdout is retained locally under `.orchestra/private/V-1066/host-tests.txt`, `host-checksum-{control,mutation}.txt`, and `host-boundary-{control,mutation}.txt`. All23 changed files passed credential-shape and local literal/forbidden scans before this bookkeeping addition. No model review was run under the owner freeze.

Python activation remains with the existing authorized idle watcher; no manual restart or live provider recovery was performed. Seedon independently continued current V353 work using a smaller delivery, so the original rejected attachment must not be replayed blindly. Full live model consumption of a large broker input remains unverified.
