# Durable notes

- Quota policy values originate from the service startup environment; `app.quota_gate.quota_policy()` watches `.env` mtime and applies changed `QUOTA_*` values on the next decision. Keep dashboard policy snapshots wired to that function rather than importing threshold constants.
