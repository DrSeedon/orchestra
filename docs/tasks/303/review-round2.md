# Sol adversarial review — round 2

Review job: `bg-cacb6bf6ff` (resumed session `01a00b20`)  
Completed verdict: **CHANGES REQUIRED**. This was the second and final prose-review round permitted by the canonical review ceiling.

## Verbatim reviewer result

The reviewer confirmed: “All three round-1 findings are substantively resolved.” It then raised one new blocker:

- **blocking:** `research.md:113,122` and `recovery-runbook.md:22` require all “credential stores” to be unreadable by the agent UID. Taken literally, this includes the Codex, Claude, and Grok authentication stores their CLIs must read after being launched as that UID. The acceptance check would therefore either break worker authentication or fail once those stores are made readable. Distinguish service credentials—which must return `EACCES`—from dedicated-agent provider authentication stores, which must be readable only by that agent UID and excluded from project-controlled subprocesses where technically possible. Add a startup/authentication check under the proposed UID.

No other new blocking defect was found.

## Author resolution after the round ceiling

Accepted the incompatibility but strengthened the resolution beyond “where technically possible”: arbitrary project code running under the same UID can read any mode-0600 provider store that the CLI reads. Current Codex and Claude provider stores are both mode 0600 owned by UID 1001; Codex per-session homes symlink the shared authentication file, while Codex runs `danger-full-access`. Therefore one agent UID is sufficient for service-runtime integrity but **not** provider-credential confidentiality.

The final research now requires three authority domains: service; credential-bearing controller/broker; and uncredentialed project execution. Provider startup/authentication must succeed in the controller domain, while every project-selected file/process/network operation must execute in a sandbox/UID where direct reads of both service and provider credentials return `EACCES`. A backend that cannot demonstrate that split must broker provider authentication outside the project-exposed CLI or remain outside the claimed confidentiality boundary.

This resolution was not sent for a third model round because prose review has an unconditional two-round ceiling. It is escalated to the orchestrator as an explicitly unconfirmed blocking-resolution decision.
