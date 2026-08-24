# research-regression-aware-merge

- A server-owned acceptance command is not automatically a safety oracle: before relying on it,
  verify non-empty/fail-closed presence, operation-time pinning, and immutability of every
  candidate-side test, fixture, helper, conftest, config, marker, and selector input.
- For a deliberately stale parallel branch, validate the deliverable with
  `git merge-tree --write-tree main HEAD`, archive that tree object, and run both sides' focused
  suites from the archive; branch-local green cannot prove three-way compatibility.
- In durable schema extensions, an empty legacy snapshot and an explicit new `source=none` snapshot
  are different states. Preserve legacy fallback only for the truly absent field; otherwise a new
  explicit no-op can accidentally bypass old validation.
