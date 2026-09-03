# Claude Opus 4.6 vs GPT-5.5 (Codex) — Orchestra

**Prepared:** 2026-05-23
**Scope:** сравнение для Orchestra: многоагентная разработка, code review, security review, длинные задачи, управление воркерами.

---

## Executive Summary

**Не стоит заменять Opus 4.6 на GPT-5.5 как основную модель Orchestra сейчас.** Для нашей текущей архитектуры Opus остается лучше как orchestrator/worker runtime: 1M context, стабильный Claude Code/SDK lifecycle, полноценная интеграция с MCP/Orchestra tools, нормальная доставка результатов через `send_message`, branch/task workflow и long-running агентные задачи.

**GPT-5.5 стоит оставить и расширять как adversarial reviewer через `codex-review`.** Это самая сильная роль GPT-5.5 в нашем стеке: он нашел 8 P0 critical и 6+ P1/high багов, включая SSRF, XSS, IDOR, open redirect, sandbox bypass и production mock-payment. Важно не то, что GPT "умнее во всем", а что это другая модель с другой ошибочной поверхностью. Она ломает то, что Opus-воркеры считают уже исправленным.

**Оптимальная стратегия: Opus пишет и оркестрирует, GPT-5.5 проверяет.** Для P0/P1 поверхностей нужен обязательный cross-model review: auth, payments, sandboxing, SSRF/network, file access, migrations, task manager state, background jobs.

---

## Current Caveats

1. **Opus 4.7 уже вышел, но этот документ сравнивает Opus 4.6**, потому что Orchestra сейчас считает и использует именно `claude-opus-4-6[1m]`. Публичные OpenAI таблицы иногда сравнивают GPT-5.5 с Opus 4.7; это не прямой ответ на вопрос про Opus 4.6.

2. **Цена GPT-5.5 в исходной гипотезе устарела/смешана.** OpenAI сейчас показывает GPT-5.5 API как **$5 input / $30 output за 1M tokens**, а не `$2.50/$10`. `$2.50` input получается для Batch/Flex GPT-5.5 или для standard GPT-5.4, но output у Batch GPT-5.5 будет `$15`, не `$10`.

3. **Context GPT-5.5 зависит от канала.** API docs показывают 1,050,000 context window и 128,000 max output. Codex launch page обещает 400K context в Codex. В реальных Codex CLI session events есть публичный issue, где GPT-5.5 репортит `258400` usable window из-за client/model-catalog split. Для Orchestra важен практический лимит Codex, а не только model-card лимит API.

4. **Benchmarks не равны production quality.** SWE-bench, Terminal-Bench и GPQA полезны, но сильно зависят от scaffold, tool harness, reasoning effort и contamination. Для Orchestra решающим является сочетание: качество модели + инструменты + стабильность сессии + доставка результата.

---

## 1. Characteristics

| Dimension | Claude Opus 4.6 | GPT-5.5 / Codex | Practical meaning for Orchestra |
|---|---:|---:|---|
| Context window | 1M in Claude Platform / Claude Code 1M variant | API: 1.05M; Codex published: 400K; observed CLI issue: 258.4K usable | Opus is safer for full project/session memory today. GPT-5.5 via Codex is constrained in our actual path. |
| Max output | 128K | 128K | Comparable on paper. |
| API price, standard | $5 input / $25 output per 1M | $5 input / $30 output per 1M | GPT-5.5 is slightly more expensive on output, not cheaper, at standard API rates. |
| Batch/Flex | Batch 50%: $2.50 / $12.50 | Batch/Flex 50%: $2.50 / $15 | Batch economics are close; not relevant to interactive agents unless we batch reviews. |
| Long context pricing | Current Anthropic pricing page says full 1M at standard pricing | >272K input tokens priced at 2x input and 1.5x output for full session | Very long GPT-5.5 API calls can become materially more expensive. |
| Reasoning controls | Adaptive thinking + effort: low/medium/high/max | Reasoning effort: none/low/medium/high/xhigh | Both support explicit reasoning depth. |
| Speed | Opus normal mode can be slow on high/max effort; Fast mode exists at 6x price | OpenAI says Codex Fast mode generates 1.5x faster at 2.5x cost | For interactive review, GPT-5.5 can be fast enough; for long orchestration, stability matters more than raw tok/s. |
| Tools/MCP, platform | Claude Code has first-class MCP, channels, resources, managed config | OpenAI API supports remote MCP/connectors, and Codex docs include MCP config; our standalone Codex lacks Orchestra MCP delivery | The issue is not "OpenAI has no MCP"; it is "our Codex subprocess path does not have Orchestra MCP/send_message yet." |
| Current Orchestra fit | Orchestrators, workers, branch/task state, Telegram delivery, MCP tools | `codex-review` subprocess, standalone reviewers unreliable | Opus is the runtime. GPT-5.5 is a specialist reviewer. |

### Notes on MCP

Claude Code is currently operationally ahead for Orchestra because MCP is native to the way our workers run: Orchestra tools are available in-session, workers can report progress, update tasks, send messages, and commit. OpenAI has MCP support in the Responses API and Codex docs, but our actual GPT-5.5 path is `codex exec` as a subprocess. In that path, Codex output returns to the Claude worker, and Claude handles delivery.

This distinction matters. The platform capability exists; the Orchestra integration is not equivalent yet.

---

## 2. Benchmarks and Public Signals

### Coding

| Benchmark / signal | Claude Opus 4.6 | GPT-5.5 | Readout |
|---|---:|---:|---|
| SWE-bench Verified | Public aggregators commonly cite ~80.8% for Opus 4.6; official Anthropic notes a modified prompt run at 81.42% | Aggregators cite 88.7% OpenAI-reported for GPT-5.5 | GPT-5.5 likely leads raw SWE-bench Verified, but verify scaffold before using this as procurement truth. |
| SWE-bench Pro | OpenAI launch compares GPT-5.5 against Opus 4.7, not 4.6; Opus 4.7 is 64.3% | 58.6% | GPT-5.5 is strong, but Anthropic's newer Opus line remains very competitive on harder SWE variants. |
| Terminal-Bench 2.0 | Anthropic launch says Opus 4.6 led at release; current OpenAI launch compares GPT-5.5 82.7% vs Opus 4.7 69.4% | 82.7% | GPT-5.5/Codex is excellent on terminal/devops-style tasks. |
| HumanEval | Saturated/stale for frontier models | Saturated/stale for frontier models | Low decision value in 2026. Use repo-level evals instead. |
| Coding competitions / LiveCodeBench | No clean, current, same-harness Opus 4.6 vs GPT-5.5 pair found | No clean, current, same-harness Opus 4.6 vs GPT-5.5 pair found | Treat as inconclusive unless we run our own eval. GPT-5.5's Terminal-Bench and SWE signals suggest strong contest-style debugging, but not enough to replace Opus operationally. |
| Real Orchestra review | Good implementer, but missed bugs in own/peer code | Found 8 P0 + 6+ P1/high | GPT-5.5 has proven value as independent reviewer. |

### Science, Math, Reasoning

| Benchmark / signal | Claude Opus 4.6 | GPT-5.5 | Readout |
|---|---:|---:|---|
| GPQA Diamond | Anthropic system-card/search snippets cite ~91.3% for Opus 4.6 | OpenAI launch: 93.6% | GPT-5.5 is slightly ahead in OpenAI's table, but differences are small at this tier. |
| FrontierMath / MATH-like hard math | Public Opus 4.6 direct comparable data is less clean; Anthropic emphasizes HLE and expert reasoning | OpenAI launch: FrontierMath T1-3 51.7%, T4 35.4% | GPT-5.5 has strong hard-math public numbers. For Orchestra, math is not primary. |
| Humanity's Last Exam | Anthropic says Opus 4.6 led frontier models at release | OpenAI launch: GPT-5.5 41.4% no tools, 52.2% with tools; compares mostly to Opus 4.7 | Both are frontier-level. Tool harness matters heavily. |
| Long-context retrieval | Anthropic reports Opus 4.6 76% on 1M 8-needle MRCR v2 | OpenAI reports strong MRCR/Graphwalks, including 74.0% on 512K-1M MRCR range | Both can use long context; Opus has the better proven operational context in our stack. |

### Security

Opus 4.6 has strong external security signals: Anthropic says it performs well on vulnerability discovery and reports customer/security investigations where Opus 4.6 beat prior Claude models. GPT-5.5 has strong OpenAI-reported cybersecurity scores too, including CyberGym 81.8%.

For Orchestra, the internal evidence is sharper than generic benchmarks: GPT-5.5 found real bugs Opus missed. That makes it valuable even if Opus is also a strong security model, because diversity beats single-model confidence.

### Code Quality Verdict

There is no single winner.

**Opus 4.6 writes better production changes inside Orchestra** because it has the full operating context: MCP tools, branch/task rules, progress reporting, worktree discipline, and enough context to keep architectural intent in memory. It is the better model when "good code" means a merged, tested, reported change that fits the existing system.

**GPT-5.5 is better at finding why code is wrong.** In our evidence, it is the stronger adversarial reviewer: it checks exploit paths, follows call chains, challenges insufficient fixes, and ranks severity more aggressively. It should be treated as a critic, not the primary hands on keyboard agent, until the Codex backend has first-class Orchestra integration.

---

## 3. Orchestra Experience

Sources inside this repo:

- `docs/ROI_REPORT.md`
- `docs/CODEX_USAGE_REPORT.md`
- `CODEX_REVIEW_FRONTEND.md`

### Opus 4.6 in Orchestra

Observed usage:

- Opus 4.6 is the default for orchestrators and most workers.
- 40 Opus 4.6 agents across local + VPS in the 5 May - 23 May 2026 reporting window.
- API-equivalent virtual cost: **$38,130** out of **$38,196** total, roughly 99.8% of virtual compute.
- 19 days of operation, 49 AI agents, 15 projects, 27,322 logged tool calls, 1,188 subagent spawns.

Strengths we actually use:

- Stable long-running sessions.
- Full Orchestra MCP tool access: `send_message`, `task_update`, worker orchestration, background jobs, file delivery.
- Works as orchestrator and worker, not only as a model call.
- Handles broad, ambiguous product/code tasks with less explicit scaffolding.
- Strong at planning, decomposition, tool use, and continuing work across messy project state.

Weaknesses:

- Expensive at API-equivalent pricing.
- Can miss adversarial security bugs in code it or another Claude worker just wrote.
- Sometimes overconfident after a plausible local fix.
- High/max effort can be slow and costly.

### GPT-5.5 in Orchestra

Observed usage:

- 4 standalone Codex sessions, only **$14.79** virtual cost.
- Main useful path is `codex-review`: Claude worker invokes `codex exec`, captures stdout, writes/reports the review.
- `docs/CODEX_USAGE_REPORT.md` records **~38 unique review reports** and **8 P0 + 6+ P1/high** findings.

Confirmed high-value findings:

- SSRF in `image_antidetect`.
- Stored XSS via AI response.
- XSS through Leaflet popup.
- Open redirect after login.
- `python_exec` sandbox bypass.
- Open redirect via shortlinks.
- ARI password in tracked source/logged URL.
- Mock payment in production when YooKassa keys are missing.
- Tariff-depth bypass, IDOR by surname, payment webhook race, SQL injection / unsafe LLM SQL patterns.

Strengths:

- Deep, systematic code review.
- Good P0/P1 severity ranking.
- Strong adversarial thinking: tries bypasses after a proposed fix.
- Excellent iterative review behavior: import-7m had 6 review rounds with fix tracking.
- Strong on security, payment logic, sandboxing, race conditions, dead code/call graph checks.

Weaknesses in our current integration:

- Standalone Codex lacks working Orchestra MCP delivery: no reliable `send_message`, no `task_update`.
- Results can be lost if written to `/tmp` or if auto-report fails.
- Timeout/reconnect issues were frequent in standalone sessions.
- Cannot be trusted as orchestrator until delivery, task state, branch management, and tool access are solved.
- As subprocess reviewer, it depends on Claude worker to feed context and preserve results.

---

## 4. Where Each Model Is Better

### Use Opus 4.6 for

1. **Orchestrators.** Needs MCP, task state, worker coordination, Telegram delivery, and long-running continuity.

2. **Primary workers.** Implementation work needs branch discipline, commits, file edits, tests, and direct reporting.

3. **Ambiguous product/architecture work.** Opus is better in our stack when the task requires finding the shape of the system, decomposing work, choosing tradeoffs, and keeping broad project context.

4. **Long-context project memory.** 1M context is materially useful for large docs/logs and multi-turn agent state.

5. **Tool-heavy workflows.** Claude Code's MCP integration is mature and already matches Orchestra's control plane.

6. **User-facing continuation.** Opus workers can report, ask the orchestrator, update progress, and finish with commits.

### Use GPT-5.5 for

1. **Adversarial code review.** Especially P0/P1 classes: auth, payments, entitlement, SSRF, XSS, IDOR, sandboxing, file/network access.

2. **Second opinion on Opus output.** GPT-5.5 should review code written by Opus and plans written by Opus before merge.

3. **Multi-round fix verification.** After Claude fixes a bug, GPT-5.5 should rerun with "try to bypass this fix" framing.

4. **Security audit packs.** Give it diff + relevant callers + route/auth context + deployment assumptions; require P0/P1/P2 output.

5. **Terminal/devops-style isolated diagnosis.** Public Terminal-Bench signals and our reviews suggest it is strong when scoped tightly.

6. **Regression-risk review before deploy.** It is good at spotting stale async, race conditions, missing URL encoding, and control-plane edge cases.

### Avoid GPT-5.5 for now

1. **Main orchestrator replacement.** Missing reliable Orchestra MCP/delivery in our path is a hard blocker.

2. **Autonomous standalone workers.** Until Codex can commit, report, update task state, and coordinate reliably, it creates operational drag.

3. **Very large whole-repo sessions through Codex CLI.** The observed 258.4K practical context issue makes this less safe than Opus 1M.

4. **Tasks where result delivery matters more than critique.** A brilliant review that does not reach the orchestrator is not useful.

---

## 5. Should We Combine Them?

Yes. The combination is the point.

Recommended workflow:

```text
Opus orchestrator
  -> assigns implementation to Opus worker
  -> worker commits candidate change
  -> worker runs tests
  -> worker invokes GPT-5.5 via codex-review
  -> GPT-5.5 produces adversarial review
  -> Opus worker fixes or documents findings
  -> GPT-5.5 re-reviews high-risk fixes
  -> Opus worker reports DONE with links and commit
```

Mandatory GPT-5.5 review gates:

- Payment/entitlement changes.
- Auth/session/cookie changes.
- Any public URL fetch/download/proxy/image endpoint.
- Any sandbox/code execution feature.
- Any SQL generated from user input or LLM output.
- Background jobs, command execution, SSH, subprocess, file write paths.
- Data migrations and idempotency-sensitive importers.
- Task state, payment ledger, balance, billing, or irreversible user data updates.

Useful review prompt shape:

```text
Review this diff as an adversarial security and correctness reviewer.
Focus on P0/P1 only first: data loss, auth bypass, payment bypass,
SSRF, XSS, IDOR, command execution, sandbox escape, race conditions.
For each finding include: impact, exact code path, exploit sketch,
why existing checks fail, and minimal fix.
Then list P2/P3 separately.
```

---

## 6. Should GPT-5.5 Become the Main Model?

**No, not yet.**

GPT-5.5 may be competitive or ahead on some raw coding benchmarks, but Orchestra is not a benchmark harness. It is a multi-agent operating environment. The main model must:

- keep long-running state;
- use Orchestra MCP tools;
- report reliably;
- update task/payment/project state;
- manage worktrees and commits;
- coordinate with other workers;
- survive context transitions;
- continue after interruptions.

Opus 4.6 already does those things. GPT-5.5 via Codex subprocess does not.

The only scenario where GPT-5.5 becomes a candidate for primary workers is after we implement a real Codex backend with:

- persistent app-server or equivalent session lifecycle;
- Orchestra MCP injection or a reliable REST callback bridge;
- first-class `send_message`, `task_update`, `update_progress`;
- worktree-safe git operations and required commits;
- durable output files in repo, not `/tmp`;
- test dependency bootstrap;
- clear handling of Codex context window and compaction;
- monitoring for timeouts/reconnects.

Even then, the likely best architecture is not "replace Opus". It is model routing:

| Role | Default model |
|---|---|
| Orchestrator | Opus 4.6 / newer Opus |
| Broad implementation worker | Opus 4.6 or Sonnet 4.6 depending risk/cost |
| Focused code review | GPT-5.5 |
| Security/payment/sandbox review | GPT-5.5 mandatory |
| Long-context research/planning | Opus 1M |
| Cheap bulk tasks | Sonnet/mini tier after task-specific eval |

---

## 7. Decision

**Keep Opus as the main Orchestra runtime. Do not switch the main model to GPT-5.5.**

**Promote GPT-5.5 from optional reviewer to required adversarial reviewer for high-risk code.** This is the highest ROI change because it directly targets the failure mode we have observed: Opus can implement a plausible fix and still miss the exploit path.

**Next engineering step:** improve the `codex-review` pipeline, not standalone Codex orchestration:

1. Standardize review prompts by risk class.
2. Require review artifacts under `docs/<task>/CODEX_REVIEW.md`.
3. Add a worker checklist: tests pass, Codex P0/P1 clear, unresolved findings documented.
4. Add a second GPT-5.5 review round after fixes for P0/P1 findings.
5. Later, build Codex backend/MCP bridge if we want GPT workers, but do not block current value on that.

---

## Sources

External:

- Anthropic, [Introducing Claude Opus 4.6](https://www.anthropic.com/news/claude-opus-4-6) — release, capabilities, 1M context, pricing, effort controls.
- Anthropic, [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing) — current long-context and batch pricing.
- Anthropic, [Claude Code MCP docs](https://code.claude.com/docs/en/mcp) — Claude Code MCP/tool integration.
- OpenAI, [GPT-5.5 model docs](https://developers.openai.com/api/docs/models/gpt-5.5) — context, output, price, reasoning effort.
- OpenAI, [API pricing](https://openai.com/api/pricing/) — current GPT-5.5 and GPT-5.4 API prices.
- OpenAI, [Introducing GPT-5.5](https://openai.com/index/introducing-gpt-5-5/) — Codex availability, Fast mode, evals.
- OpenAI, [MCP and Connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp) — Responses API MCP/connectors support.
- GitHub issue, [GPT-5.5 reports 258400 context window in Codex](https://github.com/openai/codex/issues/19319) — observed Codex context discrepancy.
- marc0.dev, [SWE-Bench Leaderboard May 2026](https://www.marc0.dev/en/leaderboard) — public aggregator; use with caution because scores mix self-reported and scaffold-dependent results.

Internal:

- [CODEX_USAGE_REPORT.md](./CODEX_USAGE_REPORT.md)
- [ROI_REPORT.md](./ROI_REPORT.md)
- [CODEX_REVIEW_FRONTEND.md](../CODEX_REVIEW_FRONTEND.md)
