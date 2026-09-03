# Reusable notes

- In the current review path, `resume`/previous UUID identifies continuation but does not provide a durable numeric round; `codex_review_artifact.py` increments `codex_sessions.json.turns` only after finalization. A DB receipt must reserve the round atomically if concurrent calls are possible.
- A migration script launched by path can import a different checkout via inherited `PYTHONPATH`; insert `Path(__file__).resolve().parents[1]` into `sys.path` before importing project modules.
- Shared artifact finalization needs both a per-artifact lock and unique temp names; unique scratch inputs alone do not serialize the final read-modify-replace.
- A durable backup path is itself state: reject existing or aliased paths before opening SQLite, otherwise repeated apply can overwrite the only rollback image.
