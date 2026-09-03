# fix-owned-dirs-lifecycle

- Lifecycle transitions must save branch, task, ownership, and prompt fields together; a failed Git switch must not pre-quarantine the old state.
- `save_session()` already provides the transaction needed for a complete loaded or detached session snapshot; update the in-memory object only after it succeeds.
