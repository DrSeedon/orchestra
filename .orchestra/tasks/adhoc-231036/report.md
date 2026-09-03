# Urgent orchestrator auto-compact window

## Result

Automatic precompact is restricted to a configurable local-time window for
orchestrators only. Defaults are `21:00` inclusive through `06:00` exclusive in
`Asia/Krasnoyarsk`. Manual compact and every non-orchestrator automatic path are
unchanged.

## Confirmed mechanism

Read-only production-log inspection showed that the daytime interruptions came
from the delayed precompact timer, not the post-turn percentage path:

- `seedon-orchestrator`: timer scheduled at `2026-07-28T07:40:05Z`, fired and
  started compact at `08:35:05Z` (`15:35` UTC+7), context `60%`;
- `COG-second-brain-orchestrator`: timer fired and started compact at
  `08:26:38Z` (`15:26` UTC+7), context `34%`;
- `TurnManager.after_turn_idle_actions()` already excludes orchestrators from
  the immediate `live_pct > 90` auto-compact branch.

## Changes

- `app/session.py`
  - parses a cross-midnight window using an explicit IANA timezone;
  - reads `AUTO_COMPACT_WINDOW_START`, `AUTO_COMPACT_WINDOW_END`, and
    `AUTO_COMPACT_TIMEZONE` at runtime so `.env` loaded during FastAPI lifespan
    is honored;
  - blocks only orchestrator timer compaction outside the window;
  - logs a visible `auto-compact blocked...` status when a timer reaches the
    gate outside the window;
  - at critical context (`>90%`), logs one immediate `deferred` warning and
    suppresses the duplicate fire-time warning;
  - leaves worker/full-cycle/researcher timers and direct `compact()` calls
    outside the gate.
- `app/main.py`
  - validates the three settings immediately after `load_dotenv()` and before
    plugin loading, DB initialization, or session resume. Invalid times,
    identical boundaries, or an invalid timezone fail startup explicitly.
- `.env.example`
  - documents defaults, inclusive/exclusive boundaries, IANA timezone format,
    worker scope, and manual bypass.
- `tests/test_session.py`
  - covers UTC-to-local conversion, both cross-midnight boundaries, runtime env
    loading, invalid settings, orchestrator blocked/allowed paths, one-warning
    behavior, worker/full-cycle/researcher bypass, and manual Codex compact
    bypass.

## Scope decision

The window applies only when `session.is_orchestrator` is true. A read-only
validation covered all 85 non-archived sessions:

- 18 orchestrators: 15 Claude and 3 Codex;
- 67 non-orchestrators across worker, full-cycle, and researcher roles.

At a fixed local midday every orchestrator was blocked and every non-orchestrator
was allowed; at a fixed local 22:00 all paths were allowed. Restricting workers
would delay the existing compacts that keep long autonomous jobs operational.

## Verification

- TDD baseline: 7 new contract tests failed before implementation.
- Focused precompact suite: `24 passed`.
- Full suite under the global test lock:
  `/tmp/pytest-adhoc-231036.log` —
  `1108 passed, 20 skipped in 121.77s`.
- `git diff --check`: clean.
- Codex adversarial review:
  `docs/tasks/adhoc-231036/codex-review-impl.md`.
  Round 1 raised four suggestions (duplicate warning, startup validation,
  environment isolation, role/manual coverage); all were fixed. Round 2:
  `APPROVED`, no blocking/suggestion/question findings.

## Operational notes

- No server restart was performed. The Python change becomes active on the next
  shared restart.
- No live DB row or worktree was modified; production validation used SQLite
  read-only/query-only mode.
- No MCP-to-route wire contract changed, so there is no mixed-version rolling
  compatibility window.
- The defaults work without adding variables to the live `.env`; deployments
  outside Krasnoyarsk should set an explicit local IANA timezone before restart.
