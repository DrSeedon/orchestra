---
name: skillcache
description: "Self-learning SkillCache v1 protocol: capsule-first execution for Tier A/B read-only collectors (>= 5 deterministic steps), trace extraction, 2-gate counterexample qualification, and stale/deopt vN -> v(N+1) repair."
---

# SkillCache v1 — Self-Learning Capsule Protocol

## 4 Iron Laws
1. **Capsule First (Tier A/B >= 5 steps):** Before executing a repetitive read-only skill with `>= 5` deterministic read/API/MCP/CLI calls, check `capsule_run` / `orch-capsule-run list` and run the active capsule (`orch-capsule-run exec <skill>`).
2. **Self-Authoring from `invocation_id` Traces:** After cleanly executing a new `>= 5`-step deterministic read-only sequence manually, distill its fixed read plan + verification step into a SkillCache capsule manifest and read-only host source adapter. Never accept raw commands, URLs, paths, or credentials from model inputs.
3. **Mandatory 2-Gate Qualification before `active`:**
   - **Gate A (Replay + Redaction):** seccomp-jailed deterministic fixture replay (`app/skillcache/replay.py`) + `secret_mask` redaction check.
   - **Gate B (Counterexample Mutation):** mutate dates, mailboxes, IDs, batches, or date windows; frozen prior outputs MUST fail verification (`verification_failed`) and live runs MUST recompute dynamic totals/checksums.
4. **Self-Repair (`stale` / `deopt`) & Tier C Boundary:** When `status=stale` (`SKILL.md`/dependency `SHA-256` drift or MCP schema digest drift) or `deopt` occurs at step `k`, patch only step `k`, re-run 2-gate qualification, and bump `vN -> v(N+1)`.
   - **Tier C Exclusion:** Pure creative, editorial, interview, or debate skills (`explainer-craft`, `grill-me`, `game-ui-design`, `codex-debate`, `teach-me`) MUST NEVER be baked into capsules.

## Ready-to-Use Shell CLI (`orch-capsule-run` in `$PATH`)
```sh
orch-capsule-run list
orch-capsule-run describe vps-health-preflight
orch-capsule-run exec vps-health-preflight
orch-capsule-run exec vps-health-preflight --in '{"query":{"units":["orchestra.service","kesha-bot-vps.service"],"include_sessions":true}}'
```
- `list` and `describe` auto-discover `/home/kesha/orchestra/data/skillcache.json` and `data/orchestra.db` from any shell.
- `exec <skill> [--in JSON]` runs any active `vps` capsule with smart defaults or validated `--in` arguments (`describe <skill>` shows exact schema & copy-paste MCP/CLI payloads).
- MCP/proof-gated calls (`capsule_run` / `orch-capsule-run run|continue`) still require cryptographic session proof (`ORCHESTRA_SESSION_ID` + `ORCHESTRA_MCP_PROOF` or HMAC headers). Fallback cleanly to the raw `SKILL.md` whenever status is `unavailable`, `revoked`, `stale`, or `deopt`.

## Active Capsule Pool (10 Read-Only Collectors)
- `kesha-mail` (`inbox_digest`) — Mail.ru IMAP + Gmail read-only unread collection & verification
- `direct-reports` (`reconcile_report`) — Yandex Direct daily vs period total reconciliation
- `xiaomi-sleep` (`sleep_window`) — Xiaomi sleep-log & activity-log RHR median collector
- `browser-control` (`inspect_page`) — Origin-pinned headless Chromium DOM structure check
- `morning-digest` (`morning_collect`) — Mail, sleep, wellness courses & reminders morning collector
- `wellness-dashboard` (`wellness_summary`) — Supplements, courses, low stock & sleep/RHR trends
- `edo-1c-status` (`edo_readonly_status`) — Read-only 1C EDO DB, CryptoPro license, XML inbox & deadlines
- `youtube-reader` (`youtube_metadata`) — oEmbed metadata & cached transcript/chapters collector
- `vps-health-preflight` (`vps_preflight`) — Systemd units, RAM/RSS, disk, sessions & cut-risk preflight
- `avito-stats` (`avito_inventory`) — Read-only Avito batch inventory, status counts & missing photos

## Operator Qualification Command
```sh
orch-capsule-run qualify --scope vps --skill <skill>
```
