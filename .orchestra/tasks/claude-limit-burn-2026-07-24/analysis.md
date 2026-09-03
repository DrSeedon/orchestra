# Claude/Codex limits: 14-day burn analysis

Snapshot time: **2026-07-24 11:31–11:36 Asia/Krasnoyarsk**.

## Verdict

Claim: «Claude 5h начал сгорать всё быстрее».

**Verdict: 🔶 MIXED.** Последний burst действительно жёсткий: 0→100% за
2ч52м от начала session window. Но это ровно медиана семи полностью выгоревших
окон за 14 дней, не новый рекорд. Самое быстрое окно сгорело за 2ч00м
2026-07-21. По всем окнам вторая неделя в среднем легче первой; проблема —
повторяющиеся concurrent bursts, а не монотонное ускорение.

## Current limits

| Provider / limit | Used | Reset, local | State |
|---|---:|---|---|
| Claude 5h session | **100%** | 2026-07-24 13:40 | hard-blocked |
| Claude 7d all models | **35%** | 2026-07-28 14:00 | normal |
| Claude Fable scoped weekly | 0% | no active reset | unused |
| Claude usage credits | 0%, disabled | — | no overage fallback |
| Codex primary 7d | **9%** | 2026-07-30 17:25 | 91% free |
| Codex Spark 7d | **0%** | inactive window | unused |

Spark's API reset timestamp tracks `now + 7d` while utilization is zero, so it
is not a meaningful fixed reset until Spark is actually used.

The current Claude weekly window went from 0% on 2026-07-21 14:00 to 35% in
2d21h. A naive linear projection is ~86% by reset, but bursty usage makes that
projection uncertain. The previous complete weekly window peaked at 81%; the
partially observed prior window reached 100%.

## Current 5h burn

Window: **08:40 → 13:40 local**.

| Time | Claude 5h | Claude 7d |
|---|---:|---:|
| 09:37 | 0% | 26% |
| 09:42 | 11% | 28% |
| 10:07 | 50% | 31% |
| 10:33 | 64% | 32% |
| 10:56 | 65% | 32% |
| 11:21 | 74% | 33% |
| 11:26 | 86% | 33% |
| 11:31 | **100%** | **35%** |

The apparent 0→11 jump does not mean the session started at 09:42. The reset
time fixes its start at 08:40. Usage is reflected after long turns complete, so
the dashboard can remain flat and then jump. Wall-clock time to cap was 172
minutes; time from first non-zero observation was 109 minutes.

During this window Orchestra logged **$29.67 API-equivalent virtual turn cost**
and roughly 267 agentic turns across four Claude sessions:

| Session | Model | Virtual turn cost | Agentic turns | Share of virtual cost |
|---|---|---:|---:|---:|
| `research-models` | Opus 4.8 | $10.21 | 38 | 34.4% |
| `seedon-orchestrator` | Opus 4.6 | $8.48 | 123 | 28.6% |
| `Orchestra-orchestrator` | Opus 4.6 | $7.05 | 69 | 23.8% |
| `COG-second-brain-orchestrator` | Opus 4.6 | $3.93 | 37 | 13.2% |

Virtual API cost is useful for attribution but is not billing and does not map
linearly to subscription percentage. The causal signal is concurrency: one
large 38-turn Opus 4.8 run overlapped three active Opus 4.6 orchestrators.

## 14-day statistics

Source: `data/orchestra.db`, `usage_snapshots`, 2026-07-10 through
2026-07-24.

- 2,061 snapshots; median interval **5.04 min**.
- 41 observed active 5h windows.
- 7 windows hit 100%; 9 reached ≥95%; 10 reached ≥80%.
- Median window peak: **57%**; mean peak: **53.9%**.
- Fully exhausted windows:
  - median time to 100%: **172 min**;
  - mean: **200 min**;
  - fastest: **120 min**;
  - slowest: **282 min**.

### Week-over-week

| Slice | Active windows | Hit 100% | ≥80% | Median peak | Mean peak |
|---|---:|---:|---:|---:|---:|
| First 7 days | 18 | 4 | 4 | 68% | 63.7% |
| Last 7 days | 23 | 3 | 6 | 31% | 46.2% |

The latest week has more windows because work is split into more sessions, but
lower typical utilization. It also has more near-cap bursts, including two
98% windows. So average load improved while tail risk remained bad.

### Fully exhausted windows

| Window start, local | Time to 100% |
|---|---:|
| 2026-07-10 15:00 | 262 min |
| 2026-07-11 09:00 | 282 min |
| 2026-07-16 10:50 | 144 min |
| 2026-07-17 09:50 | 170 min |
| 2026-07-21 08:00 | 250 min |
| 2026-07-21 18:00 | **120 min** |
| 2026-07-24 08:40 | **172 min** |

There are 20 telemetry gaps over 15 minutes, mostly overnight while Orchestra
was stopped/hibernated. Total uncovered time is ~161 hours. The conclusions are
strong for recorded active windows but do not cover Claude usage outside
Orchestra.

## Longer-term contributors

Per-turn attribution exists reliably from 2026-07-16, not for the full 14-day
window. Top Claude consumers by virtual turn cost since then:

| Session | Model | Virtual cost | Agentic turns |
|---|---|---:|---:|
| `seedon-orchestrator` | Opus 4.6 | $147.17 | 927 |
| `COG-second-brain-orchestrator` | Opus 4.6 | $137.25 | 488 |
| `Orchestra-orchestrator` | Opus 4.6 | $86.74 | 662 |
| `sensar-client-offer` | Opus 4.8 | $50.80 | 246 |
| `sensar-product-platform` | Opus 4.8 | $50.78 | 321 |
| `mass-job-hunter` | Opus 4.8 | $36.09 | 39 |
| `feat-rag-files` | Opus 4.8 | $34.88 | 167 |

The top three are long-lived orchestrators. Heavy Opus 4.8 full-cycle workers
form the second tier and can consume a large fraction in a single completion.

## Why this happens

Anthropic documents that all Claude surfaces share the same plan limit and that
usage depends on conversation length, model, effort, files, tools/connectors,
and task complexity. Long conversations and automatic context management
consume more usage. Tools and research are explicitly token-intensive.

In Orchestra, multiple Claude sessions can run concurrently against one
subscription. The provider sees aggregate consumption, while each orchestrator
acts as though it has an independent budget. Prompt-level routing guidance does
not prevent four simultaneous Opus turns, and delayed provider accounting makes
the last 20–30% arrive as jumps after work has already been spent.

## Recommended controls

1. **Server-side Claude admission control**, not another prompt rule:
   - 50%: warning / stop new Opus worker starts;
   - 65%: hard block new Claude worker turns;
   - allow only top-level orchestrator messages already in progress.
2. **Concurrency cap: at most two Claude sessions running simultaneously.**
   Queue other Claude sends; Codex remains unrestricted.
3. **Opus 4.8 requires a capability trigger** (deep citation synthesis, vision,
   1M context), otherwise Sol.
4. **All routine workers → Sol; bounded leaf tasks → Spark.** Current headroom is
   Codex 91%, Spark 100%.
5. **Use velocity, not only utilization:** dashboard should show percentage
   points/hour, time-to-cap, and an “accounting delayed by active turns” warning.
6. **Do not auto-start Fable while Claude 5h >35%.** It is not today's culprit
   (scoped weekly is 0%), but it has the worst quota multiplier.
7. Keep usage credits disabled unless the subscription-only policy changes;
   otherwise reaching 100% must remain a visible hard stop.

At current history, a 65% hard gate alone is too late: today's window went
65→100 in 35 minutes of snapshots, with spend already committed in running
turns. Admission must stop at 50% and account for in-flight Claude sessions.

## Sources

1. Orchestra SQLite `usage_snapshots` and `logs` — primary operational
   telemetry.
2. [Claude: how usage and length limits work](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work)
   — official factors affecting usage and shared surfaces.
3. [Claude Max plan limits](https://support.claude.com/en/articles/11049741-what-is-the-max-plan)
   — official Max 5x/20x and weekly reset behavior.
4. [Claude usage limit best practices](https://support.claude.com/en/articles/9797557-usage-limit-best-practices)
   — official caching/tool/model guidance.
5. [OpenAI: Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540)
   — official Codex shared-pool and task-complexity behavior.
