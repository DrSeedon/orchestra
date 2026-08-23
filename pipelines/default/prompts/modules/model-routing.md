<model-routing>
## Model routing — which class to pass to `spawn_worker`
Choose in this order; quota arithmetic must not reverse the priority. **Luna is the DEFAULT class**: use
it for everything that is not covered by the Sol or Opus exceptions below. **Sol when the task is complex and Luna will not manage it**: complexity and Luna's expected inability are both required.
**Opus only for special complex tasks** in normal routing. If the Codex pool is exhausted, falling
back to Opus is the operational exception that keeps work moving.

**Auxiliary model runs have their own authorization boundary.** Inside an already approved task,
extra Luna sessions used for evals, controls, or review are auto-approved. An additional Sol
session is never implied by approval of the parent task: this includes Sol review, `codex exec`,
a spawned Sol evaluator, and any harness/provider call selecting Sol. Start one only after the user
explicitly approves that additional Sol run. The assigned Sol worker's own continuation on its
current approved task is not an auxiliary run; the restriction is on extra Sol calls it launches.

Do not write versioned model ids in this block or in `spawn_worker`. Pass a short alias
(`luna`, `sol`, `opus`, `spark`, `grok`) or omit `model` — the role default lives in
`pipelines/<name>/pipeline.yaml`. A copied id here goes stale; the manifest is the only owner.

This policy is driven by the asymmetry of consequences, not by price. **the Codex pool is meant to be burned** deliberately and to exhaustion: hitting Claude's weekly limit is painful because work stops, while hitting Codex is tolerable because we can fall back to Opus and continue. What decides this is the **cost of exhaustion, not the cost of spend**, so arithmetic about price cannot overturn it. Do not quote the old per-percentage-point comparison at all: it was measured against a $100 OpenAI plan, the plan was upgraded to $200 on 16.08 (`prolite → pro`), and the figure understated the current cost by roughly four times (#334). Percentages of a pool are not comparable across a tariff change — check the denominator before comparing them. Reconsider this policy only with evidence about consequences.

- **Luna** — default for all work and the required choice for a CLOSED task. Before spawning, you must be able to name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is not closed. **On failure escalate, never retry:** if the named test command stays red or a criterion is not shown met by command output, hand the ticket to Sol and do not send it back to Luna. One closed ticket at a time; do not stretch it into a long multi-turn session. Long context ONLY for EXTRACTION — finding explicitly marked places in a large input. Resolving references across similar fragments goes to Sol.
- **Sol** — use only for a complex task that Luna will not manage: research, arguing with a review, architecture, empirical measurements/benchmarks, or long mechanical protocols and bulk edits where exact tool execution matters. A closed task that meets the Luna definition remains with Luna unless this complexity exception applies. Closed work goes to the `worker` role, never to `full-cycle`.
- **Opus** — use only for special complex tasks, or as the fallback after Codex exhaustion described above. It is the specialist for exceptional ambiguity, creative prose, images, or unusually demanding synthesis; it is not the default worker route.
- **Spark** — optional narrow fast/overflow leaf route with a separate but small quota wallet, not free capacity. At the current preview limit, #222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS). Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete. Use Spark only when the Codex pool is the binding constraint and all hold: text-only; ≤2 named files; ≤100K total initial context (system prompt + task + supplied files); every correctness-critical decision and value is explicit; an independent pre-existing oracle mechanically covers every correctness-critical criterion. Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route. At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption. The excluded classes are explicit: semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden. After any failed or incomplete Spark attempt, never retry Spark; hand the ticket to Luna or Sol by task class.
- **Terra** — do not use.
- **Fable** — do not use.
- **Orchestrators** — when selecting a worker, apply the same priority above; the orchestrator role does not override it.
</model-routing>
