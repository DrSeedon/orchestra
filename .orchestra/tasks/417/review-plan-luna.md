<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Wonderful: all three RED checks are genuinely red, while several “safety” checks still inspect theater props 😏

## Summary

The plan has sound scope, an acyclic T1 → T2 → T3 rollout, explicit prices for `as_of`, one-hop links, and runtime delivery. I verified the exact commands with the common-repo `.venv`: all three scripts return `RC=1` on missing prompt behavior, not import or collection failure. No files were edited.

## Findings

### blocking: T1 does not verify the actual MCP tool surface

[test_t1...py:64](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py:64>)–79 checks source strings, not registered FastMCP tools. `knowledge` could remain exposed through an alternate decorator or manual registration, while `search_memory` could be removed and its signature left in a string literal. This violates the plan’s “agent-facing surface” and preserved-tool requirements. The acceptance test must inspect the actual tool registry and invoke `search_memory` through the disabled-RAG fallback.

### blocking: Runtime prompt delivery is a source-text oracle and omits the resumed seam

[test_t1...py:81](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py:81>)–93 only checks that factory source contains `context.system_prompt` and `system_prompt=`; a hardcoded or otherwise wrong prompt can pass. Also, the plan requires `SessionManager.assemble_prompt` resumed delivery, but T1 lists no `manager.py`/`session.py` seam or behavioral test. Require sentinel prompt assertions for Claude/Codex/Grok, plus resumed-session coverage including the full-prompt-overlay preservation branch.

### blocking: Forward-only legacy behavior has no defined changed-line input

[plan.md:89](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/plan.md:89>) says the validator receives changed paths/lines, but the defined CLI only accepts repeatable `--changed` paths [plan.md:159](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/plan.md:159>). A validator cannot distinguish legacy and new bullets inside the same changed topic: validating the whole file breaks forward compatibility; validating only known legacy files can let an invalid new line through. Specify diff/line-range semantics and add a mixed legacy-plus-invalid-new-line fixture.

### blocking: T3 validates an approval-shaped string, not an approved ticket

The valid fixture [test_t3...py:66](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t3_approved_one_hop_links.py:66>)–70 contains `approved: docs/tasks/417/plan.md#t3`, but the temporary test tree never creates that plan. Therefore the oracle cannot verify that the anchor exists or names the exact relation, source fact, and target required by [plan.md:106](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/plan.md:106>)–109. Add a real approval fixture and a wrong/nonexistent-anchor case, or explicitly document that semantic approval remains a human-only gate.

### blocking: Project isolation is not specified for validator paths or links

The plan requires target existence but does not require the target or `--changed` file to resolve beneath the supplied project-local `docs/kb` root. Absolute paths or `../` links could validate another project’s Markdown as canonical. Add canonical-root containment checks and negative traversal/absolute-path fixtures.

### blocking: Self-link rejection is promised but untested

[plan.md:108](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/plan.md:108>)–110 requires self-link rejection, but the four T3 negative fixtures [test_t3...py:71](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t3_approved_one_hop_links.py:71>)–78 do not include one. T3 can therefore pass while accepting a self-link. Add it to the immutable oracle and the planned mutation checks.

### suggestion: Clarify stale architecture statements about vector and generic knowledge

[agent-memory-architecture.md:5](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/kb/agent-memory-architecture.md:5>), 10, and 11 still describe vector projections, possible vector rebuild, and generic `knowledge` as accepted architecture, while line 12 records their closure. Since this file is canonical agent memory, label those statements historical/rejected or rewrite them consistently; `README.md` need not change.

### question: Declare the Git/shell baseline for the acceptance commands

The commands in [plan.md:210](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/plan.md:210>) use `git rev-parse --path-format=absolute` and POSIX shell substitution without stating a minimum Git/shell environment. If Linux plus a pinned Git version is intentional, state it; otherwise provide a portable fallback.

## Verdict

**Needs work; do not approve the plan yet.** The RED evidence is valid, but the acceptance layer does not yet prove MCP exposure, runtime/resumed prompt delivery, changed-line legacy compatibility, approval authenticity, or project isolation.

Review route: none — `codex_review` was unavailable in this session; Sol was not called.

> “Prompt delivery is checked on fresh assembly and `SessionManager.assemble_prompt` resumed path.”

Иначе это будет как approved-link без approved-плана: табличка есть, разрешения нет.

## Round (2026-08-30T08:06:30Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Splendid: the RED gate is genuinely red now, but one approval check is still made of cardboard 😏

## Summary

Round 2 fixes the MCP-surface, runtime/resume, legacy-diff, isolation, self-link, documentation, and command-portability findings. Exact paths are unchanged from `f72ae207`; all three commands return `RC=1` on their intended missing prompt behavior, with no import or collection failure. No files were edited.

## Findings

### Prior findings

- **FIXED:** T1 now checks the actual FastMCP registry and executes the registered disabled-RAG fallback ([test_t1...py:66](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py:66>)).
- **FIXED:** Runtime sentinel delivery and resumed assembly are behaviorally exercised ([test_t1...py:100](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py:100>)).
- **FIXED:** T2 uses unified diffs and proves mixed legacy/new-line behavior ([test_t2...py:128](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t2_lexical_fact_contract.py:128>)).
- **PARTIAL:** Approval now has a real receipt, but no existing receipt with a deliberately mismatched tuple is tested.
- **FIXED:** Traversal, absolute targets, and self-links are covered.
- **FIXED:** Vector/generic-knowledge statements have closure annotations; `README.md` remains out of scope.
- **FIXED:** The acceptance command now uses `--git-common-dir`; the stated Linux/POSIX baseline resolves the portability concern.

### blocking: T1 still permits a semantically restored mandatory search step

The negative check at [test_t1...py:45](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py:45>) rejects only the exact old heading `**Step 2 — \`search_memory(\``. A future prompt could move or reword the mandatory semantic call and pass while violating [plan.md:60](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/plan.md:60>)–61 and the mutation requirement at line 250. Add a stable explicit compatibility-only invariant and a mutation/oracle that fails when `search_memory` is made mandatory again.

### blocking: T2 does not mechanically cover the full fact contract

The immutable T2 fixtures cover missing `искать:`, missing evidence, duplicates, mixed legacy lines, and path escapes ([test_t2...py:80](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t2_lexical_fact_contract.py:80>)–155), but not the required `fact:` key shape, 1–6 anchor cardinality, one-line requirement, or section/status rules. A validator omitting those checks can pass the named acceptance and planned fixture list while accepting malformed canonical facts. Add focused invalid fixtures for those contract clauses.

### blocking: T3 does not reject a real receipt with the wrong tuple

`wrong-approval` references a nonexistent anchor ([test_t3...py:90](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-agent-memory/docs/tasks/417/acceptance/test_t3_approved_one_hop_links.py:90>)); it never references an existing receipt whose source fact, relation, or target differs from the canonical link. That leaves the core “mismatched approval receipt” rule untested despite the plan stating that the validator checks receipt matching. Add a second real receipt with a different tuple and use its valid anchor in the negative fixture.

## Verdict

**Needs work; reject pending the three blocking oracle fixes above.** The RED evidence is valid and the prior infrastructure/scope findings are largely fixed, with no new vector, second-store, path-escape, or `search_memory`-removal allowance found.

Review route: none — `codex_review`/Luna was unavailable in this session; Sol was not called.

> “validator проверяет структуру/совпадение уже одобренного receipt, а не изображает человека.”

Иначе receipt — это пропуск с печатью, но с чужим именем: выглядит официально, а на входе разворачивают.

## Author resolution after prose ceiling

- Accepted the round-2 compatibility blocker: immutable T1 now requires exactly one
  `search_memory` occurrence, and that exact occurrence says compatibility-only / not mandatory.
- Accepted the round-2 fact-contract blocker: immutable T2 adds bad key shape, zero/seven anchors,
  multiline fact, and wrong-section fixtures.
- Accepted the round-2 approval blocker: immutable T3 creates a second existing receipt with a
  deliberately different source/relation tuple and rejects a canonical link that cites it.
- Final immutable RED is `88390896`; all three scripts still return `RC=1` at their original
  missing-behavior assertion. No third review was run because the prose ceiling is two rounds.
  The last reviewer verdict remains `Needs work`; this resolution does not relabel it `APPROVED`.
