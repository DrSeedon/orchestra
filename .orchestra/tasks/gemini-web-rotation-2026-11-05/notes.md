# Gemini Web rotation and pool UI

Source: authorized helper task, 2026-11-05. No commits/push/branch switch.

Confirmed defects in current implementation:
- Missing oPEP7c raises identity_mismatch instead of cookies_expired.
- Only two cookies admitted/imported; Set-Cookie updates discarded at helper exit.
- Disabling the vendor cache path also disables vendor rotate_1psidts entirely (it returns immediately when path is None).
- Pool and sticky account are absent from live usage/session UI.

Acceptance: private atomic persistence without vendor cache files, bounded recovery,
three-account UI, local/VPS focused tests, live arithmetic and read_file AgentLoop calls
via existing gemini-web-check-1793881789. Restart only orchestra.service; preserve
telegram-bot-api PID and record cut_names/recovery. No raw credentials in evidence.

Live VPS probe (cookie-probe.json): stored pair → guest + RotateCookies 401;
fresh full Google jar → authorized + RotateCookies 200; full jar with missing or
stale 1PSIDTS → guest + 401. Extra cookies alone do NOT solve Opera rotation.
A bounded on-demand Opera refresh over the existing laptop SSH tunnel is required
when Google refuses server-side recovery; no polling service or background daemon.

First expanded local run: 87 pass, 1 fail, 16 setup errors. Browser errors:
Playwright expects chromium_headless_shell-1223, only 1248 installed. No download.
Two existing T3 browser processes on the hub already consume the user's browser
allowance, so full browser suite and screenshots will run sequentially on VPS.
Metadata contract also exposed preexisting missing Antigravity provider metadata
and color; added the registry-matching entries while adding Gemini Web colors.

First live API arithmetic after restart: authentication recovered automatically
(17 cookies per slot, 0600; one cookies_expired warning, zero identity_mismatch),
but Gemini returned a generic refusal instead of 42. Session idle, zero error logs.
This is an acceptance failure, not an authentication failure. Investigating the
existing target's conversation/tool envelope before the mandatory tool check.

Live UI screenshots: all 3 accounts and session pill rendered, mobile overflow=false.
Live tool trace after id=1236733: read + tool_result executed by AgentLoop, but final
text was Google's "Sorry, something went wrong. Please try your request again."
Minimal direct requests also fail/return generic refusals. Native RPC-path probe
returned a refusal too, so no speculative routing changes made. Laptop minimal
probe returned authorization_unconfirmed; no laptop generation fallback installed.
Exact Google technical-error text must be a failed provider request, not requests_ok;
added classification so the existing pool can fail over and display honest status.
