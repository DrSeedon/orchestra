# #346 — does Serena materially improve Orchestra coding agents?

## Question

**Context:** Orchestra agents work in a Python/FastAPI/FastMCP plus JavaScript/HTML repository,
using native shell/search/read/edit tools and task-local stdlib AST scripts. The frozen source is
`b3d1fccc61381b457c9f06baa55256c24cf454f7`.

**Change under test:** add stable `serena-agent==1.7.0` as an ephemeral, project-local MCP server
with Python and TypeScript LSPs.

**Baseline:** current `rg` + bounded reads + native edits + Python `ast`. **Third arm:** a
stateless 267-line/10,967-byte MCP that only outlines files and classifies exact-name
Python/JS/HTML occurrences.

**Measurable outcome:** accepted real edits and retrieval precision/recall decide material value;
tool calls/tokens/cache, wall/start/index time, cgroup memory, disk, schema context, stale behavior,
and failures decide cost. The corpus, marker schema, counting rules, A/B/A/B order, tasks, and
acceptance were frozen in [`protocol.md`](protocol.md) before the first Serena process.

## Hypotheses considered

1. **H1 — Serena raises correctness or lowers work on symbol-centric edits.** Falsifier: native
   agents already pass the edits, and Serena adds no acceptance or call/token gain beyond baseline
   repeat noise.
2. **H2 — Serena is useful for static symbol identity but incomplete for Orchestra liveness.**
   Falsifier: decorator/registry, dynamic string, HTML/DOM, and rooted-cluster edges all appear in
   Serena results with high recall.
3. **H3 — a tiny custom MCP captures the useful delta cheaply.** Falsifier: it produces the same
   candidates as native AST/lexical search and no measured acceptance gain.
4. **H4 — a Serena zero is meaningful after a same-language positive control.** Falsifier: a
   zero-result target has a frozen production entry edge.

## Findings

### F1 — Serena materially improves precision for true semantic-reference questions

On the frozen semantic subset Serena returned all 3 relevant references and zero noise
(precision=recall=1.0) in both runs. The native/light union also found all 3, but returned 8
irrelevant declarations, comments, strings, or same-name symbols (precision 0.273). Serena
correctly separated `plain_target` from an unrelated method and returned the direct JS callback.

**CONFIRMED — tier 1 direct measurement, two identical runs.** This is the positive case: known
symbol, statically resolvable Python/TypeScript, question phrased as “which code symbols reference
this definition?” Official Serena describes exactly this symbol/reference surface [1][2], and its
vendor evaluations report the same precision advantage over grep [3][4].

### F2 — Serena is not a reachability, registry, or dead-code oracle for Orchestra

For wider production-entry truth Serena found 1/8 relevant edges (recall 0.125, precision 1.0):

- FastAPI- and FastMCP-shaped decorated functions both returned `{}` after the Python positive
  control succeeded;
- a `getattr` + string-dispatch target returned `{}`;
- TypeScript found the direct JS callback but not the HTML `onclick` edge;
- `dead_root` and decorator-rooted `live_root` both returned `{}`, making live and dead roots
  indistinguishable from references alone;
- an internal `dead_root → dead_leaf` edge was found, but internal reachability does not prove a
  production root.

The native/light candidate union found 5/8 edges (recall 0.625) with noise. That is not a claim
that lexical search is intrinsically smarter: it shows that the information Serena deliberately
filters out—strings, decorators, markup, and text wiring—is load-bearing in this repository.
Official Serena docs themselves say HTML cross-file references are not meaningful/exposed [5].
Task #332 independently observed the same real-repo false zeros for a live FastMCP tool and
FastAPI route [6].

**CONFIRMED — tier 1 controlled measurement plus independent current-repo measurement.** H4 is
refuted. A Serena zero remains a candidate generator only, never deletion proof.

### F3 — semantic rename is atomic only inside LSP reference semantics

Direct `rename_symbol` on the two frozen real tasks gave a clean split:

- `pace_text → format_pace_text`: 2 changes in 0.922 s; absence/alias checks and 8 tests passed.
- `inject_skills_to_worktree → install_skills_to_worktree`: 5 changes in 1.505 s; the Python
  graph changed, but four comment/string consumers remained and 6 focused tests failed. The
  misses were `monkeypatch`/`patch` import strings and a docstring.

Four fresh native Luna baselines completed both tasks, 8/8 accepted. Serena did not corrupt the
broad rename; it faithfully applied the language server's narrower contract. The task required a
larger contract.

**CONFIRMED — tier 1 real-file edit plus mechanical tests.** This directly counters the vendor
wording that cross-file rename is generally “atomic and semantically correct” [3]: that statement
is true only for language-server references. A 2026 primary LSP-vs-grep study reports the same
boundary: enriched LSP still misses rename obligations in comments and strings [7].

### F4 — Serena's measured cost is large relative to Orchestra's native discovery path

Pinned installation required 72 dependencies. Cold isolated totals were 174,421,353 apparent
bytes / 216,883,200 allocated bytes including venv, caches, LSP home, and project state. On the
tiny corpus:

- MCP tools-list ready: 1.667 / 1.738 s;
- first positive symbol/reference ready: 9.931 / 7.197 s;
- peak cgroup memory: 714,182,656 / 772,153,344 B;
- post-query memory: 661,700,608 / 723,554,304 B;
- full query sequence: 18.588 / 15.922 s.

The server exposed 23 tools. Their compact schemas were exactly 29,651 B; the connection bootstrap
was 132 B; the on-demand manual was 6,508 B. `o200k_base` estimates are 6,569 + 31 + 1,372 tokens,
but provider-token cost depends on whether the client eagerly injects or defers tool schemas.
Serena 1.2+ explicitly made the manual lazy to reduce initial context [8].

The light MCP used 6.1–6.6 MB peak cgroup memory, was ready in 0.056–0.063 s, and exposed 605 B
of schemas. Native scans completed the whole corpus in 0.062–0.066 s. Exact phase/process/disk
rows are in [`measurements.md`](measurements.md).

**CONFIRMED — tier 1 cgroup/disk/protocol measurement.** These are cold, two-language,
ephemeral numbers on this machine; shared LSP binaries/caches would reduce disk/start download
cost, but each active multi-project Orchestra agent still needs a project-bound, stateful server.
Official Serena recommends separate stdio instances when agents work on different projects [9].

### F5 — no Python/TypeScript stale-index defect reproduced, but the confidence boundary is language/version-specific

After warming the old symbol, an external atomic file replacement changed
`stale_target → stale_renamed`. Both Serena runs immediately dropped the old symbol and found the
new one, and remained correct after 1 s. Version 1.6.1 introduced external-file polling for this
class of stale result [10].

However, Serena's current unreleased changelog still lists language-specific silent-stale or
silent-incomplete fixes for Clojure, Scala, and TypeScript/tsserver crashes [11]. Stable 1.7.0 also
contains multiple indexing/ignore/timeout fixes [12].

**CONFIRMED for this Python/TypeScript fixture; UNCERTAIN outside it.** The experiment refutes
“Serena is generally stale” and does not support “Serena indexes are generally fresh.”

### F6 — agent-level Serena token/call savings remain unmeasured, not negative

The native Luna baseline accepted 8/8 tasks. Its identical-task variation was large: 413,575–
758,876 input tokens, 11–48 tool calls, and 139.84–250.92 s. That baseline noise alone forbids
crediting small two-run deltas.

The preregistered B/C Luna sessions all produced accepted patches but recorded zero MCP calls.
Forced-use controls returned `SERENA_UNAVAILABLE`; Codex CLI 0.149.1 parsed the nested server in
`codex mcp list`, but did not deliver it to `exec`. Its resolved feature table has `tool_search`
removed while deferred MCP behavior remains. Even under-development code-mode flags did not make
the tool available. Official OpenAI documentation confirms Luna itself supports MCP and Tool
Search [13], so this is a client/harness delivery boundary, not a model-capability claim.

**UNCERTAIN — no valid treatment reached the evaluator.** Every B/C efficiency delta is excluded.
The direct Serena capability measurements remain valid because they used the MCP protocol
directly. This gap is material: claims that Serena improves Orchestra-agent tool/tokens require a
future eval through the exact managed backend path that actually exposes custom MCP tools.

### F7 — a global custom lightweight alternative is not justified by these results

The 267-line light MCP produced exactly the native union's scores: semantic 3/8/0 and production
5/7/3 (TP/FP/FN). It is faster/smaller than Serena because it is a structured `rg`+AST wrapper,
not because it adds semantic identity. Its model treatment was also unavailable, so no acceptance
gain exists.

**LIKELY — tier 1 output/resource equivalence, agent effect unmeasured.** Do not build/integrate a
global MCP yet. The justified lightweight artifact is narrower: retain task-local, stdlib AST
scripts for decorator/registry/dead-cluster audits, with exact positive controls and lexical arms.
If repeated agent traces later show a stable multi-call pattern, promote only that one composite
query to a server tool. Primary research supports task-specific routing rather than one universal
retriever: no family dominates across 427 samples [14], a grep-trained retriever helps only after
sufficient precision [15], while an earlier tree-sitter symbol-navigation ablation shows genuine
benefit on repo-level generation [16].

## Counter-evidence

- Serena's own five published evaluations are favorable and consistently identify cross-file
  refactors/navigation as the highest-value surface [3][4]. They are meaningful vendor evidence,
  but the methodology makes the same agent executor and evaluator and lets it select concrete
  tasks [17]; it has no frozen external acceptance comparable to E2 here.
- CODEAGENT's primary ablation found removing tree-sitter symbol navigation reduced Pass@1 from
  30.7 to 22.8 on its benchmark [16]. This argues against “symbol tools never help,” not for a
  global Serena process on Orchestra.
- The preliminary LSP study reports LSP benefits for precision/reference tasks and weaker models,
  even though its overall tokens-to-success answer is usually negative [7]. This supports a
  routed/niche Serena option.
- The current experiment has only 8 production edges, 3 semantic edges, 2 real edits, and two
  resource repetitions. It can establish mechanisms and exact local costs, not universal rates.
- The Serena agent arm failed at client delivery. No conclusion about Luna's propensity to use a
  working Serena tool is permitted.

## Verdict and recommendation

**Do not add Serena globally to Orchestra agents now.** It materially improves one narrow task:
high-precision static semantic references and simple all-code refactors. It materially hurts the
default surface through a 0.66–0.72 GB resident project server, ~8.6 s median first-symbol
readiness, 23 schemas, and false confidence if zeros or renames are treated as complete across
decorators, strings, markup, registries, or dead clusters.

If Serena is revisited, route it explicitly to known-symbol, static-language navigation or a
simple refactor whose acceptance separately scans strings/comments/config and runs tests. Never
use it alone for dead-code deletion, FastAPI/FastMCP liveness, dynamic dispatch, prompt/tool names,
or JS/HTML wiring. Keep `rg` mandatory beside every rename.

Do not integrate the light prototype either. Its useful parts are already available through
native `rg` and disposable AST scripts. The next justified experiment is a managed-Orchestra Luna
A/B with working MCP delivery and a larger frozen task corpus—not more index/service code.

## Affected files, risks, and edge cases for any future phase

No production, tests, pipeline, service, database, live config, or user integration was changed.
A future Serena integration would affect managed MCP assembly/session startup, per-worktree
project configuration, process/cgroup budgets, context/tool delivery, shutdown/orphan handling,
and language-server caches. Required edge coverage includes:

- decorators and generated/runtime registries;
- `getattr`/`importlib`/string dispatch and monkeypatch strings;
- JS/HTML/template/event wiring;
- dead SCCs versus production roots;
- external edits, branch switches, and language-server crash/partial-index signals;
- multi-agent per-project process count and aggregate memory;
- a lexical post-rename scan plus pre-existing tests.

One excluded setup run did touch pre-existing user Serena state because an empty isolation value
fell back to `~/.serena`. It added the scratch project to `serena_config.yml` and wrote a dated
log. The owner removed only the exact scratch entry; read-only verification shows it absent with
owner/mode `maxim:maxim`/`0600`, while the log remains as evidence. The run is permanently
excluded. Any future Serena experiment must snapshot user-config hash+mtime, require a non-empty
`SERENA_HOME` resolved under the task scratch root before launch, and verify the user config hash
unchanged after every arm.

## Review decision gate

- Changed consumers: research artifacts under `docs/tasks/346/`, new KB topic, and personal worker
  memory; no runtime consumer.
- Author: `gpt-5.6-sol` / Codex runtime (live Orchestra metadata).
- AC: answer material benefit/harm, exact costs, custom-alternative decision, raw reproducibility,
  counter-evidence, and confidence boundaries.
- Mechanical checks: frozen-marker scorer, external acceptance, raw-output inventory, secret-shape
  scan, link/source inventory, and git cleanliness.
- **Review: none — the user explicitly prohibited auxiliary review/provider calls.** The
  `codex-debate` docs/fact route was limited to mechanical completeness; no Luna/Sol reviewer was
  launched.

## Sources

1. [Official Serena tools](https://oraios.github.io/serena/01-about/035_tools.html) — primary.
2. [Official Serena features](https://oraios.github.io/serena/01-about/025_features.html) — primary.
3. [Official Serena Claude Code evaluation](https://oraios.github.io/serena/04-evaluation/030_results/010_cc_on_tianshou.html) — vendor primary measurement.
4. [Official Serena Codex evaluation](https://oraios.github.io/serena/04-evaluation/030_results/020_codex_on_jbplugin.html) — vendor primary measurement.
5. [Official Serena configuration/language limits](https://oraios.github.io/serena/02-usage/050_configuration.html) — primary.
6. `docs/tasks/332/research.md` and `docs/tasks/332/evidence/serena.txt` — local direct measurement.
7. [Does a Language Server Save Tokens for Coding Agents?](https://arxiv.org/abs/2608.13568) — primary preprint, 2026.
8. [Official Serena changelog: lazy instructions](https://github.com/oraios/serena/blob/main/CHANGELOG.md) — primary source.
9. [Official Serena running/project workflow](https://oraios.github.io/serena/02-usage/020_running.html) — primary.
10. [Official Serena 1.6.1 changelog](https://github.com/oraios/serena/blob/main/CHANGELOG.md) — primary.
11. [Official Serena current unreleased fixes](https://github.com/oraios/serena/blob/main/CHANGELOG.md) — primary, not stable release behavior.
12. [Official Serena 1.7.0 changelog](https://github.com/oraios/serena/blob/main/CHANGELOG.md) — primary.
13. [Official OpenAI GPT-5.6 Luna model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna) — primary.
14. [Agent Retrieval Bench](https://arxiv.org/abs/2607.24882) — primary preprint, 2026.
15. [CodeGrep](https://arxiv.org/abs/2608.05886) — primary preprint, 2026.
16. [CODEAGENT, ACL 2024](https://aclanthology.org/2024.acl-long.737/) — peer-reviewed primary research.
17. [Official Serena evaluation methodology](https://oraios.github.io/serena/04-evaluation/010_methodology.html) — vendor methodology.
18. [PyPI `serena-agent` 1.7.0](https://pypi.org/project/serena-agent/) — primary package registry; wheel SHA256 recorded locally.
