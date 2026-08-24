# #332 metrics — current post-#309 reachability audit

## Baseline

| Measurement | Result | Evidence |
|---|---:|---|
| Audited main SHA | `1c5bf6db975322025fdc9413ae94fdee7abbcd54` | `evidence/commands.txt` |
| Python files under `app/` + `scripts/` | 92 | fresh `git archive main` + `pathlib` |
| AST definitions | 2,121 | `evidence/main-static-summary.txt` |
| AST calls | 18,716 | `evidence/main-static-summary.txt` |
| AST import nodes | 1,098 | `evidence/main-static-summary.txt` |
| Selected dynamic calls (`getattr`/`__import__`) | 231 | `evidence/main-static-summary.txt` |
| Syntax errors | 0 | fresh main archive AST parse |
| FastMCP decorated tools | 40 | `evidence/registry-summary.txt` |
| FastAPI route decorators | 100 | `evidence/registry-summary.txt` |
| Duplicate FastAPI `(verb,path)` keys | 0 | `evidence/registry-summary.txt` |
| Prompt skill files / manifest names | 6 / 6 | `check_pipeline_manifest.py --check` |
| Dashboard JS files | 5 | `evidence/js-summary.txt` |
| Template asset paths / missing | 14 / 0 | `evidence/registry-summary.txt` |
| JS syntax checks | 5/5 passed | `node --check` |

The branch used for the detailed generator was at #307 when the run began; `main` advanced to
#331 during the run. Its only source difference relevant to the AST count is
`scripts/orchestra_process_guard.py`; the four #331 identity/pidfd additions were independently
checked in the main archive and have production/test references.

## Candidate count

| Candidate class | Rows | Decision |
|---|---:|---|
| JS duplicate with zero production entry | 1 | CONFIRMED unreachable; future DELETE oracle, no edit now |
| Stale proxy scripts | 2 | LIKELY stale; future DELETE only after owner/external-copy check |
| Zero-LSP safety/tombstone helpers | 2 | KEEP/UNKNOWN; no delete |
| Decorator/registry false negatives | 2 | CONFIRMED live; KEEP |
| Runtime/prompt delivery consumers | 2 | CONFIRMED live; KEEP |
| Proven current FastAPI/MCP duplicate | 0 | #309 duplicate is already absent on current main |

## Method outputs

The reproducible source-only generators are `evidence/static_audit.py` and
`evidence/registry_audit.py`. They do not import app modules and have no write path outside
their stdout. Raw sanitized command/result records are in `evidence/commands.txt` and the
specialized evidence files. No database snapshot or live usage claim is made in this task.

## Exclusions

Payment/YouGile DB rows/schema, rare recovery/safety deletion, model routing #298, and live
provider probes are excluded. OpenCode static registry evidence is retained; provider/CLI
execution is intentionally unmeasured.
