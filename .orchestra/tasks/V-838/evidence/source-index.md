# Official plugin source evidence

Inspection snapshot: `anthropics/claude-plugins-official`, `main` at commit
[`8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3`](https://github.com/anthropics/claude-plugins-official/commit/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3), checked 2026-10-14. The plugin manifest at this revision says `version: 1.0.0`. The project license is Apache-2.0. These immutable links identify the reviewed source; this folder preserves the source map and decisive line references, not a vendored copy of the plugin.

## Files and what they establish

| Source | Evidence used |
|---|---|
| [`plugin.json`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/.claude-plugin/plugin.json#L1-L63) | Version 1.0.0, author, user-configurable tracks and optional pane/telemetry. |
| [`LICENSE`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/LICENSE) | Apache License 2.0. |
| [`README.md`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/README.md) | Workflow, source/target directory boundary, human decision points, proof contract, capabilities and limitations. |
| [`commands/modernize-verify.md`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/commands/modernize-verify.md#L7-L138) | Independent re-check instructions, clean test run, canary, generated fresh inputs, handoff back to a person. |
| [`scripts/proof_pack.py`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/scripts/proof_pack.py#L6-L49) | Script-derived verdict definitions, evidence inputs and exit codes. |
| [`scripts/compare.py`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/scripts/compare.py#L1-L43) | Same-output comparison, explicit masks/tolerances, missing/different cases fail, approved differences remain visible. |
| [`scripts/compare.py` self-check](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/scripts/compare.py#L338-L427) | Mutates one output byte to test the comparator itself; computes comparison result. |
| [`agents/business-rules-extractor.md`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/agents/business-rules-extractor.md#L27-L75) | Given/When/Then rule extraction with file/line citation, confidence, secret and untrusted-content handling, read-only role. |
| [`agents/test-engineer.md`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/agents/test-engineer.md#L7-L43) | Characterization oracle, rule-linked tests, edge cases, two-implementation comparison and code-breaking mutation. |
| [`commands/modernize-extract-rules.md`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/commands/modernize-extract-rules.md#L15-L68) and [`workflows/extract-rules.js`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/workflows/extract-rules.js) | Sharding, agent fan-out, referee and P0 adjudication design; command documents the substantial agent/token cost. |
| [`commands/modernize-brief.md`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/commands/modernize-brief.md) | Explicit approval before build phases. |
| [`hooks/hooks.json`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/hooks/hooks.json) and [`hooks/README.md`](https://github.com/anthropics/claude-plugins-official/blob/8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3/plugins/code-modernization/hooks/README.md) | Optional pane and telemetry hooks; pane is off without an early-access Claude Code feature flag. |

## Important source details

The README calls out six human decision points: preflight questions, disputed rules, brief approval, proof differences, proof sign-off, and applying a security patch. `modernize-verify` explicitly treats a PROVEN result as evidence, not approval; the named owner still signs. The proof pack computes verdicts from result artifacts and lists limitations; it does not ask a model to assign the final label.

The comparison helper is deterministic byte comparison after explicitly declared masks and narrow, justified numeric tolerances. A person-approved difference is preserved in the output as approved, not erased. Its self-check flips output bytes to confirm the comparator can detect differences. Separately, the verify command asks an agent to alter one behavior-bearing source line and retain runner evidence showing tests fail. These are distinct checks: testing the comparator, and testing whether product tests detect a code mutation.

The plugin README says the legacy source is linked/read-only by convention and writes generated code into `modernized/`; it also admits build output can be written wherever the project's own build normally writes. Recommended permission rules are a separate safety layer, and shell commands/scripts are not fully fenced by file-tool rules. Thus “does not touch source” is a workflow goal, not an OS-enforced sandbox guarantee.

No claim is made here that Orchestra can install or execute these Claude Code plugin commands. The inventory shows a Claude Code plugin package: slash-command markdown, specialist agents, Python/JavaScript scripts, workflow definitions, and optional TypeScript pane hooks; the inspected tree has no MCP server declaration.
