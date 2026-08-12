# fix-grep-guard

- Linux multicall identity: `comm` does not follow `exec -a`; match the policy cgroup, resolved
  `/proc/PID/exe`, and the first NUL-delimited `argv[0]`, with one-field-at-a-time negative tests.
- `cgroup.freeze` is a shared, non-reference-counted bit. A separate marker cannot prove ownership
  of a transition on somebody else's cgroup; use an exclusively created private child cgroup and
  never clear the parent's freeze bit.
- For a reversible multi-file install, persist expected payload hashes before the first rename.
  Rollback should atomically claim each current destination, accept only the recorded payload or
  the exact saved predecessor, and validate any executable/config backup before claiming live files.
