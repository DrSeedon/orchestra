# impl333-outbox-sol

- `monkeypatch.setattr(one_module.uuid, "uuid4", ...)` mutates the shared stdlib module object
  seen by every importer. Keep unrelated internal ownership tokens on `secrets.token_hex()` (or
  an isolated imported callable), so a public event-id test cannot break lease generation.
- A frozen async oracle that waits only `asyncio.sleep(0)` ticks cannot bound work delegated with
  `asyncio.to_thread`: OS thread-pool scheduling is independent of event-loop ticks. For small
  mandatory pre-boundary file verification, use bounded chunks with an event-loop yield between
  chunks when deterministic progress is part of the contract.
