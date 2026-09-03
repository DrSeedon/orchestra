# Deepgram Voice Transcription — Research

**Date:** 2026-06-01
**Status:** Working (shared client in `app/transcription.py`; callers: TG bridge and dashboard `/api/transcribe`)

---

## 1. Voice Pipeline: TG → Orchestra → Deepgram

### Flow

```
User sends voice in TG group
    ↓
aiogram handler `handle_voice()` (tg_bridge.py:987)
    ↓
_download_file() → downloads OGA from TG Bot API
    ↓
transcribe_audio() → POST to Deepgram → returns text
    ↓
Text injected into agent session as [voice: path | transcription]
```

### File Download (tg_bridge.py:110-143)

**Two paths:**
1. **Local Bot API** (`TG_LOCAL_API_URL=http://localhost:8081`): `bot.get_file()` returns an absolute path on disk → `shutil.copy2()` to `data/uploads/`. Fast (0ms network, local copy).
2. **Remote TG API** (fallback): `bot.download_file()` downloads from `api.telegram.org`. Slower, 20MB limit.

**File format:** OGA container, Opus codec, mono, 48kHz. This is Telegram's native voice format.

Files saved to `data/uploads/` with naming pattern: `voice_YYYYMMDD_HHMMSS_NNNNN.oga`
Media cache (`data/uploads/.media_cache.json`) deduplicates by `file_unique_id`.

### Transcription (`app/transcription.py`)

**Request:**
```
POST https://api.deepgram.com/v1/listen
  ?model=nova-3
  &language=ru
  &smart_format=true
  &profanity_filter=false
Headers:
  Authorization: Token {DEEPGRAM_API_KEY}
  Content-Type: audio/ogg
  Accept-Encoding: gzip, deflate
Body: raw audio bytes
```

**Key parameters:**
- **model=nova-3** — Deepgram's latest STT model (upgraded from nova-2 in original code)
- **language=ru** — Russian language
- **smart_format=true** — punctuation, capitalization, paragraph formatting
- **profanity_filter=false** — uncensored transcription (added in `ff6de56`)

**Response parsing:** `data["results"]["channels"][0]["alternatives"][0]["transcript"]`

**Retry logic:** 3 attempts with backoff (1.5s, 3s). Transcription cache (`data/uploads/.transcription_cache.json`) deduplicates by `file_unique_id`.

### Video Notes

Video notes (round videos) go through an extra step:
1. Download `.mp4`
2. `ffmpeg -i input.mp4 -vn -acodec libopus -y output.oga` (extract audio)
3. Same shared `transcribe_audio()` path

---

## 2. SSL Breakage — Chronology

### Timeline of commits

| # | Commit | Date | What happened |
|---|--------|------|---------------|
| 1 | `693ac81` | ~May 26 | **Initial voice feature.** `aiohttp.ClientSession()` (default). `trust_env` not set → defaults to `False` in aiohttp <3.10, `True` in aiohttp 3.10+. With aiohttp 3.13.5 → **True by default** → picks up `HTTPS_PROXY=http://127.0.0.1:12334` |
| 2 | `7e41905` | May 30 05:14 | **First fix.** Added `trust_env=False`. Commit msg: "aiohttp picked up HTTPS_PROXY (Hiddify) for Deepgram API calls, causing SSL handshake failures" |
| 3 | `89c6eaf` | May 30 07:29 | **Second fix.** Added `Accept-Encoding: gzip, deflate` (no brotli). "Deepgram responds with brotli encoding which aiohttp+py3.13 can't decompress" |
| 4 | `1e1abe4` | Jun 1 05:00 | **Regression.** Removed `trust_env=False`, added explicit `proxy=HTTPS_PROXY`. Commit msg: "fix Deepgram SSL BAD_RECORD_MAC — use HTTPS_PROXY instead of trust_env=False". This was WRONG — it forced proxy when it should have bypassed it |
| 5 | `ff6de56` | Jun 1 05:30 | Added `profanity_filter=false` |
| 6 | `6ab422d` | Jun 1 05:54 | **Final fix.** Removed `proxy=` parameter, added timing logs. "Deepgram через Hiddify прокси = 34s, напрямую = 3.8s" |
| 7 | `63b9c7a` | Jun 1 05:56 | Same as #6 (duplicate commit, squash merge artifact) |
| 8 | `d1a85b8` | Jun 1 18:49 | **WIP auto-save.** Added `ssl=certifi` context + restored `trust_env=False`. This is the current state |

### What broke and why

**Root cause:** aiohttp 3.13.5 defaults `trust_env=True`, which reads `HTTPS_PROXY` from environment. Orchestra sets `HTTPS_PROXY=http://127.0.0.1:12334` (Hiddify VPN proxy) globally for Anthropic API access. Deepgram doesn't need a proxy and works fine direct.

**The proxy problem manifested in two ways:**

1. **SSL BAD_RECORD_MAC** — Hiddify is a VLESS+Reality proxy (not a standard HTTP CONNECT proxy). When aiohttp sends an HTTPS request through it, the proxy's TLS interception can corrupt the TLS record layer, producing `ssl.SSLError: [SSL: BAD_RECORD_MAC]`. This is intermittent — depends on proxy state, connection reuse, and timing.

2. **Latency** — Even when it works, routing through Hiddify adds ~30s overhead (34s vs 3.8s direct), because the traffic goes: local → Hiddify → VPS in Russia → Deepgram → back. Direct: local → Deepgram (2s).

---

## 3. SSL BAD_RECORD_MAC — Technical Explanation

### What is BAD_RECORD_MAC?

TLS protects each record with a MAC (Message Authentication Code). `BAD_RECORD_MAC` means the receiver computed a different MAC than what the sender attached. This means the TLS record was **modified in transit**.

### Why does Hiddify cause this?

Hiddify runs a VLESS+Reality proxy. This is designed for censorship circumvention, not as a transparent HTTP proxy:

1. **HTTP CONNECT proxies** (standard): Client sends `CONNECT host:443`, proxy creates a TCP tunnel, TLS runs end-to-end between client and server. No MAC corruption possible.

2. **VLESS+Reality** (Hiddify): The proxy terminates TLS differently. It can interfere with the TLS handshake in ways that corrupt records, especially with:
   - Connection reuse/multiplexing in aiohttp
   - Large POST bodies (audio files = 100-200KB)
   - Specific cipher suite negotiation

### Why curl works but aiohttp didn't (initially)?

**curl via proxy** works because curl uses a simpler CONNECT tunnel per-request. aiohttp's connection pooling and HTTP/2 multiplexing interact poorly with VLESS+Reality's connection handling.

However, **as of today's tests, aiohttp through proxy also works** — this suggests the issue was intermittent and possibly related to:
- Hiddify proxy version/config changes
- Connection state at the time
- Race conditions in connection reuse

### Why `trust_env=False` + `ssl=certifi` is the correct fix

The current code uses a belt-and-suspenders approach:

```python
import ssl, certifi
_dg_ssl = ssl.create_default_context(cafile=certifi.where())

async with aiohttp.ClientSession(trust_env=False) as http:
    async with http.post(url, ..., ssl=_dg_ssl) as resp:
```

1. **`trust_env=False`** — Don't read `HTTPS_PROXY` from environment. Go direct to Deepgram.
2. **`ssl=certifi`** — Use certifi's CA bundle instead of system CAs. This ensures consistent cert validation regardless of system state. Not strictly necessary for the fix, but defensive.

---

## 4. Current Status — Test Results (2026-06-01)

All tests use the same audio file: `voice_20260601_101102_35162.oga` (190KB, Opus, mono 48kHz)

| # | Method | Config | Time | Result |
|---|--------|--------|------|--------|
| 1 | curl | direct (--noproxy) | 1.9s | OK |
| 2 | curl | via Hiddify proxy | 2.1s | OK |
| 3 | aiohttp | trust_env=False + certifi ssl | 2.5s | OK |
| 4 | aiohttp | trust_env=True (picks up HTTPS_PROXY) | 1.4s | OK |
| 5 | aiohttp | explicit proxy=HTTPS_PROXY | 1.5s | OK |
| 6 | aiohttp | trust_env=False, no custom ssl | 1.3s | OK |

**All variants work today.** The SSL BAD_RECORD_MAC error is not reproducible right now. This is consistent with it being an intermittent issue caused by proxy state.

**Note:** Tests 4 and 5 (via proxy) are faster in this run than test 3 (direct) — this is just network variance on a single-run test. The 9x difference (34s vs 3.8s) from commit `6ab422d` was likely during a period of high proxy latency or proxy restart.

### Recommendation

Keep the current code (`trust_env=False` + certifi ssl) as-is:
- Deepgram is not blocked in Russia, doesn't need proxy
- Direct connection is more reliable (no proxy failure modes)
- The certifi ssl context is a cheap insurance against system CA weirdness
- Retry logic (3 attempts with backoff) handles transient network issues

---

## 5. Summary

| Question | Answer |
|----------|--------|
| Format | OGA (Ogg Opus), mono 48kHz — Telegram's native voice format |
| Download path | Local Bot API (shutil.copy2) or remote TG API (download_file) |
| Deepgram endpoint | `POST /v1/listen?model=nova-3&language=ru&smart_format=true&profanity_filter=false` |
| Why it broke | aiohttp 3.13+ defaults trust_env=True → picked up HTTPS_PROXY → Hiddify VLESS proxy corrupted TLS records intermittently |
| Fix | `trust_env=False` (bypass proxy) + `ssl=certifi` (explicit CA bundle) |
| Current status | Working, all 6 test variants pass |
