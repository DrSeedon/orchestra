# #294 browser and Telegram release gate

Decision: **KEEP DISABLED**. `ARTIFACT_PUBLIC_LINKS_ENABLED` must remain unset or `0`.

This matrix separates a passing behavior measurement from a test-harness limitation. A command that
fails before launching its named engine is **not** evidence about that engine.

## Automated engines

| Engine | Command/result | Behavior measured | Gate |
|---|---|---|---|
| Chromium | Implementation review command, 2026-08-16: `tests/test_artifacts_browser.py` included in `27 passed, 2 warnings` | Trusted wrapper, sandboxed child, fragment absent from server target, no dashboard/external request, direct content rejected | PASS for Gate B |
| Firefox | `ARTIFACT_BROWSER=firefox uv run pytest -x -q tests/test_artifacts_browser.py` → exit 1 in 5.64 s | None: frozen test stopped at `tests/test_artifacts_browser.py:134` because it requires literal `chromium` | NOT MEASURED |
| WebKit | `ARTIFACT_BROWSER=webkit uv run pytest -x -q tests/test_artifacts_browser.py` → exit 1 in 4.46 s | None: frozen test stopped at `tests/test_artifacts_browser.py:134` because it requires literal `chromium` | NOT MEASURED |

The Firefox/WebKit failures are release-gate failures, not browser-security findings. Generalizing
the immutable browser oracle is future test work and cannot be replaced by inference from Chromium.

## Real Telegram clients

| Client | Preview absent | Fragment absent from request/log | Redeem/removal/render/repeat | Child confinement | Row revoke | Secret rotation rejects existing grant + original fragment | Document fallback | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Telegram Desktop | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | KEEP DISABLED |
| Android in-app | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | KEEP DISABLED |
| Android external | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | KEEP DISABLED |
| iOS in-app | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | KEEP DISABLED |
| iOS external | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | KEEP DISABLED |

No live configuration, public capability, deployment, or restart was used to produce this file.
Telegram document delivery remains the release fallback.
