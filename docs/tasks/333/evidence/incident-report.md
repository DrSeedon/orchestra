# Sanitized incident report excerpt

Source: `/home/maxim/.local/state/orchestra/bug-inbox/records/20260824T080805.472060Z-f49cf488dde54ede865a5fb711f0184c.md`.

```text
2026-08-24 08:08 UTC — send_file_to_tg returns HTTP 5xx during sequential 8-image delivery
Error: http_5xx: TG file delivery failed; see tg-bridge logs
The functions.exec cell remained running for about 53 seconds before failure.
Eight existing PNG paths, 437,744–605,181 bytes, stat/sha256 verified immediately before delivery.
Delivery count before failure: unknown because the batched exec emitted no per-call output.
No model inference rerun and no data loss.
```

The source report contains no provider receipt or Telegram message id for the failed batch.
