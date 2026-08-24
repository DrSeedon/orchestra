# Research worker memory

- For delivery incidents, never infer provider acceptance from a local 500 or timeout: correlate
  logical event id, queue/request id, and provider message id; if any link is absent, preserve
  `UNKNOWN` and do not recommend a fresh retry.
- Safe incident probes are read-only journal/SQLite/API GETs plus a non-mutating provider health
  preflight; sanitize effective unit output before persisting it because systemd command lines can
  contain credentials.
