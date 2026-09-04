<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently the receipt card now audits its own fields 🙃: no blocking crash or XSS issue, but three P2 correctness gaps remain.

## Findings (Conventional Comments)

suggestion [P2] Decode Python escape sequences correctly  
**File:** `app/static/js/tool-renderers.js:747-748`

A valid repr such as `{'outcome_evidence_ref': 'line1\nline2'}` is rendered as `line1nline2`, because every backslash simply drops its escape meaning. This can corrupt the only displayed evidence value when it is absent from call arguments.

---

suggestion [P2] Treat arrays as unreadable call arguments  
**File:** `app/static/js/tool-renderers.js:785-788`

`JSON.parse('[]')` produces an object according to `typeof`, so `_callArgsHaveEvidence('tool: []')` returns `false` and echoes the evidence. Arrays are not valid `{json args}` objects; they should take the deliberate “do not render evidence” fallback.

---

suggestion [P2] Reject partially parsed malformed receipts  
**File:** `app/static/js/tool-renderers.js:771-775`

The parser accepts fragments from invalid payloads. For example, `{'receipt_id': 'x', 'status': }` becomes `{receipt_id: 'x'}`, which then passes the receipt guard and suppresses normal rendering. Malformed non-receipt results should fall through instead.

---

question [P2] Should the card include `author_outcome`?  
**File:** `app/static/js/tool-renderers.js:725-728`

The added fixture populates `author_outcome: "disputed"`, but the whitelist never renders it. The call argument contains the related `outcome`, but the receipt card itself does not show the recorded outcome.

## Verdict

**ACK** — no blocking findings. The exact dispatch branch is scoped correctly, and all inserted values use `textContent`.

Verbatim changed line: `const _RECEIPT_HASH_FIELDS = new Set([`

At least the raw dict stopped printing itself twice; the receipt still has a few forms to fill out.
