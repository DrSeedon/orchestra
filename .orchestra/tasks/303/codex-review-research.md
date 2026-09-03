## Summary

The incident reconstruction is well supported: exact DB rows confirm repeated replacement of the live environment, `--frozen` did synchronize it, and the subsequent `httpcore`/filesystem failures follow the replacement. The probe output matches the structured evidence.

Verbatim from `research.md`:

> “A dedicated UID is not magic.”

The review found one blocking security gap and two suggestions.

## Findings

- **blocking:** `research.md:113-122` — The recommended acceptance boundary does not actually prevent direct secret reads. Root/service ownership and “non-writable to the agent UID” enforce integrity, not confidentiality. The current `.env` is explicitly measured as `0644`; removing credentials from the worker environment does not stop project code from opening `/home/kesha/orchestra/.env`, configuration files, database files, or other world/group-readable service paths directly. “Protected `.env`” is asserted but no required unreadable mode, ACL, or inaccessible-path rule is specified. Require service secrets and sensitive configuration to be unreadable by the agent UID—verified with direct filesystem denial tests—not merely omitted from `environ`.

- **suggestion:** `research.md:89-102` — The execution-seam inventory claims completeness for inspected repository seams but omits the agent-exposed `bg_create(type="ssh")` launcher visible in the cited `app/mcp_stdio.py:1986-2033`. Even if its remote command cannot normally mutate the local runtime, the local SSH process and configuration form another project-controlled external-process seam and should be classified explicitly. Phrase completeness as a tested invariant—every project-controlled child has the agent UID—rather than relying on the enumerated list.

- **suggestion:** `research.md:120`, `recovery-runbook.md:14-21` — Compatibility evidence is narrower than the conclusion. P3 proves a dependency-free project can create a local `.venv`; it does not yet demonstrate a realistic project with dependencies, writable uv cache/home, native build subprocesses, or existing worktrees owned by `kesha`. Keep compatibility at `LIKELY` and require a representative per-project `uv sync/run/test` probe under the proposed UID before implementation approval.

## Verdict

**CHANGES REQUIRED — review completed.**

The causal chain, `--frozen` semantics, deleted mappings, `httpcore` and certifi consequences, direct/inline/symlink/uv/sudo bypass analysis, and drain/handoff recovery model are credible. Phase 1 should not be accepted as a complete boundary until direct filesystem confidentiality is made explicit and enforceable.

## Round (2026-08-16T15:18:02Z)

## Summary

All three round-1 findings are substantively resolved:

- Direct filesystem confidentiality now has explicit read/write denial and `EACCES` acceptance checks.
- The local SSH execution seam is classified separately from remote authority.
- Per-project `uv` compatibility is correctly downgraded to `LIKELY` pending a representative UID-based probe.

New verbatim line:

> “Existing worktree `.env` copying is direct counter-evidence to the first draft's confidentiality claim.”

## Findings

- **blocking:** `research.md:113,122` and `recovery-runbook.md:22` require all “credential stores” to be unreadable by the agent UID. Taken literally, this includes the Codex, Claude, and Grok authentication stores their CLIs must read after being launched as that UID. The acceptance check would therefore either break worker authentication or fail once those stores are made readable. Distinguish service credentials—which must return `EACCES`—from dedicated-agent provider authentication stores, which must be readable only by that agent UID and excluded from project-controlled subprocesses where technically possible. Add a startup/authentication check under the proposed UID.

No other new blocking defect was found.

## Verdict

**CHANGES REQUIRED — round-2 review completed.**

The round-1 objections are resolved, but the credential-store rule must distinguish service secrets from credentials required by the worker runtimes before the package is approved.
