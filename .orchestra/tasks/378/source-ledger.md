# #378 source ledger

Snapshot date: 2026-08-23. The ledger distinguishes fetched primary sources from search attempts
that returned no matching artifact. No URL was reconstructed from a title, repository name, or
numeric similarity.

## L0 — supplied screenshot (only source for the result cells)

- Local file: `/home/kesha/orchestra/data/uploads/photo_20260823_132145_158488.jpg`
- SHA-256: `5a50cb541746d288f9a0a0e561b9eb9386fa5042b4c55135e107346e53cd3393`
- Image facts: JPEG/JFIF, 1280×636, 70,838 bytes; no EXIF source URL or caption metadata was
  present in the file. The current Orchestra transcript contains only the supplied path and the
  research request; it contains no forwarded-message entity or link.
- Extracted table: `raw-normalized.csv`. Every score/cost/count value in that file comes from the
  pixels in this screenshot. Exact model ids, effort, token components, retry count, schema
  fingerprint, score rubric, footnote `†`, and source links are absent.
- Evidence tier: **single secondary image**. It is evidence of what the screenshot says, not of how
  the runs were executed.

## L1 — source-recovery searches

### General web search

Opened searches included the exact literals and rare pairs:

- `"Three-body GPT" "Heat-2D Kimi" Pi Cline Hermes Agent`
- `"Ouroboros fixed run" "H200" k=5`
- `site:github.com "Heat-2D GPT" "Three-body Kimi"`
- `"$0.294" "Three-body" agent`, `"$3.455" "Heat-2D"`,
  `"$26.613" Ouroboros H200`, `"$4.761" "Hermes Agent"`

Result: no page reproducing the table and no raw trajectory/PR link. Search results that merely
contained common words such as *three-body*, *heat*, or *Hermes* were discarded.

### GitHub search

Authenticated, source-specific GitHub searches were run for code, commits, issues, and pull
requests. Exact-code results:

| Query | Result |
|---|---:|
| `"Three-body GPT"` | 0 |
| `"Ouroboros fixed run"` | 0 |
| `"$26.613" "Ouroboros"` | 0 |
| `"$0.294" "Hermes Agent"` | 0 |
| `"Heat-2D"` | 193 generic scientific-code hits; none also contained the table identifiers |

Global issue/PR searches combining `Heat-2D`, `Three-body`, `Pi`, `Cline`, `Hermes`, the cost
pairs, and `Ouroboros fixed run` returned zero matching record.

Two same-name repositories were checked separately:

- [`Q00/ouroboros`](https://github.com/Q00/ouroboros) is an Agent OS/workflow project and was a
  false lead; its public PR/issues did not contain this benchmark.
- [`razzant/ouroboros`](https://github.com/razzant/ouroboros) is the self-developing agent that
  matches the screenshot's `Ouroboros` row more plausibly. Current `main` at
  `e0f38f88924a6cc425fd9af2439d8d1b186ee55d` contains no exact table literal. GitHub GraphQL
  pagination checked all **153 PRs** and **137 issues**, including up to 100 comments/reviews per
  item, for the exact task/table literals; no match was found. Its current public README reports
  Terminal-Bench, OSWorld, CL-Bench, SWE-bench Pro, and GAIA results, not the screenshot's
  `Three-body`/`Heat-2D` cells.

The current [`earendil-works/pi`](https://github.com/earendil-works/pi) repository and its public
issues/PRs were also searched for the task names, comparator set, and “4x cheaper”; no matching
benchmark artifact was found.

**Recovery verdict: not identifiable from the supplied material and documented searches.** The
forwarded payload itself contains no link/entity bytes to recover. A public original may still
exist under unindexed attachments, deleted comments, private logs, or links that were present in
an earlier forward. The screenshot and current message do not carry enough information to identify
it. No PR number or trajectory URL is inferred.

CSV scope: `raw-normalized.csv` intentionally contains the screenshot's 28 cells plus the core
normalization dimensions requested for this audit (exact model, effort, task label, score, cost,
count semantics, input/cache/output/reasoning, retry, and tool-schema fingerprint). Dataset-level
run conditions that have no per-cell value at all — provider/surface, snapshot, service tier,
temperature, repository/SHA, prompt bytes, timeout/stop rule, acceptance command, model/tool-call
split, compaction, pricing date, and transport trace — are all explicitly `unknown` in L0 and
`Ledger gaps`; they are not silently imputed. In the CSV, `missing_in_screenshot` means that a
particular visible cell is absent/`н/д`; `unknown` means the column exists but the screenshot does
not identify the run value.

## L2 — Pi mechanics (current source, not claimed to be the screenshot version)

Primary-source snapshot: `earendil-works/pi` commit
`a69bef789bc95abf0acee16f7b4660b70b650bb9`, package version `0.84.2`.

- [System-prompt builder](https://github.com/earendil-works/pi/blob/a69bef789bc95abf0acee16f7b4660b70b650bb9/packages/coding-agent/src/core/system-prompt.ts):
  defaults to `read`, `bash`, `edit`, `write`, but appends project context files and skill metadata;
  therefore “Pi has a tiny fixed prompt” is not a run fact without the actual loaded resources.
- [Harness construction](https://github.com/earendil-works/pi/blob/a69bef789bc95abf0acee16f7b4660b70b650bb9/packages/coding-agent/src/server/create-harness.ts):
  the four default tool definitions, active tool names, prompt snippets, and prompt guidelines are
  assembled into the model request.
- [Compaction documentation](https://github.com/earendil-works/pi/blob/a69bef789bc95abf0acee16f7b4660b70b650bb9/packages/coding-agent/docs/compaction.md):
  auto-compaction triggers when `contextTokens > contextWindow - reserveTokens`; default reserve is
  16,384; a separate LLM summary call is persisted and followed by rebuilt context.
- [Settings documentation](https://github.com/earendil-works/pi/blob/a69bef789bc95abf0acee16f7b4660b70b650bb9/packages/coding-agent/docs/settings.md):
  agent-level transient retry defaults to 3 attempts with 2/4/8-second backoff; provider/SDK retry
  default is 0. These current defaults cannot be assigned to the screenshot runs without version
  and settings evidence.

## L3 — OpenAI usage-field contract

- [Official Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create):
  `usage` separates input and output; input details expose cached/cache-write tokens and output
  details expose reasoning tokens. `max_output_tokens` includes visible output and reasoning.
- Evidence tier: primary documentation. It defines how a matched OpenAI run can be normalized; it
  does not reveal the screenshot's missing fields.

## L4 — merged local Orchestra/Codex evidence

These are Tier-1 local measurements/current-code audits, not external links:

- `docs/tasks/374/research.md` + `codex-review-research.md`: model/effort request provenance;
  current `Sol → xhigh`, `Luna → high`; the resolver is model-aware, and no representative
  long-horizon Sol effort comparison exists.
- `docs/tasks/375/research.md` + review: input includes cached tokens on the OpenAI surface; current
  context/cache observations are not a causal cost comparison; configured/reported/accepted
  context are distinct.
- `docs/tasks/376/research.md`, protocol/raw artifacts + review: a matched app-server/exec fixture
  found roughly 2–3 seconds of warm local lifecycle avoidance, but cache drift invalidated the
  causal path verdict; total wall was dominated by model-wait noise in that sample.
- `docs/tasks/377/research.md` + review: current persistent app-server lifecycle, same-thread
  compact risks, and idle footprint; local process retention is not provider-token cost by itself.

## Ledger gaps

- Original public PR/log/trajectory URLs.
- Screenshot date, author, model versions/snapshots, provider surfaces, effort, temperature, and
  service tier.
- Exact task repositories/SHAs, prompts, score rubric/oracle, timeout/budget, and whether `0F`
  means a failed run or a zero score.
- Raw usage fields, retry events, tool schemas, prompt/context bytes, compaction events, transport
  traces, and the missing footnote defining `requests` versus `calls†`.
