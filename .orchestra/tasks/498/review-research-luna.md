<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently the arithmetic is the least suspicious part 😏 The credit recomputation is correct: Astra mean `4.566933`, Sol mean `2.045247`, ratio `2.23295×`. The main problem is overconfidence in the quota, capability, and evidence claims.

The raw idle record shows account drift independently of the burn:

> `{"label": "D_quiet_1", "at": "2026-09-05T05:07:34Z", "ids": ["codex", "codex_bengalfox"], "codex": 38, "spark5h": 11}`

## Findings

1. **suggestion:** `.orchestra/tasks/498/research.md:149-179` — The evidence supports “Astra probably shares the pool,” not `CONFIRMED`: `quota_gate.py:290-291` is only Orchestra’s local mapping, while the Spark control proves only that Spark has a separately exposed bucket. A provider could aggregate Astra into `codex` without exposing a model-specific id, and the allowance table does not prove equivalence of upstream limit ids. Downgrade this to `LIKELY` or `UNCERTAIN`, and state that “no added capacity” remains an inference.

2. **suggestion:** `.orchestra/tasks/498/research.md:197-217,423-431` — The 2.23× arithmetic is correct, but `n=3` per arm on one tiny synthetic ticket establishes an observed sample mean, not a confirmed per-ticket population cost. The document itself says the ticket was too easy and does not measure long agentic work. Rename the confidence to something like “OBSERVED for this exact ticket shape”; Verdict (b) can retain its current bounded wording.

3. **question:** `.orchestra/tasks/498/research.md:254-260` — “Image input / vision: yes” is not established by `app/backend_codex.py:2145-2150,2285-2295`; those branches translate emitted `imageView` events into Orchestra tool events. The input path at `app/backend_codex.py:1198-1226` sends text-only input. Narrow the claim to the existing `ViewImage` path or provide an actual image-ingress/vision probe.

4. **question:** `.orchestra/tasks/498/research.md:261-267` — `_CARRIED_BASE_KEYS` only proves that Orchestra does not copy `context_management` into managed configs. The cited raw evidence does not contain the claimed CLI status `context_management under development false`. Change “not reachable” to “not enabled by the managed config” unless the live CLI output is preserved.

5. **suggestion:** `.orchestra/tasks/498/research.md:430,433,471-500` — “Structurally drop-in” is too strong. `catalog_summary.json` shows Astra differs from Sol in `experimental_supported_tools`, `node_repl_auto_review_required`, `multi_agent_reasoning_effort`, instruction flags, and priority. The backend also has no Astra entry in `CODEX_TOKEN_PRICES` (`app/backend_codex.py:65-76`), and `_codex_cost` raises for an unknown model (`app/backend_codex.py:204-217`). Narrow the claim to “no new transport protocol is required.”

6. **suggestion:** `.orchestra/tasks/498/research.md:302-314,434` — The reviewed evidence set contains no `AGENTS.md`, `prompt-input` dump, `wc -c` output, or config file proving `203,311`, `224,147`, or full-file delivery. The subtraction `262,144 - 203,311 = 58,833` is correct conditionally, but the measurement is not reproducible from the supplied artifacts. Preserve the raw prompt-input result or downgrade the claim.

7. **question:** `.orchestra/tasks/498/research.md:66-74,427` — Four rejected aliases do not prove “no aliases” in general. They prove only that `astra`, `gpt-6`, `gpt-6-astra-latest`, and the case variant were rejected. Reword as “the tested aliases were rejected” unless a complete alias enumeration is available.

8. **nit:** `.orchestra/tasks/498/research.md:349-350` — The prose reports base-instruction sizes of `21,261` and `17,730` bytes, while the supplied raw files measure `21,269` and `17,766` bytes. State whether the prose excludes a newline or correct the numbers.

## Verdict

Revise before using this document for routing or spend decisions. The cost calculation is sound and the long-task caveat is appropriately cautious, but the quota conclusion should not be `CONFIRMED`, the image/capability table overstates what the cited code proves, and the AGENTS measurement lacks its claimed raw evidence.

Right now the confidence table is behaving like the Spark control: it proves the instrument can move a bucket, then invoices Astra for the conclusion.
