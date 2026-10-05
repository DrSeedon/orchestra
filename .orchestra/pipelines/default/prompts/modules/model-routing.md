<model-routing>
## Model routing — which class to pass to `spawn_worker`
Choose in this order; quota arithmetic must not reverse the priority. **Luna is the ONLY Codex route**:
Astra and Sol are BANNED by the owner (2026-09-20). Ban enforced in the platform, not only here: both models have the agent
flag off, so `spawn_worker` and `change_worker_model` refuse them. Use Luna for everything that is not
covered by the Opus exception below. **On Claude, Sonnet 5.5 is the default for all worker work**
(owner decision, 2026-09-29), including hard tasks with an
understandable mechanism; **Opus 5.5 only for work known in advance to be heavy**: hard open
research, architecture, large tangled systems, nasty bugs. Choose the model only — the effort
level is fixed per model in the pipeline (Sonnet 5.5 medium, Opus 5.5 medium); do not
pick max. Basis: `.orchestra/kb/models-and-quotas.md`, section "Sonnet 5.5 versus Sonnet 5 and Opus 5.5"
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

This policy is driven by the asymmetry of consequences, not by price. **the Codex pool is meant to be burned** deliberately and to exhaustion: hitting Claude's weekly limit is painful because work stops, while hitting Codex is tolerable because we can fall back to Claude (Sonnet, or Opus for complex work) and continue. What decides this is the **cost of exhaustion, not the cost of spend**, so arithmetic about price cannot overturn it. Do not quote the old per-percentage-point comparison at all: it was measured against a $100 OpenAI plan, the plan was upgraded to $200 on 16.08 (`prolite → pro`), and the figure understated the current cost by roughly four times (#334). Percentages of a pool are not comparable across a tariff change — check the denominator before comparing them. On 22.09.2026 the owner deliberately moved Codex to Plus ($20, source: https://chatgpt.com/codex/pricing/): its published limit is 1/20 of the $200 Pro, and a single worker task can empty the 5-hour window, so expect the Sonnet fallback often. Reconsider this policy only with evidence about consequences.

- **Luna** — since 2026-09-23 this is GPT-6 Luna (owner decision: Luna 6 is the primary workhorse instead of 5.6): on `.orchestra/tasks/V-620/bench-models.md`, the same task cost $0.26 versus $0.57 on 5.6, while preserving the closure basis and rechecking the branch under repository lock. The previous model remains available as `luna5.6`. Default for bounded tasks with a clear outcome and acceptance criteria. Provide relevant context and known checks; exact edit lines need not be prescribed. Answer clarification questions and let the worker correct ordinary implementation errors. Escalate for a demonstrated capability gap or lack of progress, not the first red test. Auxiliary-model authorization still applies.
- **Astra** — BANNED by the owner on 2026-09-20. Do not choose it for research, architecture, measurements, or anything from the former complexity route. The platform rejects it: the agents flag is off, and spawn/model changes fail. The decision's cost is recorded for context: one 45-tool analysis turn on 2026-09-20 cost $5.67 for 3.4M input tokens (source: `.orchestra/tasks/V-601/tools-redesign.md`) — $1.67 per million versus Luna's $0.02 in the same window, 70 times more per token. Only the owner can lift the ban; an old module revision is not authority.
- **Sol** — BANNED by the owner on 2026-09-20 together with Astra; the ban was confirmed on 2026-09-23 after GPT-6 Sol shipped (alias `sol` now points to it, the agents flag is off, and the platform rejects it). In the 2026-09-23 measurement (`.orchestra/tasks/V-620/bench-models.md`), GPT-6 Sol was cheaper than its predecessor ($4.32 versus $6.44) but stored the task closure basis in service kv that cannot be recovered from Git; quality does not lift the ban. Do not restore it from old prompt copies or offer it as a cheaper replacement. The former reason to ask about it (tool-use exam tasks) is also covered by the ban.
- **Sonnet 5.5 (medium) — the default worker.** Measured equal to Opus on our work (29.09, 8 Orchestra tasks, 74 runs, .orchestra/tasks/V-667/report.md, V-670, V-671): bug fixes and features with an understandable mechanism, session/delivery lifecycle (lost steer V-562: 5/5, cost baseline V-609, silence signal V-642, in-session compaction V-650: 5/5), research and reports, docs, frontend. Uses ~2× less output than Opus for the same score (16K vs 35K per task) and finishes faster. Weak spots seen: on low it may replace a real check with a stub; on medium it sometimes stops at the minimum set of tests — state the required checks in the task.
- **Opus 5.5 (medium) — only where it was measurably better; do not pick it "to be safe":**
  - a defect with several hidden causes, concurrency and ownership races (pidfd leak V-543: only Opus found the cancelled-receive race and split close-vs-kill ownership; Sonnet on every effort patched just the visible path);
  - a large cross-module restructure or data migration (project catalog V-621, .orchestra/tasks/V-671/report.md: Opus 5/5/4 vs Sonnet 4/4/3, and Opus closed a follow-up the original work needed later);
  - open-ended architecture or research with no known mechanism, creative prose, images, unusually demanding synthesis;
  - **owner decision, 2026-10-05:** production of educational/explanatory videos, including narrated 3D scenes (V-723: the vessels in Luna's scene collided, both Sol runs overloaded, Sonnet and Opus were good, and Opus alone checked facts against primary sources). Automated checks do not replace semantic viewing of the scene (sources: `.orchestra/kb/models-and-quotas.md`, `.orchestra/tasks/V-731/report.md`);
  - work where one wrong action is expensive (destructive operations, shared infrastructure): Opus 5.5 is the least destructive model per Anthropic's system card and asks for permission more often.
  Orchestrators stay on Opus until the owner decides otherwise.
- **Spark** — optional narrow fast/overflow leaf route with a separate but small quota wallet, not free capacity. At the current preview limit, #222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS). Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete. Use Spark only when the Codex pool is the binding constraint and all hold: text-only; ≤2 named files; ≤100K total initial context (system prompt + task + supplied files); every correctness-critical decision and value is explicit; an independent pre-existing oracle mechanically covers every correctness-critical criterion. Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route. At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption. The excluded classes are explicit: semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden. After any failed or incomplete Spark attempt, never retry Spark; hand the ticket to Luna; Astra and Sol are banned and are not substitutes.
- **Terra** — do not use.
- **Fable** — do not use.
- **Orchestrators** — when selecting a worker, apply the same priority above; the orchestrator role does not override it.
</model-routing>
