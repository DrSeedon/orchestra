# Proxy Speed Benchmark — 2026-06-01

## Infrastructure

All traffic routes through Hiddify VPN (`tun0` → Ёжик VPS 194.87.250.243).
"Direct" (no proxy) also exits via tun0, making it NOT truly direct — it's Hiddify-via-kernel-routing.

### Proxy Inventory

| Proxy | Port | Type | Exit IP | Status |
|-------|------|------|---------|--------|
| **Hiddify** | 12334 | VLESS+Reality (Hiddify client) | 194.87.250.243 | ✅ Active |
| **Timeweb NL** | 12341 | Squid (SSH tunnel → 147.45.101.84:3128) | 147.45.101.84 | ✅ Active |
| Ёжик tunnel | 12340 | SSH → Tinyproxy 18080 on Ёжик | 194.87.250.243 | ❌ Dead (timeout) |
| VPS Tunnel | 12338 | SSH → Tinyproxy 18080 on Ёжик | 194.87.250.243 | ❌ Dead (timeout) |
| Fornex NL | 12342 | Squid (SSH tunnel → 89.127.206.225:3128) | — | ❌ Dead (407 auth hangs) |
| Direct | — | tun0 kernel routing | 194.87.250.243 | ❌ Timeouts (15s+) |

**Working proxies: 2 (Hiddify, Timeweb NL)**. The rest are dead, redundant, or broken.

---

## 1. Anthropic API — api.anthropic.com/v1/messages

### 3-run test (seconds)

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** | Min | Max |
|-------|-------|-------|-------|---------|-----|-----|
| **Hiddify** | 0.445 | 0.330 | 0.460 | **0.411** | 0.330 | 0.460 |
| Timeweb NL | 0.657 | 0.701 | 0.710 | **0.689** | 0.657 | 0.710 |
| Direct | FAIL | FAIL | FAIL | — | — | — |

### 10-run stability test

| Proxy | Success | Avg (s) | Min (s) | Max (s) | Std dev* |
|-------|---------|---------|---------|---------|----------|
| **Hiddify** | 10/10 | **0.348** | 0.312 | 0.432 | ~0.04 |
| Timeweb NL | 10/10 | **0.716** | 0.658 | 0.748 | ~0.03 |

*Hiddify is **2.1x faster** than Timeweb for Anthropic API.*

---

## 2. OpenAI API — api.openai.com/v1/models

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** | Min | Max |
|-------|-------|-------|-------|---------|-----|-----|
| **Hiddify** | 0.408 | 0.416 | 0.396 | **0.406** | 0.396 | 0.416 |
| Timeweb NL | 0.625 | 0.658 | 0.984 | **0.755** | 0.625 | 0.984 |
| Direct | FAIL | FAIL | FAIL | — | — | — |

*Hiddify is **1.9x faster** than Timeweb for OpenAI API.*

---

## 3. Deepgram API — api.deepgram.com/v1/listen

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** | Min | Max |
|-------|-------|-------|-------|---------|-----|-----|
| **Hiddify** | 0.772 | 0.683 | 0.672 | **0.709** | 0.672 | 0.772 |
| Timeweb NL | 1.240 | 1.024 | 1.146 | **1.136** | 1.024 | 1.240 |
| Direct | FAIL | FAIL | FAIL | — | — | — |

*Hiddify is **1.6x faster** than Timeweb for Deepgram API.*

Deepgram has higher base latency than Anthropic/OpenAI (~0.7s vs ~0.4s via Hiddify), likely due to Deepgram's server location or TLS negotiation.

---

## 4. Connect Latency — time_connect to httpbin.org

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** |
|-------|-------|-------|-------|---------|
| Hiddify | 0.139ms | 0.130ms | 0.135ms | **0.135ms** |
| Timeweb NL | 0.081ms | 0.080ms | 0.124ms | **0.095ms** |
| Direct | 0ms | 0ms | 0ms | **0ms** |

Connect latency measures TCP handshake to the proxy itself (localhost). All are <0.2ms — **negligible**. The real latency difference comes from the proxy→target hop, not the local→proxy connection.

---

## 5. Bandwidth — 1MB download (proof.ovh.net)

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** | Speed |
|-------|-------|-------|-------|---------|-------|
| **Hiddify** | 3.15s | 0.93s | 0.74s | **1.61s** | ~870 KB/s |
| Timeweb NL | 6.26s | 2.78s | 1.94s | **3.66s** | ~380 KB/s |

*Hiddify is **2.3x faster** for file downloads.*

Note: first request for both proxies was slower (cold connection), runs 2-3 were faster (connection reuse). Hiddify sustained ~1.1-1.4 MB/s after warmup; Timeweb ~400-540 KB/s.

### jsdelivr CDN (~80KB)

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** |
|-------|-------|-------|-------|---------|
| **Hiddify** | 0.460s | 0.480s | 0.573s | **0.504s** |
| Timeweb NL | 1.421s | 1.812s | 1.801s | **1.678s** |

---

## 6. Impact on Real Agent Workloads

### The Key Question: Does proxy latency matter for Claude agents?

**Agent workflow timing breakdown:**

| Phase | Duration | Proxy role |
|-------|----------|-----------|
| Initial API handshake | 0.3-0.7s | **Proxy adds latency here** |
| Token generation (Opus) | 15-60s | **No proxy impact** — SSE streaming, proxy is transparent |
| Tool calls (10-30 per task) | 0.3s × N overhead | **Proxy adds latency per tool call round-trip** |
| File reads, grep, bash | 0ms | Local, no proxy |

### Per-task proxy overhead calculation

Typical agent task: 1 initial request + ~15 tool-call round-trips to Claude API.

| Proxy | Per-request overhead | × 16 calls | **Total overhead** |
|-------|---------------------|------------|-------------------|
| Hiddify | 0.35s | × 16 | **5.6s** |
| Timeweb NL | 0.72s | × 16 | **11.5s** |
| **Difference** | 0.37s | × 16 | **+5.9s per task** |

For a task that takes 3-5 minutes of generation time, the proxy overhead is:
- Hiddify: ~3% of total time
- Timeweb: ~6% of total time
- **Difference between proxies: ~3% of total task time**

### Verdict

**Proxy latency is measurable but NOT significant for agent performance.** The 0.37s per-request difference between Hiddify and Timeweb adds ~6 seconds to a typical task — noise compared to 3-5 minutes of LLM generation time. Even a hypothetical "zero-latency" proxy would only save ~6s total.

**However**: for high-frequency operations (parallel agent spawns, rapid tool calls, burst API checks), Hiddify's 2x speed advantage compounds. A 30-agent parallel spawn where each makes 20 tool calls: Hiddify saves ~3.5 minutes of aggregate API wait time.

---

## Summary

### Speed Ranking (all APIs)

| Rank | Proxy | Anthropic | OpenAI | Deepgram | Bandwidth | Overall |
|------|-------|-----------|--------|----------|-----------|---------|
| 🥇 | **Hiddify (12334)** | 0.35s | 0.41s | 0.71s | 870 KB/s | **Fastest, 1.6-2.3x ahead** |
| 🥈 | Timeweb NL (12341) | 0.72s | 0.76s | 1.14s | 380 KB/s | Reliable backup |
| ❌ | Ёжик (12340) | DEAD | — | — | — | Tinyproxy down |
| ❌ | VPS Tunnel (12338) | DEAD | — | — | — | Tinyproxy down |
| ❌ | Fornex (12342) | DEAD | — | — | — | Squid misconfigured |
| ❌ | Direct | DEAD | — | — | — | tun0 timeouts |

### Recommendations

1. **Primary: Hiddify (12334)** — fastest by 2x across all APIs, 100% stability
2. **Backup: Timeweb NL (12341)** — different exit IP (147.45.101.84), slower but reliable
3. **Kill dead proxies**: Ёжик (12340), VPS Tunnel (12338), Fornex (12342) — all broken, waste SSH tunnel resources
4. **Don't optimize proxy speed for agent performance** — the difference is in the noise (~3% of task time). Optimize prompts and tool-call count instead — one unnecessary tool call costs more than the entire proxy overhead difference
