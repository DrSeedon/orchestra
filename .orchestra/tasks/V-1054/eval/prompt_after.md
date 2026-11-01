You are the worker who wrote this diff. Before reporting DONE, perform your self-check on it and list every problem you find, each with file and why.

- **Pre-mortem:** consider concrete regressions for callers, old data and recovery. Where relevant
  (owner decision, 2026-10-23), ask: which old contract must still hold, including unchanged
  callers/config/hooks that consume the changed code; what happens on failure or a repeated call;
  what happens to old data and on rollback? Check the plausible risks in proportion to their
  impact; do not invent a quota of failure scenarios. Name the evidence for each claim that a
  risk is covered; otherwise mark it unverified. Report checks actually performed and what
  remains unverified.
