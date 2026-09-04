# #480 — live incident evidence

Read-only source: `file:/mnt/data/Projects/Python/orchestra/data/orchestra.db?mode=ro`.

- Both final turns ended with `[[ORCHESTRA:SILENT_TURN]]`; silence is not the asymmetric fact.
- `golos-i18n-afk` made two `mcp__orchestra__send_message` calls: Prework at log 585117, then `DONE #98` at 585859. Both receipts had `message_kind=NULL`; the first persisted file stayed at 1 line / 464 chars.
- `kiosk-i18n-afk` made one such call, `DONE #99` at log 587258. Its file contained 34 lines / 3665 chars.
- Cause: `intercept_delivery_report()` treated the first legacy `message_kind=None` delivery as terminal and `report_path` became immutable. Correct authority is turn completion: legacy deliveries update a candidate while the member is pending; `record_terminal()` freezes it.
- Rejected: “only the broken child ended with the silence marker.” Both children did.
