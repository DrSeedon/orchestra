# feat-msg-attach

- For size-limited files read by a shared process, reject from `stat().st_size` before opening and use a bounded `MAX+1` read for growth races; an unbounded `read_bytes()` defeats the limit.
