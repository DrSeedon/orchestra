# #389 — курс Vercel Agent Harness против runtime Orchestra

Дата: 24.08.2026. Только исследование. Реализация, Vercel deployment и provider calls не
выполнялись.

Источник: [Build Your Own AI Coding Agent Harness](https://vercel.com/academy/build-ai-agent-harness),
38 уроков, 11 модулей. Проверены curriculum и ключевые уроки по pruning, cache control,
approval, sandbox lifecycle, verification и extensibility.

## Вердикт

Курс **полезен как аудит-чеклист и объяснение архитектуры**, но не как основа переписывания.
Наш runtime уже закрывает примерно 7 из 11 модулей и в нескольких местах существенно глубже.
Копировать TeensyCode, Vercel AI SDK или TypeScript stack не нужно.

Курс нашёл четыре полезных направления:

1. **Критично:** собственный policy/approval boundary вокруг inner harness tools.
2. **Высоко:** измеренный ранний pruning старых tool results вместо аварийного усечения только
   при 85% контекста.
3. **Средне:** project-aware verification discovery и server-backed scoped claims.
4. **Позже:** Sandbox interface, но только когда появится второй реальный execution backend.

## Что у нас уже есть

Текущий runtime:

- app/backend_harness.py — persistent backend, cumulative usage/cost, mid-turn injection,
  reconnect, JSONL session, best-of-N, effort routing;
- app/harness/loop.py — OpenAI-compatible tool loop, streamed reasoning/tool fragments,
  matching tool results, abort safety, 100-round ceiling, visible context truncation,
  read-only review subloop;
- app/harness/tools.py — bash/read/write/edit/glob/grep, workspace path boundary, per-agent UID
  for bash, bounded output/read, syntax checks, atomic edit/write;
- app/harness/mcp.py — persistent MCP stdio clients, tool registry, reconnect and collision
  detection;
- app/harness/sessions.py — append-only crash-tolerant JSONL sessions;
- app/harness/bestofn.py — test-gated attempts with guarded rollback;
- app/harness/llm.py — streaming OpenRouter client, retry-before-first-byte, reasoning details,
  per-round usage and parallel tool calls.

Production harness code is about 2,555 lines plus backend; 32 directly named harness tests are
collected, with additional OpenRouter/runtime tests elsewhere.

## Exact mapping of the 11 course modules

| Vercel module | Orchestra today | Decision |
|---|---|---|
| 1. Agent Loop | Implemented deeper: streaming SSE, partial tool-call assembly, fail-soft invalid JSON, abort and terminal metadata. | Nothing to import. |
| 2. Tool Design | Tools are bounded and #367 fixed 10 lying defects. Descriptions remain compact; no approval config/interceptor. | Approval boundary is critical; 5-section descriptions only A/B test. |
| 3. System Prompt | Full role/module/skill pipeline and AGENTS sync already exist outside harness. | Course prompt is far simpler; no rewrite. |
| 4. Sandbox Abstraction | Built-ins call local fs/subprocess directly; outer Orchestra supplies worktree and UID isolation. | Add interface only with a second approved backend. No Vercel dependency now. |
| 5. Context Management | Output caps exist; fit_context drops middle only above 85%, keeps system + 8 recent messages, uses chars/3.5. No explicit cache body/session ID. | Best immediate performance experiment. |
| 6. Subagent Delegation | Outer Orchestra has durable workers/tasks/worktrees; inner harness has a structural read-only reviewer. | Do not add hidden explorer/executor loops that bypass receipts/tasks. |
| 7. Sandbox Lifecycle | Outer manager/systemd/restart/FD handoff owns lifecycle; harness hibernate=false. | Snapshot/restore only when remote sandbox exists. Reuse idempotency lessons. |
| 8. Human-in-the-Loop | User can answer through dashboard/TG, but inner tool loop has no durable approval pause. | Real server-owned approval is missing and important. Course askUser string is insufficient. |
| 9. Planning & Verification | todo_write, full-cycle gates, task acceptance, merge gates and best-of-N exist. | Dynamic gate discovery/scoped claims useful, but evidence must be executable, not prompt-only. |
| 10. Surfaces | Dashboard, Telegram, SSE and MCP already exceed the course CLI/TUI/web sketch. | Nothing to import. |
| 11. Extensibility | MCP is the external tool registry; skills already use progressive disclosure. General event bus absent. | Start with one narrow pre-tool policy seam, not a universal bus. |

## Главная находка: inner tools обходят policy boundary

Course Module 2/8 correctly separates:

- operational mode: interactive/background/delegated;
- per-call policy: inspect exact tool name + payload, then allow/block/modify.

Текущий app/harness/tools.py выполняет bash/write/edit напрямую. Он ограничивает path и может
drop UID для bash, но не имеет:

- approval mode;
- protected-file policy;
- destructive-command classification;
- network/credential policy;
- durable allow/deny receipt;
- structured pause and resume after user approval.

Outer Orchestra prompt/hook не является достаточной защитой: inner OpenRouter model вызывает
builtin harness tool внутри Python loop, а не внешний Claude/Codex tool call. Значит внешний
PreToolUse/can_use_tool эту операцию механически не видит.

Course's first SAFE_PREFIXES example копировать нельзя: prefix allowlist легко обойти shell
composition, redirection, aliases and nested interpreters. Полезен не список, а **место enforcement**.

### Правильный Orchestra-контракт

Перед dispatch каждого builtin/MCP tool:

1. создать typed ToolIntent с session/turn/round/tool/payload/cwd/actor/mode;
2. применить server-owned policy;
3. allow → исполнить и записать receipt;
4. deny → вернуть честный tool_result и receipt;
5. needs_approval → durable pending approval, остановить loop без dangling tool call;
6. user response → resume того же intent exactly once.

Reviewer readonly restriction уже структурная и остаётся отдельным более сильным профилем.

## Context management: полезно, но только через эксперимент

Vercel предлагает удалять tool call/result pairs старше последних трёх сообщений перед каждым
model call. Наш runtime вместо этого ждёт 85% context guard, затем одним ударом оставляет system
и восемь последних messages. Оба числа — эвристики.

Потенциальная польза курса:

- input curve перестаёт расти задолго до emergency guard;
- старые тяжёлые tool outputs не перечитываются каждый round;
- меньше context rot;
- system/initial prompt отделяются от dynamic tail.

Риск: coding task часто зависит от найденного 10–20 rounds назад символа, test error или file
path. Blind last-three pruning может резко ухудшить task success. Он также не сохраняет summary
или evidence references.

### Нужный пилот

- frozen tasks: multi-file fix, long investigation, repeated test/debug;
- A/A first, затем current vs prune-old-tool-results;
- interleaved runs;
- metrics: task AC, tool rounds, prompt tokens, dropped evidence, re-read calls, latency;
- candidates: keep 3/5/8 conversation messages; externalize large tool result with stable ref;
- mutation: удалённый старый result должен требоваться хотя бы одному task, иначе тест вакуумный.

Не менять production по одному примеру Vercel.

## Cache control

OpenRouter официально поддерживает sticky prompt routing и prompt cache metrics
prompt_tokens_details.cached_tokens/cache_write_tokens. Для Anthropic-style endpoints можно
передать top-level cache_control; многие другие providers кешируют автоматически.

Но наш harness route использует бесплатные OpenRouter models, где главная квота — число HTTP calls,
а не оплаченные input tokens. Prompt caching не уменьшает число tool rounds/HTTP calls. Поэтому:

- сначала логировать cache metrics и явный session_id;
- не добавлять provider-specific cache_control без capability check;
- не выдавать виртуальную dollar savings за расширение free request quota;
- response caching не использовать для agent tool loops: повтор одинакового запроса может
  воспроизвести старый tool call в изменившемся workspace.

## Verification: идея полезна, пример курса слишком доверчив

Course discovers typecheck/lint/test/build from package.json and требует отличать caused от
pre-existing failures. Это хорошая формулировка, но prompt сам по себе не доказывает
pre-existing ownership.

У Orchestra уже есть более сильные primitives:

- acceptance_command/manifest tied to task revision;
- merge acceptance gate;
- target-aware regression mapping #386;
- frozen RED oracles and mutation checks;
- rule to compare against main/type commit.

Полезно добавить automatic discovery только как candidate command list. Verdict должен строиться
server-side из exact command, commit and baseline, а не из заявления модели.

## Sandbox abstraction

Course's Sandbox interface хорошо отделяет tools от local/Vercel/just-bash implementations. У нас
эта граница отсутствует: builtin functions принимают cwd и работают с локальной машиной.

Сейчас рефакторинг не окупится:

- второго execution backend нет;
- worktree + UID already give local isolation;
- Vercel Sandbox/Workflow создают vendor/runtime/credential stack;
- OpenRouter free models и Orchestra subscriptions не требуют Vercel AI Gateway.

Когда будет одобрен container/remote runtime, сначала определить наш interface:
read/write/edit/exec/stat/snapshot/stop + identity/generation/receipt. Затем реализовать local
adapter без behavioral change и только после него второй backend.

## Что не брать

- TypeScript rewrite и Vercel ToolLoopAgent;
- AI Gateway вместо текущего model routing;
- just-bash как production security boundary;
- Vercel Workflow вместо bg jobs/systemd lifecycle;
- inner executor/explorer subagents, обходящие Orchestra task/worktree receipts;
- общий event bus до появления двух независимых потребителей;
- keyword/prefix risk score как окончательный shell policy;
- prompt-only statement «failure pre-existing» без baseline proof.

## Приоритет тикетов

1. **P0 — Harness tool policy + durable approval seam.**
   Security/correctness; проверяет exact payload; deny/approve resume без dangling tools.
2. **P1 — Context pruning/caching telemetry experiment.**
   Сначала измерение; production behavior только после task-success gate.
3. **P2 — Verification discovery adapter.**
   Candidate commands feed existing task/merge acceptance, не новый prompt-only verdict.
4. **P3 — Sandbox interface ADR.**
   Отложить до решения о втором backend.
5. **Skip — Vercel stack migration.**

## Confidence

- Curriculum and course contracts: confirmed from official Vercel Academy.
- Current harness feature mapping: confirmed from current app code and #367 artifacts.
- Missing inner-tool policy boundary: confirmed by repository-wide grep and dispatch path.
- Pruning benefit: likely on tokens/context, effect on task success uncertain.
- Need for Vercel SDK/Sandbox/Workflow: low; no current problem requires them.

## Sources

- https://vercel.com/academy/build-ai-agent-harness
- https://vercel.com/academy/build-ai-agent-harness/pruning-old-results
- https://vercel.com/academy/build-ai-agent-harness/cache-control
- https://vercel.com/academy/build-ai-agent-harness/approval-config
- https://vercel.com/academy/build-ai-agent-harness/snapshot-and-restore
- https://vercel.com/academy/build-ai-agent-harness/verification-contract
- https://vercel.com/academy/build-ai-agent-harness/extension-points
- https://openrouter.ai/docs/guides/best-practices/prompt-caching
- app/backend_harness.py; app/harness/*.py; tests/test_harness*.py
- docs/tasks/367/research.md; docs/tasks/367/report.md; docs/kb/harness-tools.md
