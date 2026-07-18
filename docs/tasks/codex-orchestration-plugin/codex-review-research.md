# Adversarial second opinion — research

Date: 2026-07-18
Reviewer: fresh Codex GPT-5.5, `high`, read-only, ephemeral
Fallback note: штатный MCP `codex_review` не был доступен после reconnect; review запущен напрямую через Codex CLI. Это не штатная persistent `codex-debate` session.

## Metrics

- Wall: `606,366 ms`
- Exit: `0`
- Input: `1,564,854`; cached input: `1,350,016`
- Output: `12,575`; reasoning output: `4,872`

## Summary

Reviewer не опроверг основной вывод: same-provider routing действительно является policy + native spawn args, Fable — MCP → Claude CLI; полный plugin дублирует Orchestra, а claims `2×/40%` не доказаны. Он нашёл два blocking уточнения в предложенном Fable pilot и несколько ограничений доказательной базы.

## Findings and resolution

### R1 — blocking: MCP нельзя добавить на resume mid-thread

`CodexBackend` передаёт developer/MCP `-c` arguments только для нового `codex exec`; `exec resume` их не повторяет (`app/backend_codex.py:181-200`).

**ACK / fixed:** рекомендация теперь требует preload bridge при spawn нового full-cycle thread; hot-add в Phase 2 существующей session не обещается.

### R2 — blocking: «read-only STDIO MCP» не обеспечивается Orchestra sandbox

`--dangerously-bypass-approvals-and-sandbox` остаётся у parent; `_mcp_config_args()` передаёт command/args/env, а не MCP sandbox contract.

**ACK / fixed:** research теперь приписывает read-only guarantee только audited bridge (`--tools ""`, no persistence, bounded schema), требует security review и не обобщает его на произвольный STDIO MCP.

### R3 — suggestion: benchmark не доказывает `full-cycle=xhigh`

**ACK / fixed:** `worker=medium` оставлен как evidence-backed default; `full-cycle=xhigh` сохраняется только как текущая policy до отдельного real-task A/B.

### R4 — suggestion: raw measurements не сохранены отдельным артефактом

**ACK / fixed:** добавлен `experiment-log.md` с командами, raw summaries, failures и ограничениями воспроизводимости.

### R5 — suggestion: неточная ссылка на event parser/manager

**ACK / fixed:** `[O1]` расширен до parser lines; добавлен `[O3a]` для manager role→effort.

### R6 — question: недооценены project-scoped custom agents

**PARTIAL / fixed:** research признаёт их возможным будущим isolation path, но фиксирует, что текущий worktree config `.codex/agents` не копирует. Это не готовая интеграция.

### R7 — thought: caller identity можно добавить в Orchestra bridge

**ACK / fixed:** отсутствие caller identity ограничено upstream plugin; наша обёртка может передать worker identity через env.

### R8 — suggestion: telemetry Fable MCP и native subagents смешаны

**ACK / fixed:** Fable `mcp_tool_call` уже видим текущему parser; неизвестность оставлена только для native subagent lifecycle/cost aggregation.

### R9 — suggestion: Fable должен конкурировать с `codex-debate`, а не добавляться сверху

**ACK / fixed:** pilot сформулирован как replacement/A-B, не третий обязательный review layer.

## Verdict

`NO MAIN-CONCLUSION BLOCKER AFTER FIXES.` Полный plugin не интегрировать; Fable pilot считать лишь перспективным и запускать только после preload/security design и A/B против существующего review. Effort: оставить `worker=medium`; `full-cycle=xhigh` — status quo, не доказанный benchmark result.

## Round 2 — targeted re-review

Fresh fallback session was necessary because the first CLI review was ephemeral; штатный MCP persistent resume оставался недоступен.

- Wall: `28,507 ms`; exit `0`
- Input `102,825`; cached `64,640`; output `971`; reasoning `273`
- `R1 FIXED`: research требует preload Fable bridge при создании нового thread и не обещает MCP `-c` hot-add на `exec resume`.
- `R2 FIXED`: read-only guarantee ограничен audited bridge; произвольный STDIO MCP не объявлен sandboxed.
- `VERDICT APPROVED`
