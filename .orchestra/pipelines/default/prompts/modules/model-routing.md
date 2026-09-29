<model-routing>
## Model routing — which class to pass to `spawn_worker`
Choose in this order; quota arithmetic must not reverse the priority. **Luna is the ONLY Codex route**:
Astra and Sol are BANNED by the owner (20.09.2026, дословно: «во всей оркестре бан астра и сол поставь
ок только луна используем»). Ban enforced in the platform, not only here: both models have the agent
flag off, so `spawn_worker` and `change_worker_model` refuse them. Use Luna for everything that is not
covered by the Opus exception below. **On Claude, Sonnet 5.5 is the default for all worker work**
(owner, 29.09.2026: «сонет 5.5 можно давать более трудные»), including hard tasks with an
understandable mechanism; **Opus 5.5 only for work known in advance to be heavy**: hard open
research, architecture, large tangled systems, nasty bugs. Choose the model only — the effort
level is fixed per model in the pipeline (Sonnet 5.5 medium, Opus 5.5 medium); do not
pick max. Basis: `.orchestra/kb/models-and-quotas.md`, section «Sonnet 5.5 против Sonnet 5 и Opus 5.5»
— over two rounds on five hard Orchestra tasks (.orchestra/tasks/V-667/report.md) Sonnet 5.5 medium scored 3.9/5 vs Opus 5.5 3.6
(medium) / 3.9 (high) with ~2× less output; a single run does not separate the models.

**Auxiliary model runs.** Inside an already approved task, extra Luna sessions used for evals,
controls, or review are auto-approved. Astra and Sol are unavailable for any of it — including
`codex exec`, a spawned evaluator, or a harness/provider call selecting them. If a task looks like it
needs a banned model, that is a question for the owner, not a route.

Do not write versioned model ids in this block or in `spawn_worker`. Pass a short alias
(`luna`, `sonnet`, `opus`, `spark`, `grok`); `spawn_worker` refuses a call without `model`. The
role default in `.orchestra/pipelines/<name>/pipeline.yaml` never reaches an agent-made spawn.
A copied id here goes stale; the manifest is the only owner.

This policy is driven by the asymmetry of consequences, not by price. **the Codex pool is meant to be burned** deliberately and to exhaustion: hitting Claude's weekly limit is painful because work stops, while hitting Codex is tolerable because we can fall back to Claude (Sonnet, or Opus for complex work) and continue. What decides this is the **cost of exhaustion, not the cost of spend**, so arithmetic about price cannot overturn it. Do not quote the old per-percentage-point comparison at all: it was measured against a $100 OpenAI plan, the plan was upgraded to $200 on 16.08 (`prolite → pro`), and the figure understated the current cost by roughly four times (#334). Percentages of a pool are not comparable across a tariff change — check the denominator before comparing them. On 22.09.2026 the owner deliberately moved Codex to Plus ($20, источник: https://chatgpt.com/codex/pricing/): its published limit is 1/20 of the $200 Pro, and a single worker task can empty the 5-hour window, so expect the Sonnet fallback often. Reconsider this policy only with evidence about consequences.

- **Luna** — с 23.09.2026 это GPT-6 Luna (владелец: «луна 6 рабочая лошадка вместо 5.6»): на замере .orchestra/tasks/V-620/bench-models.md та же задача сделана за $0.26 против $0.57 у 5.6, с сохранением основания закрытия и перепроверкой ветки под блокировкой репозитория. Прежняя доступна как `luna5.6`. Default for bounded tasks with a clear outcome and acceptance criteria. Provide relevant context and known checks; exact edit lines need not be prescribed. Answer clarification questions and let the worker correct ordinary implementation errors. Escalate for a demonstrated capability gap or lack of progress, not the first red test. Auxiliary-model authorization still applies.
- **Astra** — ЗАПРЕЩЕНА владельцем 20.09.2026. Не выбирать ни для исследований, ни для архитектуры, ни для замеров — ничего из прежней «сложной» полосы. Платформа отказывает сама: флаг agents снят, spawn и смена модели возвращают отказ. Что мы за неё платили, для понимания цены решения: один ход разбора 45 тулов 20.09 стоил $5.67 при 3.4 млн входных токенов (источник: .orchestra/tasks/V-601/tools-redesign.md) — $1.67 за миллион против $0.02 у Luna в том же окне, то есть в 70 раз дороже за токен. Снять запрет может только владелец; ссылка на старую редакцию этого модуля основанием не является.
- **Sol** — ЗАПРЕЩЁН владельцем 20.09.2026 вместе с Astra; запрет подтверждён 23.09 и после выхода GPT-6 Sol (алиас `sol` теперь указывает на него, флаг agents снят, платформа отказывает). На замере 23.09 (.orchestra/tasks/V-620/bench-models.md) GPT-6 Sol дешевле предшественника ($4.32 против $6.44), но хранит основание закрытия задачи в служебном kv, откуда его не восстановить из Git, — качеством запрет не отменяется. Не восстанавливать из старых копий промпта и не предлагать как более дешёвую замену. Прежний повод спросить о нём (экзаменационные задачи с инструментами) запретом снят.
- **Sonnet 5.5 (medium) — the default worker.** Measured equal to Opus on our work (29.09, 8 Orchestra tasks, 74 runs, .orchestra/tasks/V-667/report.md, V-670, V-671): bug fixes and features with an understandable mechanism, session/delivery lifecycle (lost steer V-562: 5/5, cost baseline V-609, silence signal V-642, in-session compaction V-650: 5/5), research and reports, docs, frontend. Uses ~2× less output than Opus for the same score (16K vs 35K per task) and finishes faster. Weak spots seen: on low it may replace a real check with a stub; on medium it sometimes stops at the minimum set of tests — state the required checks in the task.
- **Opus 5.5 (medium) — only where it was measurably better; do not pick it "to be safe":**
  - a defect with several hidden causes, concurrency and ownership races (pidfd leak V-543: only Opus found the cancelled-receive race and split close-vs-kill ownership; Sonnet on every effort patched just the visible path);
  - a large cross-module restructure or data migration (project catalog V-621, .orchestra/tasks/V-671/report.md: Opus 5/5/4 vs Sonnet 4/4/3, and Opus closed a follow-up the original work needed later);
  - open-ended architecture or research with no known mechanism, creative prose, images, unusually demanding synthesis;
  - work where one wrong action is expensive (destructive operations, shared infrastructure): Opus 5.5 is the least destructive model per Anthropic's system card and asks for permission more often.
  Orchestrators stay on Opus until the owner decides otherwise.
- **Spark** — optional narrow fast/overflow leaf route with a separate but small quota wallet, not free capacity. At the current preview limit, #222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS). Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete. Use Spark only when the Codex pool is the binding constraint and all hold: text-only; ≤2 named files; ≤100K total initial context (system prompt + task + supplied files); every correctness-critical decision and value is explicit; an independent pre-existing oracle mechanically covers every correctness-critical criterion. Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route. At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption. The excluded classes are explicit: semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden. After any failed or incomplete Spark attempt, never retry Spark; hand the ticket to Luna; Astra and Sol забанены и заменой не являются.
- **Terra** — do not use.
- **Fable** — do not use.
- **Orchestrators** — when selecting a worker, apply the same priority above; the orchestrator role does not override it.
</model-routing>
