# Orchestra Bug Reports

## Open

### 🟡 TG diff images not rendering
- **Reporter:** Orchestra-orchestrator (2026-06-08)
- Edit/Write/Read/Grep/Bash diff images (`app/diff_image.py`) code exists but images don't appear in TG
- Debug logging added (`c0d73fe`) but no logs appear — `_send_diff_image` may not be called
- Need to verify after restart with debug logging enabled

### 🟡 Codex review unreachable — 403 Cloudflare
- **Reporter:** research-runtime (2026-06-05)
- `codex exec` blocked by Cloudflare geo/datacenter. Proxy 12334 routes only Anthropic, not OpenAI
- Workaround: none currently. Need separate proxy route for OpenAI

## Closed (2026-06)

- ✅ **send_message 500 после рестарта** — Fixed: ensure_loaded_any fallback (2026-06-03)
- ✅ **DONE report to wrong parent** — Fixed: last_task_sender tracking + report-format prompt (2026-06-04)
- ✅ **Ambiguous task linking** — Fixed: project_id filter in link_commits_to_task (2026-06-04)
- ✅ **Prices in thousands** — Fixed: exact currency units, _fmt_amount, removed *1000 (2026-06-04)
- ✅ **Worker status stuck idle while running** — Fixed: turn timeout no longer resets status (2026-06-05)
- ✅ **TG files to wrong topic** — Fixed: _find_orch_for_scope by parent_name (2026-06-05)
- ✅ **change_model not persisted** — Fixed: immediate save_session in change_model (2026-06-09)
- ✅ **dev-lead malformed tool calls** — Root cause: Opus 4.8 bug. Switched to 4.6 + prompt rule added
- ✅ **Single tilde strikethrough** — Fixed: escape single ~ before marked.parse
- ✅ **Spawn bubble text wrapping** — Fixed: cut at newline boundary
- ✅ **Worker colors after refresh** — Fixed: await refreshSessions before connectSSE
- ✅ **Send errors hidden in dashboard** — Fixed: show red ❌ instead of null
- ✅ **System prompt lost on compact** — Fixed: always set system_prompt (2026-06-03)
- ✅ **switch_worker_branch blocked after squash** — Fixed: reset --hard from_ref (2026-06-03)
- ✅ **Cross-project send_message** — Fixed: ensure_loaded_any fallback (2026-06-03)

## Closed (2026-05)

- ✅ **codex_review output path** — Fixed: Codex через bash (cwd=worktree)
- ✅ **Codex Reconnecting через прокси** — Fixed: strip proxy env
- ✅ **Deepgram SSL BAD_RECORD_MAC** — Fixed: trust_env=False + certifi
- ✅ **send_file silent false-positive** — Fixed: validate TG response
- ✅ **kill_worker удаляет логи** — Fixed: archive_session
- ✅ **Zombie workers after restart** — Fixed: auto_resume_all filters archived
- ✅ **Merge конфликт после squash** — Fixed: auto-reset worktree (#38)
