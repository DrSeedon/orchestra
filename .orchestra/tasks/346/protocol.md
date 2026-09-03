# #346 frozen protocol — Serena vs native code intelligence

Frozen before the first Serena installation, server start, corpus query, resource sample, or
Luna evaluator call. Protocol changes after that point are forbidden; discovered defects are
reported as exclusions or exploratory follow-ups rather than silently changing the rules.

## Structured question

- **Context:** Orchestra coding agents operating on the current repository at
  `b3d1fccc61381b457c9f06baa55256c24cf454f7` with native shell/search/read/edit tools and
  ad-hoc Python `ast` scripts.
- **Change under test:** add pinned Serena `serena-agent==1.7.0` as an ephemeral project-local
  MCP server, using its official Codex context and language-server backend.
- **Baseline (A):** current native tools: `rg`, bounded file reads, shell, Python stdlib `ast`,
  and normal patch/edit commands. No Serena or substitute code-intelligence MCP.
- **Light candidate (C):** a stateless stdlib-only MCP with two read-only operations:
  `code_outline(path)` and `code_references(symbol, definition_path?)`. It parses Python AST,
  classifies exact lexical occurrences in Python/JS/HTML, has no daemon index, memory,
  onboarding, edit/refactor operation, dependency, or persistent config. Agents still edit with
  their native tools.
- **Outcome:** mechanical acceptance and retrieval precision/recall decide material benefit.
  Tool calls, provider input/output/cache tokens, wall time, startup/index time, process-tree
  RSS, disk, schema/instruction context bytes, failures, and stale behavior are costs/diagnostics.

## Hypotheses and falsifiers

1. **H1:** Serena materially improves Orchestra agents because precise cross-file symbol
   navigation/rename raises accepted-task count or lowers tools/tokens at equal acceptance.
   **Wrong if:** accepted tasks do not increase and paired tool/token deltas are within baseline
   repeat noise, while Serena adds a persistent process/schema/index cost.
2. **H2:** Serena helps primarily on plain, statically linked Python symbols and hurts or gives
   false zeros on decorators/registries, string dispatch, DOM wiring, or root-reachability.
   **Wrong if:** it achieves full production-edge recall in those classes without lexical/AST
   fallback and without false positives.
3. **H3:** a smallest light candidate captures the useful retrieval gain at materially lower
   cost, making a custom Orchestra integration worthwhile.
   **Wrong if:** it does not improve acceptance/tools over baseline, or matching Serena would
   require adding indexing, language-specific refactors, project state, and maintenance that
   erase its size/cost advantage.
4. **H4:** a Serena zero is safe evidence of no use after a positive LSP control succeeds.
   **Wrong if:** any zero-result target has a frozen decorator, registry, string, HTML/DOM, or
   dead-cluster edge in ground truth.

## Arms

| ID | Surface available to the evaluator | Pin/state rule |
|---|---|---|
| A | Native tools only | Current Codex/Luna CLI; all nonessential user MCP servers disabled by per-run overrides |
| B | Native tools + Serena | `serena-agent==1.7.0`; package/config/cache/data under a unique real-disk scratch root; usage reporting/dashboard disabled; never read or write user Serena config |
| C | Native tools + light MCP | Exact committed `eval/light_codeintel_mcp.py`; no cache/config files |

Serena is run under a process-tree memory ceiling of 1 GiB and CPU quota of two cores when the
host permits it. Failure to start under that ceiling is a measured failure, not grounds to raise
the ceiling. Scratch roots live on `/mnt/data`, not `/tmp` (which may be tmpfs). Every server is
terminated after its run; no service, live Orchestra config, user config, or production checkout
is changed.

## Frozen corpus

The controlled corpus under `corpus/fixture/` is shaped from current Orchestra failure modes.
Every location is identified by an immutable `G346_*` marker; line numbers are derived once from
those markers by the scorer, never hand-copied.

| Case | Query/decision | Relevant evidence counted |
|---|---|---|
| R1 plain Python | references to `plain_target` defined in `python/plain.py` | import and call bound to that definition; declaration, comments, strings, and unrelated method are not references |
| R2 decorators/registries | production entry edges for `refresh_models_endpoint` and `update_progress` | FastAPI/FastMCP decorators, route/tool literals, and router/tool registry mounts; a zero symbol-reference result is a false zero for liveness |
| R3 dynamic dispatch | production entry edges for `dynamic_target` | exact string literal plus `getattr`/dispatch line; comments are irrelevant |
| R4 JS DOM/event | references/entry edges for `openDeleteOrchModal` | direct JS callback plus HTML attribute/string wiring; comment/string noise is irrelevant |
| R5 dead cluster | classify `dead_root`/`dead_leaf` vs `live_root` | internal call edge plus absence/presence of a frozen production root; an internal reference alone is not liveness |
| R6 stale index | rename `stale_target` → `stale_renamed` outside the tool after warming | immediate old symbol must disappear and new definition/reference must appear; source-on-disk truth is checked before every query |
| R7 false-zero controls | server/tool health in each supported language | `plain_target` and direct JS callback are positive controls; no negative result is scored if its same-language positive control failed |

### Retrieval counting

- Unit = a frozen ground-truth edge `(case, target, path, marker, kind)`.
- True positive = returned path/line resolves to that exact marker and edge kind is relevant to
  the query. A returned declaration is not a reference. A comment/string is not a semantic
  reference unless the case explicitly defines string/DOM dispatch as a production edge.
- False positive = any returned location outside the relevant set, including unrelated
  same-named symbols. Duplicate locations count once after exact `(path,line)` deduplication.
- False negative = a relevant edge absent from the normalized output.
- Precision = `TP/(TP+FP)`; recall = `TP/(TP+FN)`. A tool returning nothing with a failed
  positive control is `INVALID`, not zero precision/recall.
- Symbol-reference precision/recall and production-edge precision/recall are reported
  separately. They must not be averaged: R2/R3/R4 deliberately contain edges LSP reference
  semantics do not claim to model.
- Dead-cluster correctness is a separate 3-label exact score (`dead`, `live`, `unknown`), not a
  reference metric.

## Frozen real edit tasks and mechanical acceptance

Each fresh Luna run receives both tasks on a disposable clean copy at the frozen commit. The
task text names the behavior and new symbol but does not reveal corpus answers, expected tool
choice, or the scoring implementation. The scorer, not the evaluator narrative, runs acceptance.

### E1 — small cross-file Python rename

Rename `pace_text` to `format_pace_text` across `app/` and `tests/`, preserving behavior and the
existing `_pace_of` local alias. Do not change user-facing strings.

Acceptance (all clauses required):

```sh
! rg -n '\bpace_text\b' app tests
rg -n 'def format_pace_text\b' app/limits_card.py
rg -n 'from app\.limits_card import format_pace_text as _pace_of' app/tg_bridge.py
uv run pytest -q tests/test_limits_card.py tests/test_tg_bridge.py::TestLimitsCommand::test_format_limits_chat_message_includes_consumed_window_and_pace
git diff --check
```

### E2 — broad rename with string-based test dispatch

Rename the callable `inject_skills_to_worktree` to `install_skills_to_worktree` across `app/`
and `tests/`, including imports, calls, comments/docstrings that name the callable, and
`monkeypatch`/`patch` string paths. Do **not** rename
`inject_skills_to_worktree_report` or change behavior.

Acceptance (all clauses required):

```sh
! rg -n '\binject_skills_to_worktree\b' app tests
rg -n 'def install_skills_to_worktree\b' app/prompting.py
rg -n '\binject_skills_to_worktree_report\b' app tests
uv run pytest -q tests/test_legacy_pipeline_skills.py tests/test_workspace.py tests/test_manager.py -k 'inject or legacy_empty_pipeline or empty_pipeline_would'
git diff --check
```

The negative guard on `inject_skills_to_worktree_report` prevents blind substring replacement.
The exact commands are frozen before any evaluator call. A collection/import failure is a task
failure. Evaluators may not edit tests to weaken acceptance. Patches are discarded after scoring
and never merged.

## Evaluator schedule and metrics

- Model/runtime: fresh `gpt-5.6-luna` Codex CLI sessions only; identical effort, prompt, commit,
  sandbox, and task pair across arms. No resume, auxiliary Sol, reviewer, or other provider.
- Main paired order: `A/B/A/B`. Light comparison: `A/C/A/C`. These are eight fresh sessions.
  The same two edit tasks are executed in every session. Load average is recorded at start/end.
- First attempt only. Timeout = 12 minutes per session. Timeout/error is a failure and is not
  retried. A run contaminated by a harness/setup defect is excluded only if the positive empty
  control fails before editing; the defect and raw output remain recorded.
- Acceptance per task: binary, from the frozen commands above. Also report total accepted tasks
  out of 2 per run and paired arm differences.
- Tool calls: count actual native/MCP tool-call events from JSONL; setup/acceptance calls by the
  external controller are excluded. Tool names are retained verbatim and classified only after
  the raw distribution is printed.
- Tokens/cache: use provider-emitted usage fields. Report input, cached input, output, total, and
  the invariant check `cached_input <= input` for every run. Do not combine counters if that
  invariant or semantics differ.
- Wall time: controller monotonic duration from provider process start to exit. Startup/index
  and query timings are separate and never subtracted from agent wall time.
- Report medians and every raw value. With two B and two C trials, claims about agent acceptance
  are bounded to this model/repo/task pair; no significance claim is allowed.

## Resource and context measurement

- Installation disk = apparent and allocated bytes of the isolated pinned environment/cache,
  recorded separately. Project index/state disk is measured before startup, after ready, after
  all queries, and after stale recovery.
- Startup = process launch to successful MCP initialize + tools/list. Index-ready = launch to the
  first successful positive-control symbol/reference call. Both are interleaved `A/B/A/B` for
  baseline-vs-Serena and `A/C/A/C` for baseline-vs-light; `loadavg` accompanies every row.
- RSS = sum of the server's own process tree by PPID, sampled at launch/ready/post-query/idle;
  peak comes from the enclosing resource monitor. Unrelated name-matched processes are excluded.
- Context = exact UTF-8 bytes/chars of MCP `tools/list` schemas, initialize instructions, and
  `initial_instructions` result, plus the provider-emitted input/cache deltas from evaluator
  sessions. Any tokenizer estimate is labeled an estimate, never substituted for provider usage.
- Failures include startup/tool timeout, malformed result, unsupported language, empty result
  after a successful same-language positive control, wrong/stale location, process ceiling hit,
  and any persistent write outside the isolated scratch root.

## False-zero and counter-evidence rules

1. Check server process, initialize result, tool list, and same-language positive control before
   interpreting an empty query.
2. Verify source markers on disk immediately before and after stale mutations.
3. Compare Serena against both semantic-reference truth and wider production-edge truth; do not
   fault it for comments on the former or credit it for silently missing strings on the latter.
4. Preserve official Serena evaluations as vendor evidence, not independent validation. Seek and
   report primary studies that disagree with “semantic tools always save tokens.”
5. A useful Serena case does not justify global installation; a failing registry/DOM case does
   not refute its static-symbol capability. The recommendation must name task routing boundaries.

