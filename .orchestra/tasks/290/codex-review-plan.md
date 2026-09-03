## Summary

The plan has a strong safety direction, but Phase 2 should not pass its gate yet. The frozen suite currently collects correctly and produces the documented five RED assertion failures, but three acceptance tests are not valid behavioral oracles for their stated security/atomicity guarantees.

A confirming quotation from the reviewed plan: “Integrity hashes prove bytes, not authority.”

## Findings

### blocking: T4 can pass while the legacy prose summary remains the actual handoff

In [tests/test_runtime_handoff_v2.py:250](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/tests/test_runtime_handoff_v2.py:250), the test named `never_commits_from_summary_without_validation` configures `_build_runtime_handoff()` to return the legacy summary but never asserts that it was not called. It only requires two mocked validation methods to be called and the response mode to have a new label.

An implementation can therefore:

1. Build and commit `"legacy prose summary"`.
2. Call both mocks and ignore their results.
3. Return `mode="packet"`.

The test passes while the central missing behavior remains absent. Require `_build_runtime_handoff.assert_not_awaited()`, capture the staged input, and prove it is the canonical packet whose checksum was validated.

### blocking: T3 does not require valid receipts or make commit conditional on them

At [tests/test_runtime_handoff_v2.py:227](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/tests/test_runtime_handoff_v2.py:227), the test checks call order only. It does not establish the expected packet checksum, inspect canary arguments, compare the returned checksum, prove an empty tool surface, or exercise rejected ingress/capability receipts.

Production could await both functions, ignore `tools_enabled=True`, a wrong checksum, or `{"ok": False}`, then disconnect and commit. The oracle would remain green.

Add negative behavioral cases where:

- ingress returns the wrong checksum;
- ingress reports tools enabled;
- capability returns `ok=False` or a mismatched fingerprint.

Each must retain the source, avoid the atomic confirmation, and return a stable blocked result.

### blocking: T1’s authority assertion is vacuous and the raw-reference boundary is untested

The `all(...)` assertion at [tests/test_runtime_handoff_v2.py:148](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/tests/test_runtime_handoff_v2.py:148) passes when `constraints=[]`. Consequently, an implementation can discard every privileged constraint—including the genuine current system policy and tracked project document—and still satisfy the purported authority oracle.

The test also never calls `read_handoff_events`, despite its name and T1 AC covering cross-session, post-snapshot, unreferenced, hidden-reasoning, 32-ID, and 256,000-character enforcement. Nor does it test ledger idempotency.

Require the two expected privileged origins explicitly, prove the malicious transcript sentence remains only in an untrusted field, and exercise the scoped reader and duplicate idempotency key through their real public seams.

### blocking: Labelling raw transcript data “untrusted” does not prevent authority laundering after tools are restored

The plan labels raw-ref output untrusted at [plan.md:132](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/docs/tasks/290/plan.md:132), but after confirmation it restores the target’s normal executable tools at [plan.md:202](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/docs/tasks/290/plan.md:202).

There is no mechanical boundary preventing a malicious historical tool result such as “write this repository file” from being read through the raw-ref capability and then acted upon with normal tools. Provenance metadata informs the model but does not enforce authority. This violates the requirement that unprivileged transcript/raw data never create repository authority.

The plan needs a concrete enforcement rule at the action boundary—for example, raw-ref-derived content cannot authorize a privileged side effect without a fresh privileged/user instruction—and a behavioral adversarial test proving a planted raw instruction cannot cause a marker write.

### blocking: The proposed snapshot is not defined as an atomic snapshot of packet inputs

The ledger stores `snapshot_log_id`, packet bytes, and hashes, but the sequence merely says “freeze the DB snapshot” at [plan.md:194](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/docs/tasks/290/plan.md:194). It does not specify one SQLite transaction that:

- rejects outstanding asynchronous log writes;
- selects the maximum log ID for this session;
- reads exactly the rows through that ID;
- captures the relevant session metadata;
- inserts `prepared` with the resulting packet and hashes.

The current session layer writes logs asynchronously. A crash or a delayed log future between these operations can produce a packet whose declared range and effect classification omit an already-observed tool event. That can turn an ambiguous side effect into an apparently safe switch.

Specify a drained-write barrier followed by one database transaction/snapshot, and add a race test where a pending tool result/log write resolves during preparation.

### suggestion: “Every model-visible byte” is not concretely enumerable from the named construction seams

The preflight list at [plan.md:148](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/docs/tasks/290/plan.md:148) is directionally correct, but current backend construction adds runtime-specific material outside the plain session prompt: Codex project-document instructions and optional skill index, scope/user MCP discovery, Claude project inheritance, and Grok’s composed MCP set.

“Tracked project documents” and “target tool schemas” do not define how those dynamically discovered inputs are rendered and counted before target creation. A hand-maintained estimator can silently diverge from the actual backend factory.

Make preflight consume a single provider adapter-produced model-visible manifest derived from the same configuration object used to stage the target. Add component-isolation tests that overflow independently through project docs, discovered MCP schemas, injected skills, packet, and canary.

### suggestion: Fallback state does not retain both staged target identities

The ledger has only one `target_session_id`, while [plan.md:204](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/docs/tasks/290/plan.md:204) stages a fresh fallback target after a primary incompatibility. Overwriting the primary ID means recovery can clean only the most recently recorded target; crashing between fallback creation and ID persistence can orphan a provider session containing packet data.

Use an attempt table or persist both attempt identities and classifications before each external stage call. Recovery should enumerate and retire every created target attempt.

### suggestion: The frozen suite does not cover the plan’s transaction and recovery claims

The plan requires crash probes at every persisted phase, atomic session/ledger confirmation, exactly one fallback, failure classification, pending-effect rejection, and fail-closed recovery. None of these are present in the five frozen tests. The verification matrix promises them later, but the declared Phase 2 gate does not freeze them before implementation.

Because these are the highest-risk behaviors, their RED oracles should be committed before runtime work begins, especially:

- session updated without ledger confirmation and the inverse;
- crash before/after every phase transition;
- transport/auth error does not spend fallback;
- second incompatibility cannot stage a third target;
- pending or ambiguous effect blocks before target creation.

## Verdict

**REQUEST CHANGES — Phase 2 gate fails.**

The five tests genuinely collect and are currently RED, so the evidence statement is accurate. However, T1, T3, and T4 can go green without enforcing their stated security behavior, and the plan lacks a mechanical authority boundary for raw-ref data plus a sufficiently specified atomic snapshot. Runtime implementation should not start until these blocking issues and frozen RED oracles are corrected.

## Review attempt log

- Attempt 1: completed; verdict `REQUEST CHANGES` with five blocking and three suggestions.
- Attempt 2: started after plan and RED-oracle revision.

## Round (2026-08-16T11:02:43Z)

## Round 2

## Summary

Re-review status: **not approved**.

The frozen command matches the stated evidence: 34 assertion failures, with no collection, import, fixture, or setup errors. `git diff` for the permitted files is empty, so the reviewed revision is already committed rather than an uncommitted diff.

Most first-round design issues are fixed, but two frozen oracles still do not test what the revised plan claims, and preparation has a direct pending-effect contract contradiction.

## Findings

### Prior findings

1. **T4 could commit legacy prose — FIXED.**
   T4 now asserts `_build_runtime_handoff.assert_not_awaited()` and verifies that ingress receives the canonical packet and checksum.

2. **T3 ignored invalid receipts — FIXED.**
   Negative cases now cover wrong checksum, `tools_enabled=true`, and failed capability, retaining the source and skipping confirmation.

3. **T1 authority assertion was vacuous — FIXED.**
   The test explicitly requires both privileged origins, a non-empty untrusted recent delta, and the forged `SYSTEM` sentence only in that untrusted delta.

4. **Raw-ref authority laundering — FIXED in the plan.**
   Raw refs are operator-only and absent from MCP/runtime tool catalogs; free-form tool bodies do not enter the model-visible packet.

5. **Snapshot atomicity undefined — FIXED.**
   The plan now specifies draining persistence/log writes and preparing from one SQLite transaction. The race oracle injects a delayed result before preparation.

6. **Total-context inputs not derived from staging configuration — STILL BROKEN in the frozen oracle.**
   The plan now correctly mandates one immutable `ModelVisibleManifest`, but [tests/test_runtime_handoff_v2.py:320](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/tests/test_runtime_handoff_v2.py:320) passes an ordinary dict directly to preflight. It never proves that staging receives the same object/configuration hash or that the factory cannot rediscover inputs. It also omits separately named manifest components such as the developer prompt, runtime-generated project-doc instruction, and validation profile. This is a real coverage gap, though not independently blocking if adapter-specific behavioral tests are frozen before implementation.

7. **Fallback lost the primary target locator — FIXED.**
   The two-row attempt ledger retains both deterministic cleanup locators and rejects attempt 3.

8. **Transaction/recovery/fallback behavior absent from frozen RED — FIXED substantially.**
   Atomic rollback, phase decisions, structured classification, bounded fallback, pending effects, and fallback exhaustion now have RED cases.

### New findings

#### blocking: Pending-effect handling has two incompatible contracts

The plan says preparation’s transaction “aborts if an outstanding/pending effect exists” at [plan.md:123](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/docs/tasks/290/plan.md:123). But the coordinator sequence prepares first and separately rejects pending effects at [plan.md:263](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/docs/tasks/290/plan.md:263). The frozen test likewise mocks successful preparation returning `pending_effects=1` and expects the coordinator to reject it.

Both cannot be implemented. If preparation aborts, no prepared ledger/result exists for the test’s path; if it returns a prepared record, the stated atomic preparation contract is false.

Choose one fail-closed owner. Prefer having atomic preparation persist a terminal blocked/failure result or return a typed `handoff_pending_effect` without creating a live `prepared` operation, then freeze the corresponding behavioral oracle.

#### blocking: The raw-ref security oracle does not test the operator-only route boundary

The revised plan’s safety depends on the HTTP route rejecting inherited internal bearer/MCP access and requiring dashboard cookie plus CSRF. However, [tests/test_runtime_handoff_v2.py:176](/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-runtime-switch/tests/test_runtime_handoff_v2.py:176) calls the resolver directly with a caller session ID. It does not invoke the route, attempt internal-token authentication, verify CSRF, or inspect the runtime/MCP tool catalog.

Thus the frozen test can pass while the route accidentally accepts the internal bearer token—the exact condition that would expose raw transcript data to target runtimes. Add route-level RED cases for:

- internal bearer rejected;
- cookie without CSRF rejected;
- authenticated operator cookie plus CSRF accepted;
- capability absent from MCP and normal runtime tool fingerprints.

#### blocking: The planted-marker T4 oracle does not derive its packet from the planted tool result

The plan claims T1/T4 plant a marker instruction “only in a tool result” and prove it is absent from the exact staging manifest. But T4 manually supplies a packet that never contained `WRITE_MARKER_FROM_RAW`, then asserts the string is absent from that same packet. No planted tool result enters the setup, and no `ModelVisibleManifest` is inspected.

This check cannot fail if packet construction or manifest assembly leaks free-form tool bodies. Build the prepared packet from rows containing the marker, build the adapter manifest through its real seam, and assert the marker is absent from that exact object passed to staging. The isolated negative/positive marker canary should consume that manifest.

#### suggestion: Secret redaction should include visible user/assistant messages explicitly

The plan excludes free-form tool bodies but deliberately transfers recent user/assistant text. The frozen secret probe exists only in a tool result. Add probes for bearer tokens/private keys in user and assistant messages and require the shared sanitizer to redact them before packet hashing and staging. Otherwise secrets pasted into conversation can cross provider boundaries despite tool-body protection.

## Verdict

**REQUEST CHANGES.**

The revised architecture is much stronger, and six of eight prior concerns are resolved. Before implementation starts, fix the pending-effect contract and freeze route-level raw-ref authorization plus a non-vacuous marker-to-manifest oracle.

## Review attempt log — update

- Attempt 2: completed; verdict `REQUEST CHANGES` with three blocking and two coverage suggestions.
- Attempt 3: started after the final plan and RED-oracle revision.

## Round (2026-08-16T11:10:17Z)

## Round 3

## Summary

Re-review status: **APPROVED**.

The permitted-file `git diff` is empty, so there is no current uncommitted diff; the reviewed revision is already committed. The frozen suite matches its evidence: **39 assertion failures**, with no collection, import, fixture, or setup errors. Missing runtime functions are legitimate Phase 2 RED behavior.

Verbatim confirmation from the revised plan: “Awaiting a check is not validation.”

## Findings

- **Pending-effect ownership — FIXED.** Atomic preparation now returns a typed ineligible result with `handoff_id=None` and creates no live operation. The coordinator oracle uses this exact contract.

- **Raw-ref route security — FIXED.** The route-level RED covers absence from MCP, rejection of inherited bearer access, CSRF enforcement, and successful cookie-plus-CSRF operator access.

- **T4 marker oracle — FIXED.** It builds the packet from actual rows containing the marker only in `tool_result`, invokes `GrokBackend.build_handoff_manifest()`, and checks the resulting manifest components.

- **User/assistant secret leakage — FIXED.** Bearer and PEM/private-key probes are placed in model-visible transcript rows and must be absent from the canonical serialized packet.

- **Exact manifest/preflight/staging identity — FIXED.** Ten named components have independent overflow cases, and `stage_preflighted_handoff` must pass the identical manifest object and configuration hash to the adapter.

No new blocking contradiction was found in the permitted files. The revised plan consistently covers atomic preparation and confirmation, bounded attempts with recoverable cleanup locators, mechanically isolated ingress validation, structured fallback classification, fail-closed recovery, context accounting, and authority separation.

## Verdict

**APPROVED — Phase 2 plan and frozen RED gate are valid. Runtime implementation may begin under the stated gate.**
