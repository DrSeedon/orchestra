<p align="center">
  <img src="docs/banner.png" alt="Orchestra" width="100%">
</p>

<h1 align="center">Orchestra</h1>
<h3 align="center">AI agent teams that think like managers, not state machines</h3>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#comparison">Comparison</a> ·
  <a href="#features">Features</a> ·
  <a href="https://seedon.ru">Website</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/DrSeedon/orchestra?style=social" alt="Stars">
  <img src="https://img.shields.io/github/license/DrSeedon/orchestra" alt="License">
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python">
  <img src="https://img.shields.io/badge/built_by-itself-brightgreen" alt="Built by itself">
</p>

---

**Orchestra is an AI agent orchestration platform where you manage a team of agents the way a CEO manages a company — not the way a programmer writes a pipeline.**

You describe the goal. The orchestrator decomposes it, spawns the workers it needs, routes their output to a different model for review, and merges what passes. Each worker runs in an isolated git worktree. They message each other directly, not through you, and they persist for hours or days, not the length of one API request.

You are not the dispatcher. Deciding what to cut into tasks, who gets which one, when to review and what to merge is the orchestrator's job — an agent's, not yours. What stays with you is the goal, the approvals you choose to keep, and a dashboard to look at when you want to.

> **The AI agent market is moving from SDKs to products.**
> 2024: "here's an SDK, build it yourself." 2025: "here's an agent, give it a task." 2026: "here's a TEAM, give it a goal." Orchestra is the third thing.

<p align="center">
  <img src="docs/dashboard.png" alt="Dashboard showing agents working" width="100%">
  <br>
  <em>Real-time dashboard — a snapshot of 6 agents working in parallel on a client project</em>
</p>

## Quick Start

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 18+, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (requires Claude Max subscription)

```bash
# Clone and install
git clone https://github.com/DrSeedon/orchestra.git
cd orchestra
cp .env.example .env
uv sync              # --extra rag adds the deprecated vector memory, see Features

# Run
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888

# Open http://localhost:8888
# Create an orchestrator, point it at a project, start chatting
```

No graph definitions, no YAML workflows, no node configurations. You talk to the orchestrator like you'd talk to a tech lead.

## How It Works

```
You (Telegram / Dashboard)
  │
  ▼
Orchestrator (Claude) ─── thinks like a manager
  │   Decomposes task, assigns workers, reviews results
  │
  ├─► Worker A ── git worktree: feature/auth
  ├─► Worker B ── git worktree: feature/api
  ├─► Worker C ── git worktree: fix/bug-123
  │
  ▼
Reviewer (GPT) ── cross-model review
  │   Different model = different blind spots
  │
  ▼
Merge ── squash to main
```

Each worker is a full agent session in its own git worktree — Claude Code, Codex, Grok or Orchestra's OpenRouter Harness, chosen per worker. They don't share context, don't step on each other's code, and merge through squash PRs. The orchestrator coordinates. Not a graph engine. An actual AI deciding what to do next.

Workers can talk to each other via `send_message`. The backend worker finishes an API endpoint and messages the frontend worker: "endpoint ready at /api/users, here's the schema." No human relay needed.

<a id="comparison"></a>
## What Orchestra does, doesn't, and refuses to do

Feature tables where the author wins every row aren't worth reading. This one uses three statuses
and no dashes, because a dash hides the only interesting distinction — *couldn't* versus *decided
not to*:

**✅ works today** — with an anchor you can check: `file:line`, a command, or a number we measured ·
**🚧 partial or not enforced in code** — the row says exactly what is missing ·
**🚫 deliberately not on the table** — never built, or built and then retired; the reason is in the row, and it isn't "no time".

| Capability | | Anchor |
|---|---|---|
| An agent, not a human, splits the goal, spawns workers, assigns and merges | ✅ | orchestrator role prompt + `spawn_worker`/`merge_worker`; you approve, you don't dispatch |
| Workers outlive one request | ✅ | 431 finished worker sessions: median 0.8 h, p90 **130.6 h**, max 531.8 h, 81 lived past a day |
| Survive a platform restart; idle workers hibernate and release the process tree | ✅ | SQLite sessions + auto-resume, `app/session_hibernate.py` |
| Workers message each other directly, with durable delivery receipts | ✅ | `app/message_deliveries.py` |
| Workers spawning their own workers | 🚧 | Forbidden by the worker's role prompt, not by the code: `spawn_worker` carries no role gate, so a worker that ignores its instructions can still call it. The rule exists because the child edits the same files on a second branch, so the two diffs compete at merge and one of them loses — plus a task nobody ordered |
| Git worktree per worker, squash merge to main | ✅ | `app/workspace.py` |
| Two workers cannot own the same directory | ✅ | spawn refuses on overlap, `app/manager.py:554` |
| Insertion budget at merge, with a waiver that is recorded | ✅ | 2 000 lines, `app/diff_budget.py:16` |
| The platform, not the agent, runs the tests that decide a merge | ✅ | A mapped test subset gates every merge and blocks on failed *or* inconclusive (`app/merge_operations.py:1737`). A frozen acceptance oracle is pinned and run when the task carries one (`app/acceptance.py:349`); without one, a merge touching `app/` or `tests/` on a non-main target is refused outright (`app/merge_operations.py:801`) |
| Cross-model review as a **code-enforced** merge gate | 🚧 | Required by the agents' role prompts, not by the merge code. The one place the merge path mentions review says so itself: `grep -in review app/merge_operations.py` → one hit, `1226: "REVIEW_WARNINGS_OUTSIDE_MERGE"`. Receipts are stored (`app/db.py:145`) and never consulted |
| Human approval as machine-checkable state | 🚧 | Lives in chat and in the `<approval-gate>` prompt block. No approval receipt exists in the database and merge doesn't ask for one |
| Sandbox around commands an agent runs | 🚧 | The worktree isolates *files*, not execution. Our reviewer runs `-s danger-full-access -a never` (`app/mcp_stdio.py:3698`) because unprivileged user namespaces are off on this host. No isolation work is underway |
| Several vendors' models behind one runtime contract | ✅ | 4 runtimes: the Claude Code, Codex and Grok CLIs, plus our own in-process OpenRouter Harness — `app/runtime_registry.py:330` |
| Adding a new CLI agent by config | 🚫 | Every runtime is a hand-written backend; there is no config path. Orca, by contrast, advertises "any CLI agent" |
| Write with one vendor's model, review with another's | ✅ | `codex_review`, `app/mcp_stdio.py:3564` — the review starts a different vendor's CLI |
| Quota gate that blocks workers near a subscription wall | ✅ | `app/quota_gate.py:115` |
| The same gate applied to orchestrators | 🚫 | Exempt on purpose (owner, 2026-09-03): an orchestrator that stops talking is worse than one that overspends |
| Paid model routes in the built-in harness | 🚫 | Exact `:free` routes only, `app/harness/llm.py:167` |
| Free models as the default workhorse | 🚫 | Measured: 2 of 30 closed tickets solved (6.67 %), and 53 of 60 runs failed on availability rather than quality (#422) |
| Grok kept current with Claude and Codex | 🚫 | Added for one narrow job and left unmaintained. It still runs; it is not a peer |
| Lexical project memory agents must read before working | ✅ | `.orchestra/kb/`, one fact per line with the command that proves it |
| Vector / semantic memory | 🚫 | Built, measured, retired: on an 18-question holdout from this repo, vector search scored **0 unique wins against 6 for plain `rg`**. The implementation still ships and still runs if you enable it (`--extra rag`, off by default) — we just don't build on it any more |
| Root guide small enough to be an index | 🚧 | Our own rule; `wc -c CLAUDE.md` → about **190 KB**. The Codex mirror is trimmed mid-sentence at `project_doc_max_bytes`, so part of it silently never reaches those workers (#323) |
| Dashboard (`app/routes/system.py:77`) and Telegram control (`app/tg_bridge.py`) | ✅ | Voice messages are transcribed with Deepgram Nova-3, `app/transcription.py:72` |
| Terminal client, desktop or mobile app | 🚫 | Never built: the workplace is the dashboard plus Telegram. Phone access is Telegram, not an app |
| Browser-side cache of chat history | 🚫 | Built, then removed on purpose: a local mirror cannot prove nothing appeared after its watermark, so it can show a stale frame as current. `no-store` is set on the server (`app/routes/sessions.py:599`) and on the client (`app/static/js/app.js:1225`) |
| One-command install, prebuilt binaries, Docker image | 🚧 | `git clone` + `uv sync` + your own vendor CLIs and subscriptions. Nothing is published as a release artifact |
| Standing approval or an auto-queue of tasks | 🚫 | Every task is approved by hand (owner, 2026-08-27) so that nothing gets built that wasn't asked for |

### And how is this different from sub-agents?

The honest answer is that it got less different during 2026: sub-agents gained their own context,
messaging between agents, nesting, and opt-in worktrees. What did not change is who owns the
lifecycle and where the vendor boundary runs. Quotes below are from the vendors' own docs,
checked **2026-09-03**.

| | **Orchestra** | **Claude Code sub-agents** | **Codex sub-agents** |
|---|---|---|---|
| Lifecycle belongs to | a row in our database — the worker survives restarts and hibernation | the parent conversation: "Each subagent invocation creates a new instance rather than continuing an earlier one" | the parent run: "Codex waits until all requested results are available, then returns a consolidated response" |
| Repo isolation | a worktree per worker, always | opt-in `isolation: worktree`; by default "A subagent starts in the main conversation's current working directory" | "Subagents inherit your current sandbox policy" |
| Model vendor | four runtimes: Anthropic, OpenAI, xAI, OpenRouter | `model`: "`sonnet`, `opus`, `haiku`, `fable`, a full model ID such as `claude-opus-5`, or `inherit`" | `gpt-5.6`, `gpt-5.6-terra`, `gpt-5.6-luna` |
| Review | a different vendor's model, required by role prompt (see the 🚧 row above) | "Spawn a teammate using the security-reviewer agent type" | "Review this branch with parallel subagents" |

Measured on our own database, 2026-09-02: sub-agents of both kinds recorded here lived a median of
**12.5 s** (p90 75.1 s), and **0.0 %** of them lasted longer than ten minutes; worker sessions had a
p90 of **130.6 h**. That is a difference in kind, not in duration — and it cuts both ways. A
sub-agent is one tool call inside a running process; a worker here costs a session row, a branch and
a worktree, so for "go read twenty files and come back" that machinery buys nothing. Sub-agents also
nest "up to three layers below the main conversation" out of the box, which we forbid by rule.

### Where we are behind

- **Breadth.** 4 runtimes against Orca's "any CLI agent" — "if it runs in a terminal, it runs in Orca". Ours is a code contract; theirs is a terminal.
- **Tool latency.** Every tool call here is an external process: measured on this host, 3 667.6 µs against 20.2 µs in-process, of which 2 170.0 µs is `fork+exec` alone. oh-my-pi compiles its tooling in and states "No fork/exec on the hot path".
- **No LSP or debugger in the agent's hands** — ours reads files and shells out to `rg`.
- **Interfaces and packaging.** Orca ships desktop and mobile apps; when an agent spawns helpers, cmux "turns them into native panes and splits instead of hidden background processes". We ship a web dashboard and a Telegram bot, installed from a `git clone`.
- **Maturity.** One maintainer and 5 stars against 60 526 (Orca) and 26 737 (cmux), read 2026-09-03. What is being compared above is architecture, not a mature product.

<sub>Sources, all re-checked 2026-09-03: [Claude Code sub-agents](https://code.claude.com/docs/en/sub-agents) ·
[agent teams](https://code.claude.com/docs/en/agent-teams) ·
[Codex sub-agents](https://learn.chatgpt.com/docs/agent-configuration/subagents) ·
[Orca](https://github.com/stablyai/orca) · [cmux](https://github.com/manaflow-ai/cmux) ·
[oh-my-pi](https://github.com/can1357/oh-my-pi) READMEs, pulled raw via `gh api`, and star counts via
`gh api repos/<owner>/<repo>`. Orchestra's numbers come from the primary installation's own database,
read 2026-09-02, and from the commands shown in the table. Where a competitor's primary source did not
answer a question — isolation and inter-agent messaging in cmux, review in Orca — there is no row, rather
than a guess.</sub>

## Features

### 🏗️ Persistent Agent Fleet
Agents live for hours or days. They maintain context across tasks, remember past decisions, accumulate project knowledge. Not one-shot functions.

### 🌳 Git Worktree Isolation
Every worker gets its own git worktree — a full copy of the repo on its own branch. Two workers editing the same project never touch the same files. Merge conflicts are structurally minimized. `owned_dirs` per worker + `check_conflict()` before merge = safe parallel work.

### 📱 Telegram Bridge
Manage your AI team from your phone. Voice messages, photos, documents — the orchestrator transcribes voice (Deepgram Nova-3), understands images, processes files. Real-time status updates in topic threads.

### 🔀 Cross-Model Review
Code written by one model (Claude) is reviewed by another (GPT). Different models have different blind spots. Two perspectives catch bugs that one model misses. The step is required by the agents' role prompts and is not yet enforced by the merge code — see the status table above.

### 🏰 Hierarchy: Orchestrator → Sub-Orchestrators → Workers
One orchestrator per project. Sub-orchestrators manage sub-teams. Workers do the work. Cross-project messaging lets orchestrators coordinate across repos.

### 🔄 Built by Itself
Orchestra-orchestrator is the agent that builds Orchestra: workers write the code for the platform they run on, and this section was edited by one of them.

Numbers below come from the primary installation's own database, read **2026-09-02**. Sessions, tasks and sub-agents are cumulative; messages and turns cover the current log window, which opens 2026-07-27:

| | |
|---|---|
| Agent sessions | **598** (577 workers, 21 orchestrators) |
| Background jobs and sub-agents recorded | **5 593** (of which 197 are spawned sub-agents; the rest are background shell tasks) |
| Messages logged | **250 877** |
| Agent turns | **7 047** |
| Tasks tracked | **781** across 19 projects |

None of these are concurrency figures — peak observed parallelism is up to 10 workers at once. A second installation runs on a separate server and is counted separately, never added to these: 469 sessions, 5 043 background jobs and sub-agents recorded (18 of them spawned sub-agents), 248 867 messages, 660 tasks across 9 projects.

### ⚙️ Per-Role Model Policy
Every role declares its model in the pipeline manifest, and the orchestrator routes new workers by task class and remaining quota rather than by name or habit. Runtimes are mixable per worker — Claude Code, Codex, Grok and Orchestra's OpenRouter Harness all run as workers behind one contract, so a task can be written by one vendor's model and reviewed by another's.

### 📋 Task Manager
Built-in task management with priorities, assignments, and payment tracking. Agents create, update, and close tasks. No external project management tool needed.

### 💾 Persistent Sessions
Agents survive restarts. Sessions are stored in SQLite, auto-resumed on boot. Context is compacted automatically when it fills up. Workers pick up where they left off.

An idle agent costs nothing: Claude and Codex workers hibernate after their idle timeout, releasing the whole process tree — app-server and MCP servers included — and resume the exact same native thread on the next message. Spawn, switch, merge and delete are serialized through one repository lock, so a worker is never published half-prepared and a merge never lands against a moved target.

### 🐞 Durable Bug Inbox
Agents file platform bugs through `report_bug`. Reports land in the service state directory outside every Git checkout — one immutable record per report, published by atomic rename — so a bug filed mid-task can never dirty a worktree and block merges. Unread reports raise a banner in the dashboard.

### 🧠 Project Memory
Agents search past work across task docs, project rules and prior agent messages before they start.
Retrieval is lexical: plain `rg` over the knowledge base, which is written for that — one fact per
line, with exact paths, symbols and the command that proves it.

**The vector path is deprecated.** Hybrid retrieval (fastembed + sqlite-vec, fused with RRF,
reindexed on every merge) is still in the code and still runs for anyone who turns it on with
`uv sync --extra rag` + `RAG_ENABLED=true`, but it is off by default, it is not where new work
goes, and we don't recommend building on it. The reason is our own A/B, not a preference: on an
18-question holdout from this repository, vector search scored **0 unique wins against 6 for
ordinary `rg`**. With the flag off nothing ML is loaded and `search_memory` replies with the grep
command to run instead.

### 📊 Real-Time Dashboard
HTMX + SSE dashboard shows every agent, their status, context usage, cache hit rate, current task, and live logs. No polling, no refresh.

Chat history is never served from a local cache. Selecting an agent fetches one fresh snapshot, and
the live stream continues strictly after the last message id that snapshot contained. Freshness is
enforced from both ends — `Cache-Control: no-store` on the server, `cache: 'no-store'` on the client
— and switching agents aborts the previous request, so one agent's history can never bleed into
another's view.

## Real Projects Built with Orchestra

These aren't demos — they run in production. Orchestra's own figures are as of 2026-09-02, the rest as of 2026-08-07; some of these projects are private client work, so the repositories are not public.

| Project | What it does | Scale |
|---------|-------------|-------|
| **Parsing** (client, Kamchatka) | Data import, dedup, genealogy search | 166M records in MySQL |
| **[Seedon](https://seedon.ru)** (our company) | Registration, accounting, legal, site, marketing, first client | Full business ops |
| **[Kesha](https://github.com/DrSeedon/kesha-tg-bot)** | Personal Telegram bot on Claude Agent SDK | 24/7 on VPS |
| **VPN Service** | Marzban VLESS+Reality management | Self-hosted |
| **RimWorld Mods** | 70+ mod translations, C# DLL | 2000+ text keys |
| **Sensar** (medtech) | Software validation protocol for video laryngoscope | 36 test items, 20 pages |
| **University** | MSc thesis, lecture notes, ML dashboards | 45 pages, 29 DOI sources |
| **Orchestra itself** | Self-development: workers build the platform they run on | 598 agent sessions, 197 spawned sub-agents (see above) |

## Architecture

```
Dashboard (HTMX + SSE) ◄──► FastAPI :8888 ◄──► Session Manager
                                                  │
                               ┌──────────────────┼──────────────────┐
                               ▼                  ▼                  ▼
                         Orchestrator A     Orchestrator B     Orchestrator C
                         (Project: site)    (Project: bot)     (Project: data)
                           │                  │                  │
                      ┌────┼────┐         ┌───┼───┐          ┌──┼──┐
                      ▼    ▼    ▼         ▼   ▼   ▼          ▼  ▼  ▼
                     W1   W2   W3        W4  W5  W6         W7 W8 W9
                    (fe) (be) (seo)     (tg)(api)(db)      (import)(dedup)(search)

TG Bridge (aiogram) ◄──► Orchestra API ◄──► Telegram group (topics per agent)

SQLite (WAL) ── sessions, logs, tasks, payments, background jobs, usage
Git Worktrees ── one per worker, squash merge to main
Service state ── bug inbox, kept outside every checkout
```

## Telegram Bridge

Mirror everything to a Telegram group with topic threads. Write in TG, agents receive. Send voice — transcribed via Deepgram. Send screenshots — agents see them.

```bash
# Add to .env
TG_BRIDGE_TOKEN=your_bot_token
TG_BRIDGE_GROUP=your_group_id
# Optional: voice transcription
DEEPGRAM_API_KEY=your_key
```

## Stack

- Python 3.12+, FastAPI, Jinja2, SSE
- `claude-agent-sdk` — Claude Code SDK (persistent client per session)
- Codex and Grok runtimes behind one backend contract (JSON-RPC over stdio), plus the in-process OpenRouter Harness
- SQLite (WAL mode), git worktrees
- fastembed + sqlite-vec — deprecated vector memory, off by default (`--extra rag`)
- Tailwind CSS, highlight.js, marked.js (bundled offline)
- aiogram 3.x (Telegram bridge)
- Deepgram Nova-3 (voice transcription)

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Good first issues are labeled `good-first-issue`.

## License

**AGPL-3.0** for open source use. Commercial license available for businesses that need it.

See [LICENSE](LICENSE) for details. Contact [@DrSeedon](https://t.me/DrSeedon) for commercial licensing.

---

<p align="center">
  <b>Orchestra</b> — stop building pipelines, start managing teams
  <br>
  <a href="https://seedon.ru">seedon.ru</a> · <a href="https://t.me/DrSeedon">Telegram</a> · <a href="https://github.com/DrSeedon/orchestra">GitHub</a>
</p>
