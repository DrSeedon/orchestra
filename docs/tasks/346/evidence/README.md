# #346 evidence map

All command-derived facts were redirected to files in `raw/` by the command that produced them.
The research narrative cites the compact derived files below; source JSONL/envelopes remain beside
them.

## Load-bearing evidence

- `raw/static-score.json` — marker-derived precision/recall for all valid A/B/C static runs.
- `raw/static-{a1,a2,a3,a4}.json` — native `rg`+AST raw calls.
- `raw/static-b{1,2}-valid.json` — Serena MCP envelopes, tool outputs, stale mutation, resource samples.
- `raw/static-c{1,2}.json` — light MCP envelopes and tool outputs.
- `raw/static-resource-summary.json`, `raw/serena-memory-phase-summary.json`,
  `raw/serena-index-ready-summary.json` — resource/timing projections from the raw runs.
- `raw/serena-install-*.txt`, `raw/serena-install-disk.txt`, `raw/post-run-disk.txt` — pin,
  resolver failures, successful official-wheel install, and disk counts.
- `raw/serena-context-size.json`, `raw/light-context-size.json` — exact schema/instruction bytes
  plus disclosed tokenizer estimates.
- `raw/direct-serena-edit.json`, `raw/direct-serena-edit-acceptance.txt`,
  `raw/direct-serena-edit.patch` — direct `rename_symbol` E1 pass / E2 failure.
- `raw/luna-{a1,a2,a3,a4}-valid.*` — frozen native Luna baseline JSONL, acceptance, patch, and time.
- `raw/luna-summary.json` — provider usage/tool/wall aggregate. B/C rows are explicitly no-treatment.
- `raw/luna-mcp-control-b-{features,usercfg,codemode}.*` — forced controls proving the direct
  Codex evaluator had no Serena tool.
- `raw/codex-relevant-features.txt`, `raw/codex-feature-control.txt`,
  `raw/codex-code-mode-feature-control.txt` — CLI 0.149.1 resolved feature states.
- `raw/eval-control-tests-correct.txt`, `raw/eval-frozen-hash-control.txt` — pre-edit positive
  acceptance and frozen-SHA controls.
- `raw/secret-shape-scan-files.txt` — repository artifact scan for common credential shapes.
- `raw/user-serena-cleanup-verification.txt` — exact post-cleanup owner/mode/hash, absent scratch
  entry, and preserved contaminated log.

## Excluded evidence

- `raw/static-b1.json` — isolation variables were accidentally empty, LSP failed, user Serena
  fallback occurred; excluded permanently. The owner removed only its exact added project entry;
  the dated log remains.
- `raw/luna-a-eval1.*` — moving-main and scorer-cwd contamination; excluded despite a favorable
  patch.
- `raw/luna-b{1,2}-valid.*` and `raw/luna-c{1,2}-valid.*` — accepted patches but zero MCP calls;
  retained as delivery/no-treatment evidence, never treatment performance.
- Background launch failures before a model call are recorded in the conversation/platform job
  log; they produced no research measurement.
