## Summary

Reviewed the committed diff `c93ec6e18ba1953bfcacc14d9756ef01372eced5...d76f4a2e6129534c438000c4c415bce1deea8049`. I did not edit files or run tests.

## Findings

### Blocking

- [usage.js](/home/kesha/v918-work/v918-clean-20.r0-yk0gv3z1/app/static/js/usage.js:433): the usage tooltip callback appends to `h` without declaring it. Opening the details tooltip throws a `ReferenceError`, so the panel—including its new OpenRouter details—does not render. Initialize `h` before the first append.

### Suggestion

- [openrouter_counter.py](/home/kesha/v918-work/v918-clean-20.r0-yk0gv3z1/app/openrouter_counter.py:31): `_ok()` clears the unhealthy flag after any successful database operation. If recording an attempt fails, a later usage read can clear that flag and report `available: true` even though the failed attempt is missing from the count. Keep the failed-accounting state until it is explicitly recovered or acknowledged; otherwise the UI can present an undercount as healthy.

- [usage.js](/home/kesha/v918-work/v918-clean-20.r0-yk0gv3z1/app/static/js/usage.js:279): the daily countdown is based on `Date.now() + 24h`, rounded to the hour, while the counter’s day boundary is UTC midnight. It can therefore show the wrong reset time by many hours. Calculate the next UTC midnight.

## Verdict

NEEDS WORK — fix the tooltip runtime error and preserve unhealthy state after a lost count before relying on the panel.