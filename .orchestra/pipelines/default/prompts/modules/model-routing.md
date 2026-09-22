<model-routing>
## Model routing — which class to pass to `spawn_worker`
Choose in this order; quota arithmetic must not reverse the priority. **Luna is the ONLY Codex route**:
Astra and Sol are BANNED by the owner (20.09.2026, дословно: «во всей оркестре бан астра и сол поставь
ок только луна используем»). Ban enforced in the platform, not only here: both models have the agent
flag off, so `spawn_worker` and `change_worker_model` refuse them. Use Luna for everything that is not
covered by the Opus exception below. **Sonnet is the Claude-side analog of Luna** (owner, 22.09.2026:
«в клауди не только опус но и сонет использовать для простых задач… аналог луны в клауди»): the
same bounded tasks go to Sonnet whenever they run on Claude — in particular when the Codex pool is
exhausted. **Opus only for special complex tasks**; it is not the fallback for bounded work.

**Auxiliary model runs.** Inside an already approved task, extra Luna sessions used for evals,
controls, or review are auto-approved. Astra and Sol are unavailable for any of it — including
`codex exec`, a spawned evaluator, or a harness/provider call selecting them. If a task looks like it
needs a banned model, that is a question for the owner, not a route.

Do not write versioned model ids in this block or in `spawn_worker`. Pass a short alias
(`luna`, `sonnet`, `opus`, `spark`, `grok`); `spawn_worker` refuses a call without `model`. The
role default in `.orchestra/pipelines/<name>/pipeline.yaml` never reaches an agent-made spawn.
A copied id here goes stale; the manifest is the only owner.

This policy is driven by the asymmetry of consequences, not by price. **the Codex pool is meant to be burned** deliberately and to exhaustion: hitting Claude's weekly limit is painful because work stops, while hitting Codex is tolerable because we can fall back to Claude (Sonnet, or Opus for complex work) and continue. What decides this is the **cost of exhaustion, not the cost of spend**, so arithmetic about price cannot overturn it. Do not quote the old per-percentage-point comparison at all: it was measured against a $100 OpenAI plan, the plan was upgraded to $200 on 16.08 (`prolite → pro`), and the figure understated the current cost by roughly four times (#334). Percentages of a pool are not comparable across a tariff change — check the denominator before comparing them. On 22.09.2026 the owner deliberately moved Codex to Plus ($20): its published limit is 1/20 of the $200 Pro, and a single worker task can empty the 5-hour window, so expect the Sonnet fallback often. Reconsider this policy only with evidence about consequences.

- **Luna** — default for bounded tasks with a clear outcome and acceptance criteria. Provide relevant context and known checks; exact edit lines need not be prescribed. Answer clarification questions and let the worker correct ordinary implementation errors. Escalate for a demonstrated capability gap or lack of progress, not the first red test. Auxiliary-model authorization still applies.
- **Astra** — ЗАПРЕЩЕНА владельцем 20.09.2026. Не выбирать ни для исследований, ни для архитектуры, ни для замеров — ничего из прежней «сложной» полосы. Платформа отказывает сама: флаг agents снят, spawn и смена модели возвращают отказ. Что мы за неё платили, для понимания цены решения: один ход разбора 45 тулов 20.09 стоил $5.67 при 3.4 млн входных токенов — $1.67 за миллион против $0.02 у Luna в том же окне, то есть в 70 раз дороже за токен. Снять запрет может только владелец; ссылка на старую редакцию этого модуля основанием не является.
- **Sol** — ЗАПРЕЩЁН владельцем 20.09.2026 вместе с Astra. Не восстанавливать из старых копий промпта и не предлагать как более дешёвую замену. Прежний повод спросить о нём (экзаменационные задачи с инструментами) запретом снят.
- **Sonnet** — Luna's twin on Claude: bounded tasks with a clear outcome and acceptance criteria, same assignment and escalation rules as Luna. First trial (V-611, 22.09): one turn to DONE, both of the orchestrator's mutations reddened its test, $1.99 — ≈2.3× cheaper than the same tokens at Opus rates. Its share of the Claude subscription pool is not yet measured. Escalate to Opus for a demonstrated capability gap, not the first red test.
- **Opus** — use only for special complex tasks. It is the specialist for exceptional ambiguity, creative prose, images, or unusually demanding synthesis; it is not the default worker route.
- **Spark** — optional narrow fast/overflow leaf route with a separate but small quota wallet, not free capacity. At the current preview limit, #222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS). Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete. Use Spark only when the Codex pool is the binding constraint and all hold: text-only; ≤2 named files; ≤100K total initial context (system prompt + task + supplied files); every correctness-critical decision and value is explicit; an independent pre-existing oracle mechanically covers every correctness-critical criterion. Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route. At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption. The excluded classes are explicit: semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden. After any failed or incomplete Spark attempt, never retry Spark; hand the ticket to Luna; Astra and Sol забанены и заменой не являются.
- **Terra** — do not use.
- **Fable** — do not use.
- **Orchestrators** — when selecting a worker, apply the same priority above; the orchestrator role does not override it.
</model-routing>
