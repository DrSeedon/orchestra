<model-routing>
## Model routing — which model to pass to `spawn_worker`
Choose in this order; quota arithmetic must not reverse the priority. **Luna is the DEFAULT**: use
it for everything that is not covered by the Sol or Opus exceptions below. **Sol when the task is complex and Luna will not manage it**: complexity and Luna's expected inability are both required.
**Opus only for special complex tasks** in normal routing. If the Codex pool is exhausted, falling
back to Opus is the operational exception that keeps work moving.

This policy is driven by the asymmetry of consequences, not by price. **the Codex pool is meant to be burned** deliberately and to exhaustion: hitting Claude's weekly limit is painful because work stops, while hitting Codex is tolerable because we can fall back to Opus and continue. The calculation that a dollar of Codex consumes 4.8× more of its own pool than a dollar of Claude ($5.39 versus $25.67 per percentage point) is correct, but it does not imply moving work to Claude: it compares the **cost of exhaustion, not the cost of spend**. Reconsider this policy only with evidence about consequences, never with arithmetic about spend price.

- **Luna** (`gpt-5.6-luna`) — default for all work and the required choice for a CLOSED task. Before spawning, you must be able to name the file and line to change, the acceptance criteria, and the test command. Cannot name all three → the task is not closed. **On failure escalate, never retry:** if the named test command stays red or a criterion is not shown met by command output, hand the ticket to Sol and do not send it back to Luna. One closed ticket at a time; do not stretch it into a long multi-turn session. Long context ONLY for EXTRACTION — finding explicitly marked places in a large input. Resolving references across similar fragments goes to Sol.
- **Sol medium** (`gpt-5.6-sol`) — use only for a complex task that Luna will not manage: research, arguing with a review, architecture, empirical measurements/benchmarks, or long mechanical protocols and bulk edits where exact tool execution matters. A closed task that meets the Luna definition remains with Luna unless this complexity exception applies. Closed work goes to the `worker` role, never to `full-cycle`.
- **Opus 5** (`claude-opus-5[1m]`) — use only for special complex tasks, or as the fallback after Codex exhaustion described above. It is the specialist for exceptional ambiguity, creative prose, images, or unusually demanding synthesis; it is not the default worker route.
- **Spark** (`gpt-5.3-codex-spark`) — optional narrow leaf route only when the Codex pool is the binding constraint and all hold: text-only + ≤2 files + clear AC + explicit test command + context <128k. Spark never takes review work. It is not for research, architecture, vision, or security; a ticket needing a file outside the named ones goes to Sol.
- **Terra** — do not use.
- **Fable** — do not use.
- **Orchestrators** — when selecting a worker, apply the same priority above; the orchestrator role does not override it.
</model-routing>
