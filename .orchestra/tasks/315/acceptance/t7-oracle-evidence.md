# T7 prompt/document cutover oracle evidence

Date: 2026-08-25. No production, application-test, live database, service, provider, model, eval or
review call was made while freezing this oracle. The explicit no-review constraint overrides the
high-risk Sol route selected by `codex-debate`; the evidence is the frozen corpus, positive controls,
real consumer assembly and compound mutants below.

## Current production trace

- `app.pipeline.build_system_prompt` reads role layers and modules from
  `pipelines/default/prompts/`; `app.manager.ROLE_SYSTEM_PROMPT` is the production role owner.
- Claude appends that prompt through `ClaudeAgentOptions.system_prompt`; Codex sends it as
  `developerInstructions`; Grok writes an ACP agent profile with `agents_md: true`; Harness adds its
  native tool guide and installs the result as the system message. The control executes all four
  consumers without starting a provider.
- Claude and Codex discover pipeline skills from separate generated `.claude/skills/` and
  `.codex/skills/` addresses. The control creates an isolated Git consumer and proves both addresses
  receive the exact tracked skill-owner bytes.
- The existing MCP `knowledge` tool reaches `POST /api/knowledge` and `knowledge_api`, but the MCP
  registry still also exposes `search_memory`. Current assembled prompts still direct agents to
  Markdown files and `search_memory`; `app.ia.cutover`, `scripts.ia_document_inventory` and
  `scripts.ia_migrate_documents` do not exist.

## Frozen corpus and contract

The source cutoff is commit `34fb2350a8224f2991dbe722afc29070daf02bee`. Its tracked inventory
contains 1,505 individually classified paths:

- 1,346 immutable evidence/cold archive paths: 1,321 `docs/tasks/**/*.md`, 21 `docs/kb/*.md`,
  three session archives and `TODO.md`;
- 159 active skill/resource sources: 134 worker-memory files, 23 pipeline prompt/skill Markdown
  owners, `CLAUDE.md` and `pipelines/default/pipeline.yaml`.

Each row freezes path, class, source commit, Git blob, SHA-256, byte size and a typed `orch://`
alias. Aliases use UUIDv5 namespace `31500000-0000-4000-8000-000000000007` over
`{source_commit}:{path}:{git_blob}`. `AGENTS.md`, native skill homes, the Grok profile and Harness
system message are classified as derived delivery addresses, not extra source owners.

The behavior contract exposes one internal cutover owner (`app.ia.cutover.cutover_api` under
`document_cutover_mode`) and two real administrative consumers (`inventory_api` and
`migration_api`). Agent reads stay on the existing MCP `knowledge` → HTTP → `knowledge_api` chain.
Legacy, shadow and canonical generations are explicit; canonical activation requires independently
consistent parity, privacy, rollback, prompt-delivery, live-cutover and rebuildable-projection
receipts. Rollback advances generation and retains canonical events.

## Frozen selection and controls

The oracle contains four invariant controls, five positive behavior nodes and seven compound-mutant
nodes. Controls pin all 21 T1–T6 test/contract/record artifacts; validate every frozen blob through
Git; execute all 20 runtime×role prompt consumers and both native skill homes with a positive
sentinel; execute the live MCP→HTTP→owner route; and prove the order/additive-metadata alternate plus
dual-truth/stale-runtime detectors are material.

Control command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py::test_t7_control_frozen_inventory_and_t1_t6_hashes_are_exact docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py::test_t7_control_real_runtime_and_native_skill_assembly_paths_execute docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py::test_t7_control_real_knowledge_mcp_http_owner_path_executes docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py::test_t7_control_valid_alternate_and_compound_detectors_are_material -q
```

Exact output:

```text
....                                                                     [100%]
4 passed in 1.19s
```

## Pre-implementation RED

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py -q
```

Exact summary and exit:

```text
....FFFFFFFFFFFF                                                         [100%]
12 failed, 4 passed in 0.93s
exit 1
```

Ten cutover/migration nodes first fail with
`#315 T7 missing behavior: cannot import app.ia.cutover: No module named 'app.ia.cutover'`.
The two real delivery regressions fail independently: `search_memory` remains in the live MCP tool
registry, and neither injected skill owners nor all assembled runtime prompts contain the typed
cutover contract. Collection and all setup controls succeed.

## Compound mutants

- a Markdown file beside canonical JSON is rejected as dual truth;
- a patched source with stale Harness assembly blocks shadow migration;
- a forged zero-mismatch parity receipt with unequal normalized heads cannot trigger SQLite deletion;
- rewritten historical bytes plus an updated alias/hash cannot replace the frozen inventory row;
- SQLite/vector payloads cannot hide canonical query failure;
- an explicit legacy file reader cannot bypass the typed API in canonical mode;
- a rollback with the wrong expected generation preserves the canonical owner and emits no receipt.

The valid alternate reverses inventory order, adds safe metadata and wraps runtime prompts with
harmless layout text while preserving normalized ownership, heads and anchors.

## Frozen hashes

| Artifact | SHA-256 | Git blob before commit |
|---|---|---|
| `test_t7_prompt_document_cutover_behavior.py` | `2d5ea2f9a751a9489a95bc31f63cad1f0ce490cb8c9883224497ed2bfff1b2f0` | `e321c440b0c4d08a514616147d9eee984d754389` |
| `fixtures/t7_cutover_contract.json` | `404b1ad09d49d3f40c99ad196bcaccad220cadb0012239bc746580d0f4f72362` | `0439ef0677db9eb5b8e91db0421588b652b10699` |
| `fixtures/t7_cutover_records.json` | `b193804bd2466711c785dc12fca5f26b96833eebd3f8e472fa159307228850b0` | `09bc1bc5dd4eeb4ee2353b13d9ef1f1d4d9e1fa9` |
| `fixtures/t7_document_inventory.json` | `1f65c67eea34c615ef18d68e9c9fe2b9de68e8819b5dc2284022b9c67d52e51f` | `cb9165d05cd182a8bada1861054fa9d445cf86f4` |
