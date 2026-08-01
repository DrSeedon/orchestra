# Worker memory

- Claude CLI `429 You've hit your monthly spend limit` with
  `duration_api_ms=0` and cost `$0` can mean the 5h window is exhausted while
  supplemental capacity is disabled, not a payment limit. Before classifying
  it, check `/api/usage` → `anthropic.five_hour` and `extra_usage`.
