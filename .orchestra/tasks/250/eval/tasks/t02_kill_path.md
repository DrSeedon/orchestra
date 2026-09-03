# T02 — killed token on the real lifecycle path

A prior test called `Barrier.on_child_killed()` directly and passed even when `SessionManager.remove()` was not wired to the barrier. Removing `worker-1` must archive it and publish one observable `("worker-1", "killed")` terminal token. Renaming or inlining the helper is a valid refactor.

Write the smallest regression test through the public lifecycle path.

