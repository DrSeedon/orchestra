# Astra Standard vs Fast — 05.09.2026

## Findings

Official API launch claim: up to 2x speed at 2x API price.
Codex CLI 0.153.2 corrected Astra's displayed Fast description from 1.5x to 2x;
the release explicitly says request behavior did not change.
Codex Fast is billed at 2.5x Standard credits. This is not the API price multiplier.
The Astra model guide provides no Fast-mode latency SLA.

Sources:
- https://openai.com/index/gpt-6-astra/
- https://github.com/openai/codex/releases/tag/rust-v0.153.2
- https://learn.chatgpt.com/docs/agent-configuration/speed
- https://developers.openai.com/api/docs/guides/latest-model

## Local measurement

Codex CLI 0.153.4, Astra medium, sequential fresh ephemeral CLI invocations, existing
subscription authentication and inherited proxy environment; no Orchestra workload,
project instructions or tool calls. Both modes requested explicitly via service_tier.
The backend did not echo the actual serving tier in exec JSONL; requested configuration
is verified, backend routing is not independently attested.

First exploratory 60-line control timed out after 90 seconds before an answer. That
batch stopped without retries; it is retained in measurements.jsonl and excluded from
speed ratios. Short OK probes in both modes succeeded but were not latency samples.

A second exploratory batch used a fixed 12-line answer. Two Standard A/A controls,
then four balanced pairs: S/F, F/S, S/F, F/S. Model output was byte-identical across
all ten successful runs, with 184 output tokens and zero reported reasoning tokens.
Input was 16,772 tokens (including the native Codex harness). See measurements-12.jsonl.

| Metric | Standard, n=4 | Fast, n=4 |
|---|---:|---:|
| Median time to complete answer | 11.378 s | 8.171 s |
| Median full CLI wall time | 13.152 s | 9.800 s |
| CLI wall-time range | 12.587–13.953 s | 9.249–12.684 s |

Ratios of medians: answer 1.392x (28.2% less waiting), full CLI 1.342x (25.5% less).
Per-pair full-wall speedups: 1.373x, 1.509x, 1.312x, 0.992x (last effectively tied).
The two A/A controls were 13.953 s and 14.351 s; one pair is not a robust noise estimate.

Important confound: Standard cached-input tokens were 0, 9856, 9856, 16640; Fast
reported 0 in all four runs. The first pair had zero cache in both modes and a
1.373x full-wall speedup, but that is only one pair. Host load changed during the
batch and is logged per run; no heavy local tests ran during the measured batch.
CLI version and launcher hash matched throughout (native binary hash not recorded).

This measures short-answer completion, not TTFT, raw token decoding throughput,
code quality, long-context reasoning, or complete multi-tool development tasks.
Four pairs and one failed earlier pilot cannot establish a population-average speedup.

## Public reactions

The following firsthand threads praise Astra's speed/focus compared with Sol, while
comments dispute quota consumption and whether rollout load will change latency.
They do not supply controlled Astra Fast vs Astra Standard measurements:
- https://www.reddit.com/r/codex/comments/1w7gy48/astra_is_fast/
- https://www.reddit.com/r/codex/comments/1w7eu6n/gpt6_astra_is_blazingly_fast/

The Reddit JSON reader was blocked; accessible web-rendered pages were used instead.
No vote counts or claims of representative consensus were inferred.

## Reproduce

Create the scratch directory specified in measure.py outside project trees, then run
`ASTRA_BENCH_LINES=12 python measure.py` from this task directory. The script refuses
to overwrite existing measurement files, executes one request at a time and stops
on an invalid/failed result. The recorded run used a MemoryMax=2G user scope and nice=15.
Credentials and global client configuration were neither copied into Git nor changed.
