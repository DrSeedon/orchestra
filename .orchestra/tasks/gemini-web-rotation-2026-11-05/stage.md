# Gemini Web rotation / pool UI — helper handoff

Status: cookie recovery and UI implemented/deployed; full live completion acceptance
is NOT green. Gemini returns generic refusals, technical error text, or timeouts.
No claim that a nonempty provider answer proves working inference.

## Code

- `app/gemini_web_auth.py`: allowlisted full Google session jar, optional TS,
  owner-only atomic writes and directory-inode flock, CAS rotation updates shared
  slots without overwriting newer imports, masked labels, all-cookie redaction.
- `app/harness/gemini_web_worker.py`: guest/missing principal -> cookies_expired;
  nonempty unauthorized principal -> identity_mismatch. Full cookies, memory-only
  RotateCookies, auto-refresh, updated_cookies on success AND authenticated errors;
  exact Google technical error classified as request_failed. Vendor caches remain
  disabled and audit hook denies every .cached_cookies_ open.
- `app/harness/gemini_web.py`: opt-in on-demand Opera refresh over existing laptop
  tunnel, one refresh per shared login per stream; private validated pipe, same
  __Secure-1PSID required, bounded timeout/cleanup. Per-account status/counters,
  masked pool data and live bindings. Counters are per service process.
- `scripts/gemini_web_opera_cookies.py`: cookie-only Opera/KWallet reader; source
  piped to laptop Python, values returned solely to captured private pipe. No
  cookie/temp/browser files, nice=15, address-space limit 2 GiB, core dumps off.
- `app/backend_harness.py`, `app/session.py`, `app/routes/system.py`: account badge
  metadata and /api/usage.gemini_web.
- `app/static/js/{usage,app,theme,utils,i18n}.js`,
  `app/static/css/design-system.css`: compact 3-account pool, details and chat pill.
  Existing missing Antigravity metadata/color completed to pass exhaustive contract.
- `tests/test_gemini_web_harness.py`, `tests/test_usage_analytics_frontend.py`:
  rotation/CAS/privacy/error/refresh/backend/API and browser/mobile contracts.

## Setup / measured limits

VPS `.env`: `GEMINI_WEB_COOKIE_SOURCE=opera-laptop` (non-secret opt-in).
Uses the existing SSH inventory in `scripts/orchestra_backup.py`; no new tunnel,
service, timer, daemon, paid route or provider configuration was added.
The laptop must be reachable and KWallet unlocked if Google has invalidated the
whole jar. Extra SID/HSID/SSID/etc alone do NOT make stale TS work: direct VPS
probe found guest + RotateCookies 401 with stale/missing TS, versus authorized +
200 with fresh full cookies. Probe: `cookie-probe.json`.

## Checks

| Check | Result |
| --- | --- |
| Local focused harness/API/metadata/contracts | 89 passed, `pytest-local-final.log` |
| VPS full requested harness + analytics frontend + usage contract | 109 passed, `pytest-vps-final.log` |
| JS syntax, git diff --check | passed |
| Instruction contract | passed, `instruction-contract.log` |
| Real authenticated desktop/mobile screenshots | 3 compact accounts, all 3 in tooltip, session pill present, no mobile overflow; `live-visual.json`, `live-*.png` |
| Private auth modes / vendor cache / evidence scan | 0600 / 0700; 0 cache files; no credential value hits; `privacy-check.json` |
| Existing session missing-TS live recovery | 3 absent -> 3 restored automatically; `live-final-math.json` |
| Existing session arithmetic | RED: no 42, final attempt 1 error after provider failures |
| Real AgentLoop tool | read + tool_result executed, final provider technical error; `live-tools-final.json` |

The first broad local browser run had 16 setup errors (expected Playwright binary
1223 missing locally), and a real metadata mismatch. Metadata was fixed; complete
browser suite passed on VPS using its already installed binary. No downloads and
no acceptance tests weakened. `pytest-local.log` preserves the original failure.

Checked imports:
- `/mnt/claude-data/astrahancev-maxim-911aird/orchestra/app/__init__.py`
- `/home/kesha/orchestra/app/__init__.py`

## Operations / ownership

Only named files were rsynced; no commit, push, branch switch or other remote edit.
Initial authorized orchestra.service restart: PID 2095830 -> 2099437, active;
cut_names=[], interrupted_names=[]. telegram-bot-api PID remains 769, never restarted.
A later restart was deferred while Seedon had a live turn. After all turns ended,
final orchestra.service restart completed: PID 2099437 -> 2114717, active;
telegram-bot-api still PID 769. See `service-after-final.json`.
Final missing-TS arithmetic and tool API turns both ended idle with 1 error each;
all three accounts failed inference. Auth TS restored on 3/3; full final evidence:
`live-final.json` (success=false). No further provider retries scheduled.

Existing unrelated AGENTS.md edits and other untracked tasks/skills were preserved.
Full live acceptance remains an open issue; no speculative RPC routing or laptop
inference fallback was installed. Native-RPC-path and minimal prompt probes also
returned refusals/timeouts; underlying inference failure is not established.

Remaining UI limitation: after service restart the idle target has no attached
backend, so provider_account is null until its next connection. The real bound
badge was verified before restart (u/0 then u/3), but durable assignment across
service restarts is not implemented; no speculative DB/auth schema change made.
