# #346 measurements

Frozen source: `b3d1fccc61381b457c9f06baa55256c24cf454f7`. During the run local `main`
advanced to `b693f302`; every accepted edit control was rebuilt from the frozen SHA. Raw command,
protocol, JSONL, patch, timing, cgroup, and acceptance outputs are under `evidence/raw/`.

## Retrieval corpus

The unit is a frozen `(case, target, path, marker, kind)` edge from
`corpus/ground-truth.json`. Definitions, same-name unrelated symbols, strings, and comments are
false positives for semantic-reference queries; decorator/registry/string/DOM edges are relevant
for the separately scored production-edge queries.

| Arm | Runs | Semantic TP/FP/FN | Precision / recall | Production TP/FP/FN | Precision / recall |
|---|---:|---:|---:|---:|---:|
| Native `rg` + stdlib AST union | 4 identical | 3 / 8 / 0 | 0.273 / 1.000 | 5 / 7 / 3 | 0.417 / 0.625 |
| Serena 1.7.0 LSP | 2 identical | 3 / 0 / 0 | 1.000 / 1.000 | 1 / 0 / 7 | 1.000 / 0.125 |
| Light exact-name AST/lexical MCP | 2 identical | 3 / 8 / 0 | 0.273 / 1.000 | 5 / 7 / 3 | 0.417 / 0.625 |

Evidence: `static-score.json`. The native/light precision numbers are candidate-output precision,
not final-agent precision: their rows are visibly classified and an agent can discard noise.
Serena's high precision is real and useful, but its 0.125 production-edge recall is not a defect
against LSP semantics; it is the measured limit on using semantic references as an Orchestra
liveness/deletion oracle.

Per-case observations:

- Plain Python: Serena returned the import and call and excluded the unrelated method, comment,
  string, and declaration (2/2, no noise).
- JavaScript: Serena/TypeScript returned the direct `addEventListener` callback but not the HTML
  `onclick` edge. The same-language positive control succeeded, so the missing HTML edge is a
  valid false zero rather than a dead language server.
- FastAPI/FastMCP-shaped decorators: both targets returned `{}` after the Python positive control
  succeeded; decorator and mount edges were absent from the symbol-reference result.
- Dynamic string dispatch: `dynamic_target` returned `{}`; the exact string and `getattr` edge
  were absent.
- Dead cluster: Serena found `dead_root → dead_leaf`, but both unreferenced `dead_root` and
  decorator-rooted `live_root` returned `{}`. References alone cannot classify root reachability.
- Stale external atomic rename: in both runs Serena immediately returned no old symbol and the new
  `stale_renamed` definition, both immediately and after 1 second. No Python/TypeScript stale
  failure was reproduced.

## Real edit controls

### Native Luna baseline

Four fresh Luna sessions received both frozen rename tasks without any code-intelligence MCP. All
8/8 task outcomes passed external acceptance: old names absent, new definitions and alias present,
8 E1 tests green, 14 E2 tests green, and `git diff --check` green. Provider-emitted counters:

| Run | Accepted | Tool calls | Input | Cached input | Output | Wall |
|---|---:|---:|---:|---:|---:|---:|
| A1 | 2/2 | 12 | 482,672 | 422,400 | 5,971 | 139.84 s |
| A2 | 2/2 | 48 | 758,876 | 687,360 | 9,089 | 250.92 s |
| A3 | 2/2 | 11 | 413,575 | 361,472 | 5,126 | 169.45 s |
| A4 | 2/2 | 11 | 576,750 | 514,304 | 6,769 | 153.23 s |
| Median | 8/8 total | 11.5 | 529,711 | 468,352 | 6,370 | 161.34 s |

`cached_input <= input` held in every run. The unchanged baseline's input range was
413,575–758,876 and tool-call range 11–48, so two-run treatment deltas smaller than this noise
cannot be assigned causally. Evidence: `luna-summary.json`, per-run JSONL/acceptance/patch files.

### Direct Serena `rename_symbol`

The Serena server itself was then given the same two tasks without an LLM:

| Task | Tool result | Mechanical acceptance |
|---|---|---|
| E1 `pace_text` | 2 changes, 0.922 s | PASS: 8 tests, alias and absence checks green |
| E2 `inject_skills_to_worktree` | 5 changes, 1.505 s | FAIL: old token remained in 4 comment/string paths; 6 failed / 8 passed |

The E2 misses were exactly the non-semantic consumers that matter to this repository:
`monkeypatch`/`patch` import strings and a docstring. Serena correctly changed the Python
definition/import/call graph, preserved `inject_skills_to_worktree_report`, and produced a clean
diff, but the task failed. Evidence: `direct-serena-edit.json`,
`direct-serena-edit-acceptance.txt`, and `direct-serena-edit.patch`.

This matches the frozen counter-hypothesis: a semantic rename is atomic only over what the
language server defines as a reference. Orchestra renames frequently include tool names, route
strings, patch targets, comments, prompt text, or JS/HTML wiring, so `rg` remains mandatory.

### Agent MCP delivery boundary

Eight additional Luna edit sessions were scheduled A/B/A/B and A/C/A/C. All returned accepted
patches, but every B/C run recorded **zero MCP tool calls**. Forced-use controls returned
`SERENA_UNAVAILABLE`; no Serena process/log was created. Three delivery attempts were preserved:

1. isolated `--ignore-user-config` plus session `mcp_servers.*` overrides;
2. the same with removed `tool_search` flags requested explicitly;
3. normal user-config layering with unrelated MCP servers disabled.

Codex CLI 0.149.1's resolved feature table reports `tool_search` as removed/false and
`tool_search_always_defer_mcp_tools` as removed/true; enabling the under-development code-mode
flags still did not expose the server to `exec`. `codex mcp list` did parse a synthetic nested
override, so configuration parsing and model delivery are distinct steps. Therefore B/C token
deltas in `luna-summary.json` are **excluded as no-treatment** and no agent-level Serena or light
acceptance claim is made.

## Startup, memory, disk

All server runs used fresh real-disk scratch roots, a transient user cgroup, `MemoryMax=1G`,
`CPUQuota=200%`, and no dashboard/usage reporting. `SERENA_HOME` and UV cache paths were isolated.

| Metric | Native scan | Serena 1.7.0 | Light MCP |
|---|---:|---:|---:|
| Ready / first tool-list | 0.006–0.009 s | 1.667 / 1.738 s | 0.056 / 0.063 s |
| First positive symbol/reference ready | included above | 9.931 / 7.197 s | included above |
| Full frozen query sequence | 0.062–0.066 s | 18.588 / 15.922 s | 0.129 / 0.132 s |
| Cgroup memory at tool-list | n/a | 133,840,896 / 147,439,616 B | not separately sampled |
| Cgroup memory after queries | n/a | 661,700,608 / 723,554,304 B | 6,135,808 / 6,631,424 B peak |
| Cgroup memory peak | n/a | 714,182,656 / 772,153,344 B | 6,135,808 / 6,631,424 B |
| Sum of process RSS peak | n/a | 854,642,688 / 858,275,840 B | 13,254,656 / 13,123,584 B |

Summed RSS double-counts shared pages; cgroup memory is the resource-ceiling ground truth. The
post-query Serena cgroup contained eight processes (Serena, uv/provider helpers, Python and both
language-server trees). Direct real-edit peak was 755,163,136 B. Evidence:
`static-resource-summary.json`, `serena-memory-phase-summary.json`,
`direct-serena-edit.json`.

Pinned installation and isolated state:

| Component | Apparent bytes | Allocated bytes |
|---|---:|---:|
| Serena venv (72 dependencies) | 93,832,359 | 110,252,032 |
| Initial UV download/cache | 35,723,437 | 40,378,368 |
| Per-cold-run Serena home/LSP | 25,982,260 | 26,456,064 |
| Per-cold-run LSP UV cache | 18,859,182 | 39,735,296 |
| Per-project `.serena` state | 24,115 | 61,440 |
| Cold isolated total | 174,421,353 | 216,883,200 |

The light prototype is 267 lines / 10,967 bytes and writes no cache/config/index. Its size is not
evidence that it is good: its scored output was identical to the native union and it added no
measured capability.

## Context surface

Exact serialized protocol surface (UTF-8):

| Surface | Serena | Light MCP |
|---|---:|---:|
| Tools exposed | 23 | 2 |
| Compact `tools/list` schemas | 29,651 B | 605 B |
| MCP initialize instructions | 132 B | 106 B |
| On-demand Serena manual | 6,508 B | n/a |
| `o200k_base` estimate: schemas | 6,569 tokens | 139 tokens |
| `o200k_base` estimate: bootstrap/manual | 31 / 1,372 | 20 / n/a |

The tokenizer values are estimates; bytes are exact. No provider context delta is reported because
the direct Codex evaluator never received either MCP. In a client that defers MCP schemas, all
29,651 bytes need not be in every model request; in an eager client they are the available schema
surface. Serena 1.2+ deliberately made the 6,508-byte manual on-demand, so only its 132-byte
bootstrap is connection-time instructions. Evidence: `serena-context-size.json`,
`light-context-size.json`, raw MCP envelopes.

## Invalid/excluded runs

- One setup command passed empty isolation variables; Serena fell back to the pre-existing
  `~/.serena`, wrote a new dated log, and re-saved `serena_config.yml` with one proven added
  project entry: `/mnt/data/task346-serena.tHyHCU/run-b1` (line 189 after the run). The server
  stopped; all subsequent commands asserted non-empty `SERENA_HOME`. The owner removed only that
  exact entry; read-only verification recorded it absent while owner/mode remained
  `maxim:maxim`/`0600`. The dated log was intentionally preserved as evidence. This contaminated
  run remains permanently excluded.
- Two background-runner path/cwd failures exited before a model call.
- One model run used moving `main` (`b693f302`) instead of frozen `b3d1fccc`; its favorable patch
  is excluded. All accepted controls compare hashes against the frozen source.
- B/C Luna sessions with zero MCP calls are retained as harness/delivery evidence but excluded
  from treatment efficiency.
