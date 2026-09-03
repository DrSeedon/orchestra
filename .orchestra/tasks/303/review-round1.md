# Sol adversarial review — round 1

Review job: `bg-5580a754fa`  
Route: fresh same-family Sol technical review; cross-family Opus unavailable because the measured Anthropic seven-day pool was 100% used.  
Completed verdict: **CHANGES REQUIRED**.

## Verbatim reviewer findings

- **blocking:** `research.md:113-122` — The recommended acceptance boundary does not actually prevent direct secret reads. Root/service ownership and “non-writable to the agent UID” enforce integrity, not confidentiality. The current `.env` is explicitly measured as `0644`; removing credentials from the worker environment does not stop project code from opening `/home/kesha/orchestra/.env`, configuration files, database files, or other world/group-readable service paths directly. “Protected `.env`” is asserted but no required unreadable mode, ACL, or inaccessible-path rule is specified. Require service secrets and sensitive configuration to be unreadable by the agent UID—verified with direct filesystem denial tests—not merely omitted from `environ`.
- **suggestion:** `research.md:89-102` — The execution-seam inventory omits agent-exposed `bg_create(type="ssh")`; classify it and express completeness as the invariant that every project-controlled child has the agent UID.
- **suggestion:** `research.md:120`, `recovery-runbook.md:14-21` — P3 is dependency-free and does not test a representative dependency/cache/native-build workload or existing-worktree ownership under the proposed UID. Keep compatibility LIKELY and require that probe before implementation approval.

The reviewer also stated: “The incident reconstruction is well supported: exact DB rows confirm repeated replacement of the live environment, `--frozen` did synchronize it, and the subsequent `httpcore`/filesystem failures follow the replacement.”

## Resolution before round 2

Accepted all three findings after source/filesystem verification:

1. Measured direct readability: service and worker `.env` mode 0644; incident DND worktree `.env` mode 0664. Added the current `app/workspace.py:26-29` source fact that `.env` is intentionally copied as a secret-bearing file.
2. Required service `.env`, sensitive config, DB/transcripts, and credential stores to be unreadable and unwritable by the agent UID; required direct-read `EACCES` checks; removed service `.env` copying from the accepted boundary.
3. Added local SSH launch to the seam inventory and the matrix, while explicitly excluding remote-host containment from the local UID claim.
4. Downgraded legitimate-project compatibility to LIKELY and made representative dependency-bearing `uv sync/run/test` under the proposed UID a pre-implementation check.

This first-round dissent is retained because #303 is an open architecture/security decision.
