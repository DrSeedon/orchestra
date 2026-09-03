# Orchestra ROI Report — May 2026

**Period:** 5 May — 23 May 2026 (19 days, 18 active)
**Prepared:** 2026-05-23

---

## Executive Summary

За 19 дней работы Orchestra управляла **49 AI-агентами** на **2 серверах** (локальный + VPS клиента), обслуживая **15 проектов**. Виртуальная стоимость по API-ценам — **$38,196**, реальная стоимость подписки — **$200/мес** (~$130 за период). Экономия **~99.7%** vs API.

Для клиента (parsing-hub) выполнено и оплачено **163 задачи** на **2,060,000₽**. Получено оплат на **2,284,000₽**. VPS Orchestra за 3 дня работы произвела **35 коммитов** и обработала **3,260 turns** через 13 агентов.

---

## 1. Infrastructure Overview

| Metric | Local | VPS (client) | Total |
|---|---|---|---|
| Active days | 19 | 3 | — |
| Sessions (agents) | 36 | 13 | 49 |
| Projects | 12 | 3 | 15 |
| Log entries | 55,049 | 27,528 | 82,577 |
| Tool calls (logged) | 17,814 | 9,508 | 27,322 |
| Virtual cost (API equiv) | $21,634 | $16,562 | $38,196 |
| Subagent spawns | 532 | 656 | 1,188 |

## 2. Cost Analysis

### Virtual vs Real Cost

| | Virtual (API prices) | Real (subscription) |
|---|---|---|
| Claude Opus 4.6 (1M) | $38,130 | — |
| Claude Sonnet 4.6 | $52 | — |
| GPT-5.5 (Codex) | $15 | $0 (free tier) |
| **Total** | **$38,196** | **~$130** (19/30 × $200) |
| **Savings** | — | **99.7%** |

### Cost by Model (Both Servers)

| Model | Agents | Virtual Cost |
|---|---|---|
| Claude Opus 4.6 [1M] | 40 | $38,130 |
| Claude Sonnet 4.6 | 5 | $52 |
| GPT-5.5 | 4 | $15 |

## 3. Projects Breakdown (Local)

| Project | Agents | Virtual Cost | Notes |
|---|---|---|---|
| Parsing (parsing-hub) | 4 | $10,978 | Client project — family tree builder, burials import |
| Orchestra (self-dev) | 6 | $6,274 | Self-development — dashboard, backend, TG bridge |
| Seedon | 4 | $2,562 | SEO/CRO analysis, marketing strategy |
| RimWorld Mods | 3 | $1,224 | Game modding — Grounded mod dev |
| University | 6 | $204 | Academic projects |
| kesha-tg-bot | 4 | $155 | Telegram bot |
| Unity | 1 | $127 | Unity game dev |
| Sensar | 1 | $86 | Cursor project |
| TradingCryptoBot | 2 | $10 | Crypto trading bot |
| Aperant | 3 | $7 | — |
| COG-second-brain | 1 | $4 | — |
| VPN-Service | 1 | $2 | — |

### Top Sessions by Cost (Local)

| Agent | Project | Cost | Status |
|---|---|---|---|
| Parsing-orchestrator | Parsing | $9,871 | idle |
| Orchestra-orchestrator | Orchestra | $5,628 | idle |
| seedon-orchestrator | Seedon | $2,450 | running |
| Mods-orchestrator | RimWorld | $837 | idle |
| family-tree-builder | Parsing | $696 | idle |

## 4. VPS Client Instance (147.45.101.84)

**Deployed:** 21 May 2026 (3 days ago)
**Project:** parsing-infra (client's parsing infrastructure)

| Agent | Cost | Turns | Tool Calls | Status |
|---|---|---|---|---|
| Parsing-orchestrator | $13,930 | 660 | 396 | idle |
| zahoron-worker | $1,299 | 722 | 684 | idle |
| mobile-worker | $514 | 877 | 858 | idle |
| drevo-builder | $309 | 265 | 253 | running |
| test-worker | $138 | 82 | 76 | idle |
| victoria-worker | $110 | — | — | idle |
| victoria-dev | $97 | 462 | 451 | idle |
| victor-researcher | $96 | 120 | 108 | idle |
| drevo-worker | $77 | 74 | 63 | idle |
| codex-reviewer | $8 | — | — | running |

**VPS Totals:** 3,260 turns, 2,919 tool calls, 35 commits in 3 days.

**VPS Tasks:**

| Status | Count | Price (₽k) |
|---|---|---|
| Done | 21 | 182.0 |
| In progress | 6 | 51.0 |
| Backlog | 30 | 553.0 |
| New | 57 | 641.0 |
| Cancelled | 8 | 90.0 |

## 5. Client Revenue (parsing-hub)

### Task Manager Stats

| Status | Tasks | Price (₽k) |
|---|---|---|
| Paid | 163 | 2,060 |
| New | 28 | 362 |
| Backlog | 32 | 554 |
| Cancelled | 15 | 244 |
| **Total active** | **223** | **2,976** |

### Payments Received

| Date | Amount | Note |
|---|---|---|
| 14 May | 2,169,000₽ | YouGile import (consolidated) |
| 17 May | 56,000₽ | ATB transfer |
| 19 May | 29,000₽ | ATB transfer |
| 19 May | 30,000₽ | ATB transfer |
| **Total** | **2,284,000₽** | (~$25,378 @ 90₽/$) |

### Revenue vs Costs

| Metric | Amount |
|---|---|
| Revenue from client (paid) | 2,284,000₽ ($25,378) |
| Orchestra subscription cost | $200/month |
| **ROI** | **~126x** (revenue / cost) |

## 6. Activity Timeline (Local)

| Date | New Sessions |
|---|---|
| May 5 | 3 |
| May 6 | 2 |
| May 7 | 2 |
| May 9 | 2 |
| May 10 | 2 |
| May 11 | 3 |
| May 12 | 3 |
| May 13 | 1 |
| May 14 | 5 (peak) |
| May 16 | 1 |
| May 17 | 3 |
| May 19 | 2 |
| May 20 | 1 |
| May 21 | 3 |
| May 22 | 2 |
| May 23 | 1 |

## 7. Productivity Metrics

### Work Output Estimates

- **Tool calls logged:** 27,322 (both servers)
- **Subagent spawns:** 1,188
- **Log entries generated:** 82,577
- **Git commits (Orchestra project):** 673
- **Git commits (VPS, 3 days):** 35
- **Git commits (Parsing local):** 23

### Time Equivalent

Assuming 1 tool call ≈ 1 manual action (file edit, terminal command, code review step):

| Metric | Value |
|---|---|
| Total tool calls | 27,322 |
| Estimated human equivalent (@ 30 actions/hr) | **~911 hours** |
| Effective work weeks (@ 40hr/wk) | **~23 weeks** |
| Cost per equivalent hour | **$0.14** |

## 8. Comparison: With vs Without Orchestra

| Metric | Without Orchestra | With Orchestra |
|---|---|---|
| Agent management | Manual CLI sessions, one-at-a-time | Parallel agents, auto-spawn/stop, persistent sessions |
| Context tracking | None (restart = lost context) | SSE dashboard, real-time logs, context % |
| Task management | Spreadsheet/YouGile only | Integrated task manager, auto-assignment to agents |
| Cross-agent communication | Copy-paste between terminals | `send_message()` — instant, no human relay |
| Client billing | Manual invoice tracking | Auto-payment distribution, task-level accounting |
| Multi-project | Separate terminals per project | Single dashboard, 12+ projects simultaneously |
| VPS deployment | Not feasible manually | Deploy with systemd, full remote agent fleet |
| Cost visibility | No tracking | Per-agent, per-project cost breakdown |
| Recovery from context overflow | Manual restart, re-explain | Compact worker, resume with full history |

## 9. Key Findings

1. **$200 subscription → $38,196 in API-equivalent compute** — 190x leverage on infrastructure
2. **$200 subscription → 2,284,000₽ ($25,378) in client revenue** — 126x financial ROI
3. **Opus dominates** (99.8% of virtual cost) — Sonnet and GPT-5.5 are used sparingly for specific tasks (implementation, code review)
4. **VPS deployment validated** — 3 days, 13 agents, 3,260 turns, client's infra running autonomously
5. **23 weeks of equivalent human work** compressed into 19 calendar days
6. **Parsing-hub is the money project** — $10,978 local + $16,562 VPS = $27,540 virtual compute for a project generating 2.28M₽ revenue
7. **Self-development pays off** — $6,274 spent on Orchestra improving itself (dashboard, TG bridge, task manager, auth, MCP tools)

## 10. Recommendations

1. **Scale VPS deployments** — proven model, deploy for more clients
2. **Optimize Opus usage** — consider Sonnet for implementation-heavy workers (20x cheaper, adequate for code-from-spec)
3. **Track token counts properly** — `total_input_tokens`/`total_output_tokens` columns are mostly zeros; fix stats collection for better cost attribution
4. **Automate task→agent pipeline** — from "new task" to "assigned worker" with minimal human oversight
5. **Add commit tracking per worker** — link git commits to sessions for audit trail

---

*Generated by Orchestra ROI Analysis Agent, 2026-05-23*
