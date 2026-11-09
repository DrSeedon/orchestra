# Gemini Web surgical fixes

Source: owner/helper task dated 2026-11-06. Scope: the four named harness/auth/test
files; no commit, push, branch switch, live provider probe or deployment.

Confirmed in current code before editing:
- Cookie CAS updates only exact cookie matches, leaving drifted multi-login slots stale.
- Disabled accounts have no active-pool exclusion.
- Cookie cache directory discovery remains enabled; vendor post-stream history polling
  has no harness override.
- Generation rejects only one exact canned response and has no Flash fallback.
- Prompts retain historical canned refusals and unbounded system content.

Implemented in app/gemini_web_auth.py, app/harness/gemini_web_worker.py,
app/harness/gemini_web.py and tests/test_gemini_web_harness.py:
- Exclude the owner-disabled email and explicit boolean-disabled entries from active
  accounts; preserve and validate the optional disabled flag.
- Require an exact cookie CAS match before propagating changed cookie values across
  the shared PSID, including drifted slots; stale writers/no-ops do not write.
- Disable cache directory discovery and vendor class history polling in the disposable
  helper, using the vendor's handled TimeoutError path after stream completion.
- Reject blank/canned responses and try available Flash -> Flash-Lite -> Pro candidates,
  preserving requested selected_model and reporting the successful display name.
- Omit historical assistant refusals and compact system strings above 12000 chars to
  first 8000 + marker + last 3000, without mutating inputs or changing normal JSON.

Validation: `.venv/bin/pytest tests/test_gemini_web_harness.py -q` (under nice=10 and
oom_score_adj=1000) exited 0: **114 passed in 5.52s**. `git diff --check` passed.
Checked app import: `/mnt/claude-data/astrahancev-maxim-911aird/orchestra/app/__init__.py`.
All vendor behavior was mocked; the post-stream regression test mirrors 2.1.1's
generator/TimeoutError handler. No live Gemini request or deployment was performed.
Existing unrelated changes were preserved. No commit, push or branch switch.
