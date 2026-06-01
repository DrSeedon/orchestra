# Proxy Benchmark — 2026-06-01

## Infrastructure Context

Machine routes ALL traffic through Hiddify VPN (`tun0` → Ёжик VPS 194.87.250.243).
This means "Direct" (no proxy) and "Hiddify proxy" (127.0.0.1:12334) both exit through the same VPN tunnel — Direct goes via tun0 routing, Hiddify proxy goes via explicit VLESS proxy. Same exit IP, different transport.

## IP Identity

| Proxy | Exit IP | Location | Org |
|-------|---------|----------|-----|
| Hiddify (12334) | 194.87.250.243 | Amsterdam, NL | Timeweb |
| VPS Tunnel (12338) | 194.87.250.243 | Amsterdam, NL | Timeweb |
| Direct (no proxy) | 194.87.250.243 | Amsterdam, NL | Timeweb |
| Timeweb NL (3128) | 147.45.101.84 | Amsterdam, NL | Timeweb |
| Fornex NL (3128) | ❌ DEAD | — | — |
| "Ёжик VPN" (12334) | = Hiddify | DUPLICATE | same port |

## Speed Test — Anthropic API (3 runs, seconds)

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** |
|-------|-------|-------|-------|---------|
| **Hiddify (12334)** | 0.349 | 0.344 | 0.342 | **0.345** |
| Timeweb NL (3128) | 1.121 | 0.582 | 0.555 | **0.753** |
| VPS Tunnel (12338) | 0.767 | 0.871 | 0.826 | **0.821** |
| Direct (tun0) | 0.790 | 1.244 | 0.760 | **0.931** |

## Speed Test — OpenAI API (3 runs, seconds)

| Proxy | Run 1 | Run 2 | Run 3 | **Avg** |
|-------|-------|-------|-------|---------|
| **Hiddify (12334)** | 0.364 | 0.444 | 0.440 | **0.416** |
| Timeweb NL (3128) | 0.717 | 0.724 | 1.077 | **0.839** |
| VPS Tunnel (12338) | 0.807 | 0.852 | 0.979 | **0.879** |
| Direct (tun0) | 0.863 | 1.078 | 0.977 | **0.973** |

## Stability Test — 10 sequential requests to Anthropic

| Proxy | Success | Fail | Avg (s) | Min (s) | Max (s) |
|-------|---------|------|---------|---------|---------|
| **Hiddify** | 10/10 | 0 | 0.342 | 0.317 | 0.459 |
| Timeweb NL | 10/10 | 0 | 0.617 | 0.524 | 0.743 |
| VPS Tunnel | 10/10 | 0 | 0.844 | 0.680 | 1.139 |
| Direct | 10/10 | 0 | 0.853 | 0.790 | 1.102 |
| Fornex NL | 0/10 | 10 | — | — | — |

## Analysis

### Duplicates Confirmed

1. **"Ёжик VPN" = Hiddify** — same port 12334. The PROXY_LIST has two names for the same thing. Remove "Ёжик VPN" alias.

2. **Direct ≈ Hiddify (via tun0)** — all traffic already goes through Hiddify's tun0 VPN. "Direct" is NOT actually direct-to-internet, it's Hiddify-via-tun0. Using Hiddify as explicit HTTP proxy (12334) is faster because it avoids the tun0 routing overhead (~0.34s vs ~0.85s).

3. **VPS Tunnel (12338)** — SSH tunnel to Tinyproxy on Ёжик (port 18080). Same exit IP as Hiddify. Slower (0.84s vs 0.34s) because: SSH encryption overhead + Tinyproxy hop + TCP-over-TCP. Redundant if Hiddify works.

### Dead Proxies

- **Fornex NL (89.127.206.225:3128)** — DEAD. TCP connects to Squid but CONNECT requests hang. Squid is likely misconfigured or outbound HTTPS blocked by firewall. 0/10 success rate.

### Speed Ranking

1. 🥇 **Hiddify (12334)** — 0.345s avg, fastest by 2x. VLESS+Reality, no extra hops
2. 🥈 **Timeweb NL (3128)** — 0.753s avg. Different exit IP (147.45.101.84), good as backup
3. 🥉 **VPS Tunnel (12338)** — 0.821s avg. Same exit IP as Hiddify, slower, redundant
4. 4️⃣ **Direct (tun0)** — 0.931s avg. Goes through Hiddify anyway, slower than explicit proxy

## Recommendations

### Keep (2 proxies)

| Proxy | Role | Why |
|-------|------|-----|
| **Hiddify (12334)** | PRIMARY | Fastest (0.34s), most stable, VLESS+Reality |
| **Timeweb NL (3128)** | BACKUP | Different exit IP (147.45.101.84), works if Ёжик VPS goes down |

### Remove (4 entries)

| Proxy | Why |
|-------|-----|
| "Ёжик VPN" (12334) | DUPLICATE of Hiddify — same port, same process |
| Fornex NL (3128) | DEAD — Squid hangs on CONNECT, 0% success |
| VPS Tunnel (12338) | REDUNDANT — same exit IP as Hiddify, 2.4x slower |
| Direct | MISLEADING — not actually direct, goes through tun0 VPN anyway |

### PROXY_LIST Cleanup

**Current (6 entries):**
```
Hiddify, Ёжик VPN, Fornex NL, Timeweb NL, VPS Tunnel, Direct
```

**Proposed (2 entries):**
```
Hiddify (http://127.0.0.1:12334)  — primary, Anthropic + OpenAI
Timeweb NL (http://orchestra:***REMOVED***@147.45.101.84:3128)  — backup, different IP
```

### VPS Tunnel (12338) Shutdown

The SSH tunnel to Ёжик Tinyproxy can be stopped. It's currently running as:
```
ssh -N -L 12338:127.0.0.1:18080 -i .../server1.pem root@194.87.250.243
```
Two processes running (root + maxim). Both can be killed. Tinyproxy on Ёжик (port 18080) can also be disabled if nothing else uses it.

**However**: Orchestra workers currently use `HTTPS_PROXY=http://127.0.0.1:12338`. Before killing the tunnel, update all worker configs to use 12334 (Hiddify).

### Open Question: Fornex VPS

Fornex (89.127.206.225) — the Squid proxy is dead. Options:
1. Fix Squid config on Fornex — gives a third exit IP (useful for rate-limit diversification)
2. Drop it entirely — Hiddify + Timeweb is enough for current scale
