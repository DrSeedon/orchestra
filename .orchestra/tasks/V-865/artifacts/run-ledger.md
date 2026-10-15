# V-865 run ledger

- Dynamic workflow: `V-865-6eefb1192d73`; background job `bg-586b99459e`; complete, exit 0.
- Primary A/B stage: 24/24 completed; 12 A/B pairs.
- Blind assessor: 1/1 completed in Stage 2, a distinct Luna workflow call/session.
- Resolved model/runtime in journal: `gpt-6-luna` / `codex` for all 25 calls. Billing route: `subscription`; no API-credit calls.
- `cost_usd` recorded in workflow journal (API-equivalent, not a cash/API invoice): A/B stage `$0.02910934`; assessor `$0.00196958`; total `$0.03107892` of `$15` authorized ceiling.
- Workflow limits: `budget_usd=15`, `max_calls=36`, `max_concurrency=3`.
- Run files produced by Orchestra: `/home/kesha/orchestra/data/workflow-runs/V-865-6eefb1192d73/manifest.json`, `journal.jsonl`, `request.json`, `steps/`, `calls/`. Copies of the raw answer text and raw blind score are preserved in this task's `raw-responses.md` and `blind-judge.json`.
- No tool call was missing, timed out, or stopped by the budget. The blind-evaluator prompt contained conflicting X/Y position wording and per-case randomized labels. It still returned both per-answer correctness scores for every case as 1; swapping X/Y cannot change the paired outcomes, which are all ties. Treat the label-specific subfields as unreliable, but the A/B result is unchanged.
