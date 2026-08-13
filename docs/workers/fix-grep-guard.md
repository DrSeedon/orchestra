# fix-grep-guard

- Linux multicall identity: `comm` does not follow `exec -a`; match the policy cgroup, resolved
  `/proc/PID/exe`, and the first NUL-delimited `argv[0]`, with one-field-at-a-time negative tests.
- `cgroup.freeze` is a shared, non-reference-counted bit. A separate marker cannot prove ownership
  of a transition on somebody else's cgroup; use an exclusively created private child cgroup and
  never clear the parent's freeze bit.
- For a reversible multi-file install, persist expected payload hashes before the first rename.
  Rollback should atomically claim each current destination, accept only the recorded payload or
  the exact saved predecessor, and validate any executable/config backup before claiming live files.
- A stored PID is never an identity by itself. Persist its start time in the same atomic snapshot,
  open a pidfd before every `/proc` identity read, and signal only through that pidfd; independently
  mutable labels such as runtime/backend type cannot strengthen the old snapshot.
