# Task #303 — Phase 2 plan

## Gate status and scope

Phase 1 is accepted for planning with one explicit unresolved security gate. The final Sol research artifact is **not APPROVED**: round 2 ended `CHANGES REQUIRED`, and the post-ceiling three-domain correction has not received a model verdict. This plan preserves that distinction.

The implementation is four vertical releases. Six reviewed Phase 2 freezes are **rejected evidence**, not acceptance baselines: `ff6aacb7ee6a05ed1cdc07588e80ef8cecddd69b` with `red-release-*-v3.txt`/`codex-review-plan.md`; `622e740e2cd934d7bfe6fac40ab894afef27ac9c` with `red-release-*-v4.txt`/`codex-review-plan-corrected.md`; v5 `8fe615b9cc89b0f94a8cce9e1d7d8d9f659b2e4e` with `red-release-*-v5.txt`/`docs/reviews/303/enforcement-oracle-audit.md`; v6 `1ec850dbf5b69a35bdcd6422eca1001f5a3576f8` with `red-release-*-v6.txt`/`enforcement-oracle-audit-v6.md`; v7 `c83f4437e73432e6b3752014b7786126e59b48a2` with `red-release-*-v7.txt`; and v8 `9c80ec07d30e918e8f9a8d79c4be8bc984afeafe` with `red-release-*-v8.txt`. V7 and V8 share the first two rounds of appended `enforcement-oracle-audit-v7.md`; both rounds ended `CHANGES REQUIRED`. The v6 background job was additionally marked blind/failed even though it emitted the preserved findings. Earlier freezes `ff6a8c03`, `213b5339`, `1745b9a7`, `f02b9905`, and `0dbb9a59` remain superseded and excluded forever.

V9 (`6045144a5fc207b276048b622f5f63f04dff26eb`) received an exact `APPROVED` enforcement-oracle verdict and remains preserved evidence that its authority seams are sound. It is nevertheless **permanently superseded for implementation acceptance**: its ticket commands combined ordinary source/package work with root-owned installed state, PID 1, `/opt`, `/var/lib`, and `/etc/systemd/system` evidence, while the authorized implementation phase forbids those mutations. V10 split delivery from activation and received an exact `APPROVED` review, but its reference-runtime inventory rejects the normal Python 3.12 virtual-environment directory alias `lib64 -> lib`. V11 fixed that representation and received exact `APPROVED`, but two honest fresh runtimes then exposed a second unsatisfiable premise: 38 files differed only because their scratch virtual-environment prefixes differed. V11 is therefore superseded for implementation evidence, not rejected as security design. V12 preserves every V9–V11 byte and normalizes only independently classified prefix-bearing artifacts to a fixed versioned final path, with independent `RECORD` recomputation. No earlier green result may satisfy V12.

This Phase 2 turn changes only task-local plan/oracle evidence. It does not mutate runtime, systemd, provider authentication, Unix accounts, secrets, or live processes. V12's fresh targeted Sol audit recorded below ends exactly `APPROVED`; every privileged activation gate remains mandatory RED/pending regardless of delivery verdict.

PROJECT CONTEXT for review: personal multi-project Orchestra on one VPS; Python/FastAPI/systemd; many concurrent agents/worktrees. Correctness, security, and runtime continuity matter. Enterprise ceremony and 100% coverage do not. Blocking means service-environment corruption, a bypass, agent loss, or secret exposure.

## Release claims — keep them separate

| Release | It may claim | It must not claim |
|---|---|---|
| A — emergency recovery | A root-owned, commit-pinned application/runtime/control-plane package can replace the corrupted on-disk environment without overwriting it, and activation/rollback use the existing authorized drain/handoff path | General project-code isolation or provider-secret protection; B and C remain required |
| B — project execution identity | Arbitrary project code cannot write service-owned runtime/state through the enumerated local seams | Provider-login secrecy; until C, a model CLI and its tools still share delegated provider credentials |
| C — credential controller/broker | Provider authentication is usable by the controller and unreadable to every model-selected project operation | Success for a provider that did not pass startup + authenticated turn + refresh + adversarial EACCES probes |
| D — scoped environment and guards | Workers/MCP receive scoped allowlists, service `.env` is not copied, the global internal token is absent, and dangerous configured targets are rejected/audited | That a string/path guard stops inline env, direct `uv venv`, symlink aliases, or another program; B is the enforcement |

Release order is A → B → C → D. Each activation is a separate operator decision after its implementation and rehearsal evidence. A is the only recovery release; B–D must never be smuggled into an emergency runtime repair.

## V12 two-lane acceptance state machine

Each release has two independent gates:

1. **Delivery/package/source gate — unprivileged.** `v12_delivery_gate.py <release>` runs only the frozen source node ids, derives the install prefix itself as `/opt/orchestra/runtimes/<full-source-commit>-<release-a-d>-py312`, and passes that value—but never the oracle's private reference path—to the fixed public builder CLI. Application, control-plane, unit, link, source-content, owner-only storage, pending-only report, `O_NOFOLLOW` snapshot, TOCTOU, and exact candidate/reference rules remain byte-for-byte inherited from V10/V11. Runtime comparison changes in one place: the independent reference normalizer recognizes exactly five named activation-template assignments plus executable `runtime/bin/*` files whose first line is exactly `#!<private-reference>/bin/python`; any other occurrence of the private prefix fails. It replaces only those fields with the derived final prefix, independently recomputes hash and size only in `.dist-info/RECORD` files that own changed console scripts, and requires every changed script to have exactly one owning row. Candidate archive bytes are never normalized by the oracle: they must already equal the independently normalized reference, including final-prefix shebangs and recomputed `RECORD`, and manifest schema v2 must repeat the independently derived prefix. A builder/manifest pair that agrees on another prefix still fails exact equality. Absolute, escaping, dangling, cyclic/chained, special-device, protected-state, extra, explicit-directory, install-prefix-mismatched, and candidate/reference-mismatched entries fail closed. The runner strips service/provider secrets from child environments and snapshots authoritative host paths before and after. A successful run retains exactly `delivery_ready=true`, `activation_ready=false`, `privileged_evidence="pending"`, `activation_authorized=false`, `isolation_claimed=false`, `activation_receipt=null`, `protected_secret_comparison="pending_privileged_activation"`, and `production_state_unchanged=true`. It does not authorize installation or claim live isolation.
2. **Release/activation gate — privileged and deferred.** The exact V9 installed-state tests remain frozen under separate commands. They read the real root-owned selection, installed control plane and unit files, derive the actual `ExecStart`, query PID 1 using `systemctl show`, verify live PID/starttime/runtime binding, and require the signed, atomic one-use rehearsal evidence. These commands must remain RED/pending during the implementation-only phase. They may not be skipped, xfailed, replaced with fixture JSON, redirected to a temporary fake `/opt`/`/var/lib`, or reported green. Only a separately authorized operator window may create their evidence and run them against the installed host.

The state transition is one-way and fail-closed:

```text
source RED ──implement──> delivery GREEN + pending-only report
                                  │
                                  └── no activation authority; no isolation claim
                                      operator install/rehearsal authorization required
                                                        │
                                                        v
                                     privileged activation gate GREEN
                                                        │
                                                        v
                                               release may activate
```

Delivery GREEN alone can neither authorize nor advertise an active boundary. Release A continues to mean recovery integrity only. B/C isolation claims begin only after their own privileged activation gate is green on the installed host. D remains defence in depth.

## Measured emergency baseline already active (recovery, not prevention)

Read-only measurements on 2026-08-16 are frozen in `emergency-baseline-v6.json`. The running unit uses `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m uvicorn app.main:app --fd 3`; both `/opt/orchestra/runtimes` and the selected runtime are root-owned and non-writable, the selected runtime is additionally exposed read-only by systemd, `UnsetEnvironment=VIRTUAL_ENV UV_PROJECT_ENVIRONMENT` is loaded, `/proc/<MainPID>/environ` contains neither variable, and `NoNewPrivileges=yes` is effective. This is the already-applied emergency recovery layer. It removes `uv run` from service startup and prevents project code from overwriting that versioned runtime.

It is not the final boundary: `orchestra.service` still runs as `kesha`, its working directory remains the writable checkout, and arbitrary-code children still originate in that controller authority domain. Therefore A starts from this stable direct-runtime baseline and adds only reproducible package selection, drain/handoff, admission, and rollback. Permanent prevention is B+C: a non-project controller identity, an unprivileged executor identity across every arbitrary-code seam, and a credential controller/broker whose stores are unreadable to the executor. D's prompt rules, env stripping, path guards, and audit events are defence in depth and cannot satisfy the prevention claim by themselves.

## Triage: restore merge/MCP before the full credential architecture

Release A is the smallest safe way to restore the current supervisor and fresh MCP processes:

1. From a clean checkout of an exact commit, build a manifest-bearing application/runtime/control-plane package as an unprivileged user; do not touch `/home/kesha/orchestra/.venv` and do not execute the package as root from the checkout.
2. The operator copies the package bytes first into root-owned staging using only trusted system tools, verifies the independently supplied package digest and commit, rejects links/special files/path traversal, then installs the verified application source, Python 3.12 runtime, probes, hooks, and control helpers into immutable versioned roots. Verification runs only the installed copy and checks imports and CA bundle from its staged interpreter.
3. Install two root-owned, hash-pinned one-shot systemd templates: `orchestra-runtime-recovery@.service` enters only the installed manager's public `activate` operation for A, and `orchestra-boundary-activate@.service` enters only its public `authorize-commit` operation for B–D. Installation never activates either unit. After a separate operator authorization, `systemctl start --wait <unit>@<activation-id>.service` is the only production authority entry; there is no app route, shell wrapper, `systemd-run` argv generator, or checkout callback that can apply selector/admission/process state. The unit survives old/new supervisor death, records the exact old state, and uses the existing application path for the 900-second active-turn wait and Codex FD handoff.
4. A supervisor booting for a pending activation starts with ordinary HTTP/turn/mutation admission closed. Only the activation probe/commit endpoints are reachable. The external owner verifies the selected `/proc/<pid>/exe`, source/lock/unit hashes, import/SSL postchecks, and health; it durably commits those observations before it tells the new process to open admission. Thus a failed staged process can listen only behind the closed activation gate, never briefly accept agent work.
5. Do not kill surviving Codex CLIs. Their old MCP children are stale; the existing `tools_are_stale` path replaces them at the next turn boundary. Keep the old runtime until `/proc` has zero references.
6. On any failure before commit—including an ambiguous timeout after the restart request—the external unit stays alive after the old supervisor exits. If the old PID is still present it invokes the activation abort path and reopens the rolled-back handoff; otherwise it stops the target unit to break the restart loop, restores the exact selector and active-state bytes, and starts the positively checked old runtime. The append-only attempt record remains for audit. Never rebuild either runtime in place.

This restores merge/MCP continuity but leaves the same-UID authority defect open and visibly reported. Release B is the prevention boundary. C and D are not prerequisites for emergency recovery.

## Architecture and files

### Release A — side-by-side Python 3.12 recovery

Files:

- `scripts/build-orchestra-runtime-package.py` (new): unprivileged, deterministic package builder for an exact Git commit; never a root execution entry point.
- `scripts/manage_orchestra_runtime.py` (new): the single public, stdlib-only control-plane executable for `stage`, `verify`, `activate`, `authorize-commit`, `status`, and `rollback`. Root-owned one-shot systemd templates execute this installed path directly; there is no second test-facing activation adapter.
- `scripts/rehearse-runtime-recovery.py`, `scripts/runtime-activation-probe.py`, `scripts/runtime-activation-hook.py`, `scripts/attestation-policy.py`, `scripts/attest-boundary-rehearsal.py` (new): control-plane artifacts copied and hash-pinned in the same package; no installed artifact imports the worktree.
- `app/runtime_activation.py` (new), `app/main.py`, `app/manager.py`: pending-activation middleware/state and adopt-only resume; ordinary routes/background consumers remain closed until the external owner commits verified postchecks.
- `app/routes/system.py`: activation-id status/abort/probe/commit contract around the existing drained restart; it does not replace the drain or handoff implementation.
- `deploy/orchestra.service` plus its packaged drop-in: preserve the measured direct `/opt/orchestra/runtimes/<release>/bin/python -m uvicorn app.main:app --fd 3`, `UnsetEnvironment=VIRTUAL_ENV UV_PROJECT_ENVIRONMENT`, `NoNewPrivileges=yes`, `ReadOnlyPaths=/opt/orchestra/runtimes`, socket/FD-store/KillMode settings, and parameterize the selected version without reintroducing `uv run`.
- `deploy/orchestra-runtime-recovery@.service`, `deploy/orchestra-boundary-activate@.service` (new): root-owned one-shot authority entrypoints. Each has exactly one shell-free `ExecStart` into the installed hash-pinned manager, no other `Exec*` directive, no environment file, and no alternate apply path.
- `deploy/orchestra-authority-surface.json` (new): fixed manifest of the sole authority owner, the non-authority package builder, the two unit callers, the installer, and the complete scanned production source roots (`app`, `scripts`, `deploy`). It is an inventory input, not self-attestation: the frozen oracle independently walks every shipped Python/script/deploy file and rejects files absent from the scan. The package builder may name the two unit files as archive entries but may not import/call either authority operation.
- `deploy/orchestra.service.template`: parameterized runtime and application-source roots; no `.venv` or `ExecStartPre=uv sync`; same socket activation, FD store, `NotifyAccess`, and `KillMode=process` contract as the live unit. The live `/home/kesha` layout is not copied into new installs.
- `deploy/install.sh`: exact, byte-for-byte frozen non-root wrapper around `/usr/bin/python3 scripts/build-orchestra-runtime-package.py`. It calls absolute `/usr/bin/id`, exits 77 before any other action when EUID is 0, contains no remote/root/install/systemd operation, and cannot grow extra shell logic without failing the frozen equality oracle. This intentionally retires the legacy remote root installer; root bootstrap consists only of the recovery runbook's documented absolute `/usr/bin/install`, digest verification, extraction, unit installation, `systemctl daemon-reload`, and the installed root-only manager's `stage`/`verify` operations. First activation is always a separate operator action.
- `docs/tasks/303/recovery-runbook.md`: replace proposed placeholders with the exact shipped commands only after implementation.

Package and installed-control-plane contract:

- The package contains the exact application source tree, `uv.lock`/`pyproject.toml`, built Python runtime, unit files, and every root wrapper/probe/hook/rehearsal/policy artifact. Its canonical manifest records the exact source commit, package digest, relative path, type, mode, and SHA-256 for every entry. It also records `provider_credential_store_included=false` as a result derived from the typed member inventory and `protected_secret_comparison="pending_privileged_activation"`; it must not turn the latter into `complete`. Before any selector/admission/process mutation, the installed privileged verifier compares candidate regular-file bytes with the non-empty protected service/provider values it alone can read and rejects a match. The independently supplied expected commit and package digest are operator inputs, never values learned from the checkout being protected.
- Root never executes a checkout script to bootstrap trust. It opens the candidate archive with `O_NOFOLLOW`, copies from that open descriptor into a root-owned `.new` file, fsyncs it, verifies the copied digest against the operator input, and extracts only regular files/directories into a root-owned `.new` directory. Symlinks, hard links, devices, FIFOs, absolute paths, `..`, duplicate paths, and manifest mismatches fail before any package byte executes. The final digest is over the copied descriptor/tree, so replacing the source path after open cannot substitute executed bytes.
- The installed manager exposes the same production primitives to the oracle: `open_verified_package(path, *, expected_sha256) -> int` returns an `O_NOFOLLOW` descriptor after hashing that descriptor, and `copy_open_package(fd, destination, *, expected_sha256)` rewinds/copies/fsyncs/hashes the same descriptor and removes the destination on mismatch. The test opens a good file, atomically replaces its pathname with hostile bytes, and proves the copied bytes still come from the opened inode; a symlink open and wrong second digest both raise.
- The verified control plane is atomically installed at `/usr/libexec/orchestra-runtime/control-planes/<source-commit>/`; every manager/probe/hook/policy/attestor artifact is root-owned mode `0500`, so application and project UIDs cannot read, import, or execute a missed alternate spelling even if the static inventory were incomplete. Versioned runtimes stay under the already deployed `/opt/orchestra/runtimes/<release>/`, and packaged application source is root-owned beside its selected runtime. All ancestors are root-owned and non-group/world-writable. `/var/lib/orchestra-runtime/control-plane-selected.json` is a root-only regular file binding the package digest, commit, application/runtime tree digests, selected target, every executable role/path/hash, and the fixed paths and hashes of both installed activation units. It does **not** carry a declarative public argv as acceptance evidence. Selectors may change only through the manager reached by those units; versioned targets are immutable.
- The A and B oracles independently open the actual fixed installed unit paths, verify root ownership/non-writability, source commit, and selection hash, require `Type=oneshot`, `User=root`, exactly one shell-free `ExecStart`, no other executable directive, and no root/image/bind/mount remapping, then derive the manager argv from that line. They query PID 1 with `systemctl show` for a fixed probe instance and require `LoadState=loaded`, the exact fragment path, no effective drop-ins, and an effective `ExecStart` equal to the derived argv after `%i` expansion. The only allowed forms are `<installed-manager> activate --state-root /var/lib/orchestra-runtime --activation-id %i` for recovery and `<installed-manager> authorize-commit --state-root /var/lib/orchestra-runtime --activation-id %i` for boundary activation. The parser rejects `/bin/true`, another operation, another `Exec*`, environment injection, non-root execution, filesystem remapping, a cached/different fragment, or any instance/template drop-in. Thus a correct manager binary or stale declarative command cannot pass while the real loaded unit invokes a bypass.
- A manifest-wide authority-surface oracle independently scans every shipped `app/**/*.py` plus every file under `scripts/` and `deploy/`. Only `scripts/manage_orchestra_runtime.py` may own the root-state operations and only the two fixed unit templates may call them. Python imports/strings that expose the manager, either unit, `/var/lib/orchestra-runtime`, `activate`, or `authorize-commit` outside that allowlist fail. The legacy shell installer is not parsed or denylisted: its entire source must equal the frozen root-refusing package-builder wrapper. Appending direct commands, `unit=...; systemctl start`, `"$manager" activate`, or the audit's constructed `sys`+`temctl`/`sta`+`rt` form changes the bytes and fails before lexical interpretation. An alternate application import/route also fails the whole-corpus scan. Exact root-only mode `0500` on the installed control plane and root-only state are the runtime backstop: the static inventory is delivery evidence for trusted shipped wiring, not a claim that text matching confines hostile project code.
- The A oracle executes the argv derived from the installed recovery unit, retargeting only `--state-root` and `%i` to a temporary instance of the production state schema. After the manager itself has verified the copied selected manager/probe/hook set, it publishes a test-only filesystem barrier below the public command and before execution. The oracle then physically attacks each path by atomic rename, symlink replacement, or same-inode/same-size modification and releases the manager. The manager must reopen with `O_NOFOLLOW`, recompute identity, execute only the matching open descriptors, and mutate the parameterized production selector (`current`), `deploy-state/active.json`, `activation-state/admission.json`, and `activation-state/process.json` only after all three executions. All nine mismatch arms return `artifact_identity_changed:<role>`, run no hostile payload, and leave those authority paths byte-for-byte unchanged. The no-swap control executes all three exact verified identities and applies once. No oracle callback owns verification, execution, commit, or state mutation; no rehearsal JSON field is acceptance evidence.

Installed public-manager contract:

- `manage_orchestra_runtime.py activate --state-root PATH --activation-id ID` is the exact production operation named by the installed recovery unit and executed by the frozen Gate 1 oracle; production passes `/var/lib/orchestra-runtime`/`%i` and the oracle substitutes only a temporary root/id after deriving the base argv from that unit. There is no scratch implementation or alternate state schema. `--oracle-sync-dir` only pauses the same operation after complete identity verification and before descriptor execution. The command reports the device/inode/size/mode/SHA-256 identities it both verified and executed. Replacing the public command's shared descriptor-pinned implementation with path reopen or a no-op makes the control/attack/state assertions fail.
- Manager, probe, and hook implement `--task303-identity-probe <role>` as a stdlib-only, non-mutating execution control. The public manager owns the open descriptors, subprocess execution, and state commit; the oracle owns only fixture copies, physical attacks, barrier release, and independent filesystem snapshots.

- `stage_release(package_fd, expected_package_sha256, expected_commit, release_id, runtime_root, runner)` consumes the already-open verified package copy, creates versioned `.new` targets on persistent disk, and removes both activation variables from its own environment. It runs uv with an explicit scratch target, `--frozen`, `--python /usr/bin/python3.12`, and `--no-install-project`; it never resolves a bare `.venv`.
- `verify_release(path)` checks Python 3.12, source SHA, lock SHA, `fastapi/httpx/httpcore/uvicorn`, `certifi.where()`, SSL context creation, and a production-shaped application import. Only a verified directory is atomically renamed from `.new` to its immutable release name.
- Final application/runtime/control-plane directories, selectors, and state are root-owned and non-writable to the service/project identities; interpreter/library/source paths remain readable/executable by the service. Device/inode/mode/hash values are included in verification and rollback state. Protecting these release artifacts is required recovery integrity, not a claim that A confines arbitrary project code or hides credentials.
- Active state under `/var/lib/orchestra-runtime/deploy-state/active.json` records the exact previous selector target, selected target, source/lock/unit hashes, activation id, phase, and `pending_mcp_refresh`; writes are fsync + atomic replace and precede selector changes. A separate append-only attempt record preserves failures without changing the byte-for-byte active-state rollback oracle. An incomplete attempt is fail-closed and requires status/rollback, never overwrite.
- The Release A operator command is exactly `systemctl start --wait orchestra-runtime-recovery@<activation-id>.service`; Release B–D use exactly `systemctl start --wait orchestra-boundary-activate@<activation-id>.service`. The installed manager refuses to run in `orchestra.service` or without root-owned state. The selected one-shot unit is the rollback owner and remains alive across old/new supervisor death. The installer never runs these commands.
- The activation id is sent with `POST /api/restart`. Before the pending app yields its lifespan it closes both existing admission gates and calls `auto_resume_all(adopt_only=True)`: handed-over Codex pipes are adopted, but idle reconnect, inbox drain, bg restore, TG polling, merge restore, and other background consumers are deferred. After yield, middleware allows only liveness plus activation probe/commit/abort and returns 503 for every ordinary route. The probe reports internal hashes/import/SSL checks but cannot open the gate. Commit runs the deferred startup first and opens ordinary/manager admission only if it completes; a deferred-start failure stays closed for external rollback.
- Bootstrap explicitly supports today's already-running supervisor, which cannot know the new activation routes before its first restart. A normal 200/409 uses the old endpoint contract. On an ambiguous response timeout the external owner does **not** restore the selector while the legacy restart task might still signal: it watches the exact old PID through the current `_watchdog_budget_s()` plus a fixed margin. A new PID enters the pending-supervisor path; if the exact old PID remains healthy after that bound, the old code has necessarily aborted/reopened or its watchdog has fired, so the owner restores the old selector and makes a fresh drained restart request against the old target. This legacy branch is deleted only after an activated release proves every live supervisor advertises the new activation protocol.
- The external owner verifies the new main PID and `/proc/<pid>/exe` against the selected immutable release, checks the probe and ordinary health, fsyncs committed state, then calls commit. Only that call opens admission. A 409 restores exact state immediately. A protocol-aware ambiguous timeout is resolved by activation id: abort/rollback on the still-live old PID, or stop-loop/restore/start-old after old exit.
- `rollback_release(...)` never guesses “previous” by directory order. Before new-process commit it stops `orchestra.service` when necessary to prevent systemd restart loops, restores selector and active-state bytes, starts the recorded old runtime, and requires a positive old-runtime health check before success. After a committed activation it performs a new drained transaction rather than rewriting a live selector.
- `status` reports current/staged/previous hashes; main PID/executable; `(deleted)` mappings; old-runtime references; adopted sessions; and MCP processes still awaiting boundary refresh. Cleanup is a separate explicit command allowed only when every old-path reference count is zero.

The normal success path does not issue an unconditional `systemctl restart orchestra`; existing application logic remains the sole owner of turn/mutation drain and FD handoff. The external owner may stop/start only after a post-signal failure, while the pending gate is closed, to break a restart loop and restore the old verified runtime. No identity, environment allowlist, or provider-auth change belongs in A, and the report must state that same-UID attack prevention is absent.

### Shared root attestation and one-use activation contract

Release B/C/D evidence and every activation use the installed `boundary_attestor` and `attestation_policy` artifacts from the selected root control plane. The pre-B worktree copies are build inputs only: root never imports or executes them. The installed attestor has a fixed no-shell argv table mapping release to one installed producer role; a report-supplied path or command is invalid.

An activation transaction first creates `/var/lib/orchestra-runtime/activations/<activation-id>/request.json` under a root-only directory with a 256-bit random nonce. Attestation schema `orchestra.task303.attestation.v2` is Ed25519-signed by a root-only 0600 private key; the public key is a root-owned hash-pinned raw 32-byte Ed25519 key. The signature covers canonical UTF-8 JSON with `sort_keys=True`, compact separators, and only the top-level `signature` field omitted. Root-owned 0700 state contains results and the consumed-nonce ledger. The signed record binds all of:

- release, activation id, nonce, exact installed wrapper/producer paths and hashes, producer argv, result hash, and control-selection hash;
- current `/proc/sys/kernel/random/boot_id` plus SHA-256 of `/etc/machine-id`, preventing cross-boot and cross-host use;
- target PID and `/proc/<pid>/stat` starttime, preventing PID-reuse/cross-process use;
- live `/proc/<pid>/exe` path, device, inode, size, and SHA-256 plus the selected application/runtime/provider fingerprints;
- issued/finished/expiry timestamps with a maximum ten-minute lifetime, and protected-store/provider-manifest fingerprints where applicable.

The installed public command `manage_orchestra_runtime.py authorize-commit` is the activation consumer reached by the fixed installed boundary unit's sole `ExecStart`. It owns the full ordering—verify evidence, recompute current context, atomically consume, then apply selector/admission/process state—and resolves any internal policy code itself from the root selection. Neither the oracle nor an application route supplies a verifier, nonce helper, apply callback, or policy callable; no application route may directly apply this state. Success creates the nonce receipt with one atomic create-if-absent transaction (`O_CREAT|O_EXCL` or an equivalently proven single-winner primitive), fsyncs the receipt, and only then applies once. Check-then-write (`exists()` followed by ordinary creation) is forbidden. Missing/invalid signatures, stale records, another activation, boot, host, PID/starttime, runtime inode/hash, selected manifest/store drift, or a consumed nonce fail before any authority-state mutation.

The Ed25519 signature remains only because B/C/D evidence is detached from the root producer that created it; no second signature/MAC/key hierarchy is added. Local command authority comes from the installed root-owned manager, root-only state, and Unix identity, not from cryptography. If Phase 3 keeps producer and consumer in one root-owned process and removes detached evidence, it may simplify the signature layer only by refreezing this gate; it may not weaken context binding or atomic one-use consumption.

The frozen helper `docs/tasks/303/oracle_support.py` generates records/attacks, parses the restricted systemd `ExecStart`, invokes the derived public commands, releases filesystem barriers, and snapshots state; it implements no verification, replay, or apply policy. `/usr/bin/openssl pkeyutl` is calibrated against RFC 8032 vector 2 and garbage/bit-flip/wrong-key controls before the manager is invoked. Every invalid arm enters the exact operation derived from the installed boundary unit and leaves its temporary instance of the production `current`, `deploy-state/active.json`, `activation-state/admission.json`, `activation-state/process.json`, apply journal, and consumed ledger unchanged.

The concurrency arm launches two byte-identical copies of the argv derived from the installed boundary unit for the same signed record and shared state. The manager places each contender at `validated_before_consume`; only after both distinct PIDs are present does the oracle release the barrier. Exactly one process must return `authorized`/exit 0, one must return `replay`/exit 73, the receipt count must be one, and the real active/admission/process files plus append-only apply journal must all show `apply_count=1` with only the winner PID. A third identical call must return replay with an exact zero state delta. Thus a check-then-create ledger, a dead correct command beside a bypassing unit, or a loser-side apply makes the gate red deterministically.

### Release B — dedicated non-sudo project-execution identity

Files:

- `app/execution_identity.py` (new): common fail-closed async/sync launchers that submit every arbitrary-code child to the executor service, verify returned PID/UID and passed stdio descriptors, and label every seam.
- `deploy/manage-project-execution-user.sh` (new), `deploy/orchestra-project-executor.socket` (new), `deploy/orchestra-project-executor@.service` (new): stage/activate/status/rollback for separate `orchestra-controller` and `orchestra-project` identities, a peer-checked root-owned local execution socket, and a worktree/cache ownership manifest. The service runs as the non-project controller UID; each executor instance runs as the project UID and can spawn only inside registered project roots. Neither identity has sudo, privileged groups, capabilities, a login shell, or a writable activation socket.
- `app/backend_codex.py`, `app/backend_claude.py`, `app/backend_grok.py`, `app/backend_opencode.py`: launch the interim whole CLI under the project identity. This establishes service integrity but deliberately does not claim provider credential confidentiality.
- `app/bg_jobs.py`: local `run`, `command`, `cron_command`, file helper children, and the local SSH client cross the same identity boundary. Remote-host policy remains separate.
- `app/acceptance.py`, `app/merge_test_gate.py`: project-supplied acceptance and pytest code run through the common launcher.
- `app/workspace.py`, `app/prompting.py`: replace the two permissive `gosu-if-present` copies with the common fail-closed primitive.
- `app/runtime_registry.py`: project MCP is classified as a project-execution seam; the provider CLI that launches it is under the project identity in B, and the C broker retains that same identity later.
- `scripts/rehearse-project-identity.py` (new): production-shaped UID, bypass, and real-project compatibility evidence; packaged as the installed `project_identity_rehearsal` role before root execution.
- `scripts/attest-boundary-rehearsal.py`, `scripts/attestation-policy.py` (new): packaged as the installed `boundary_attestor` and `attestation_policy` roles implementing the shared signed, live-bound, one-use contract above.
- `docs/tasks/303/release-b-evidence.json` (generated): exact consumer hashes, observed child UIDs, errno/canary outcomes, compatibility rows, and ownership round-trip. C and D must regenerate it after changing a consumer so the frozen B oracle stays green.

`app/execution_identity.py` fails startup when either identity is absent, the controller and project UIDs are equal, either has sudo/privileged groups, the executor socket/unit is missing or writable, peer credentials do not equal the controller UID, or a spawned PID does not report the project UID. “Could not delegate, ran locally” is forbidden. No setuid/sudo helper is available inside `orchestra.service`; the already-effective `NoNewPrivileges=yes` remains enabled. All arbitrary-code children receive a project-owned HOME/cache and no service venv prefix.

Before activation, a filesystem inventory proves the service source/config/database/transcript paths and every Release A runtime/state path are owned by root or `orchestra-controller`, not writable by `orchestra-project`, and return `EACCES` to direct executor reads where sensitive. Project worktrees/cache are the inverse: writable by the project UID; controller access is limited to metadata and the explicit broker protocol, not ambient project-code execution.

The test-defined AST gate rejects raw project-capable subprocess calls in the named consumers and requires an executable common-boundary call; it mutates away each call while leaving imports behind and must turn red. The one allowlist is Codex's service-controlled systemd feature probe in `_run_process`; its argv and cwd are constants and it is not a project seam. This mechanical gate complements rather than replaces the observed-UID rehearsal.

The privileged rehearsal runs on persistent scratch storage against fresh `--no-local` clones of current Orchestra and the DND project, owned by the proposed project UID. It records current consumer hashes and, for each backend, bg subtype, local SSH, project MCP, acceptance, merge, workspace, and prompting seam, observes only the project UID, a successful worktree write, a successful cache write, and a protected-target `EACCES`. Before the run it records pass/fail criteria: dependency count > 0, `uv sync --frozen`, `uv run`, one focused pytest command, cache writes, and a native-build subprocess must succeed. It then repeats the attack matrix against a service-owned canary/runtime alias:

- inherited `VIRTUAL_ENV` + `--active`;
- inline absolute `UV_PROJECT_ENVIRONMENT`;
- `uv venv --clear PATH`;
- symlink alias;
- absolute uv binary and direct Python filesystem write;
- `sudo`;
- background run/command/cron, local SSH, project MCP, acceptance command, and merge pytest.

Every local mutation must fail with `EACCES`, not because uv is missing or a wrapper matched text. Positive controls must still write worktree/cache. Source/path hashes prove the protected canary was not replaced. The report lists every observed child UID, captures the local SSH **client** UID separately from remote-host authority, and does not add exploratory reruns to the confirming sample.

The B oracle accepts the JSON only with a consumed schema-v2 `/var/lib/orchestra-runtime/attestations/task303/release-b.json` produced by the installed root control plane. It validates signature/key/state ownership, activation/host/boot/PID/starttime/runtime/expiry binding, the exact installed producer role and command, root-owned result digest, and the one-use receipt before reading B claims. Current repository hashes are not a trust root. A handwritten JSON, a worktree replacement, a stale/cross-host/cross-PID record, a report from another run, or replay of the same valid record cannot satisfy the gate.

Migration: inventory existing worktree/cache ownership before changing it; record each changed path and prior uid/gid/mode in a root-owned rollback manifest; refuse an empty or changed inventory. Activate through Release A's application restart. Existing adopted Codex processes retain the old UID until their turn boundary; the boundary is not declared active until no old-UID CLI/MCP/bg/test child remains. Rollback restores the exact ownership manifest and launcher setting through the same drained restart.

### Release C — credential-bearing controller versus uncredentialed project tools

Files:

- `app/provider_boundary.py` (new): provider policy registry, dedicated controller launch/IPC, exact evidence validator, and all-provider fail-closed latch.
- `app/provider_inputs.py` (new): production resolver for the candidate provider launcher, ordered effective non-secret configuration, and auth-store path. It is deliberately **not** the oracle's source of truth.
- `app/project_tool_broker.py` (new): the only project filesystem/process/network tool host; it always invokes Release B's project identity and never receives provider stores.
- `deploy/manage-provider-controller-user.sh` (new): stage/status/rollback for a non-login `orchestra-credential` identity and its 0700 auth roots; the service and project UIDs cannot read those roots.
- `deploy/orchestra-provider-controller@.service` (new): credential UID, neutral working directory, peer-checked Unix IPC, read/write access only to the selected provider store, and a mount namespace that hides registered project roots/worktrees plus service secrets/state.
- `app/backend_codex.py`, `app/backend_claude.py`, `app/backend_grok.py`, `app/backend_opencode.py`: provider-specific controller adapters, neutral controller cwd, native arbitrary tools disabled/rerouted, and no project worktree mount/read path in the controller domain.
- `app/runtime_registry.py`: selects only a provider adapter whose completed capability record matches the current binary/version/config hash.
- `scripts/rehearse-provider-boundary.py` (new): positive authentication and negative direct-read matrix for all four supported providers.
- `docs/tasks/303/release-c-evidence.json` (generated): one current, exact-hash row per provider. It contains fingerprints/hashes and pass/fail facts, never token values.
- `/var/lib/orchestra-runtime/provider-selection.json` (root-owned generated state, not committed): operator-pinned provider manifest independently consumed by the frozen oracle and enforcement latch.

Controller credentials are stored outside project-readable directories, owned by `orchestra-credential`, mode 0600 under a 0700 root, never symlinked into a project-owned home, and never copied to argv/environment/MCP configuration/logs. The service and project UIDs get `EACCES` on those stores; the controller UID gets `EACCES` on service `.env`, DB/transcripts, and registered project roots. The service talks to the controller over a root-owned Unix socket with peer-UID checks; the controller receives only the provider protocol and a neutral cwd inside the unit's mount namespace. Every model-selected Read/Write/Edit/Glob/Grep/Bash/test/MCP/background/network operation must be disabled natively and exposed through `project_tool_broker` under the project UID. A prompt, approval callback, path parser, or best-effort hook is not the boundary.

Provider adapters may use different mechanisms (for example a provider-supported external code-mode host versus disabling native tools and supplying the broker), but they share one observable contract. Phase 3 starts with a production-binary feasibility probe for each adapter; this is not a shipping mode. Unknown binary version/config hash, an unclassified tool, inability to disable an in-process read, or a provider whose subscription CLI cannot delegate tools to the broker leaves the global latch off and stops T-C for architecture approval. No partial provider list and no “mostly isolated” green status are allowed.

The operator stages each selected provider launcher/package into `/usr/libexec/orchestra-runtime/providers/<provider>/<binary-sha256>/` as a root-owned, non-writable regular-file tree. The fixed root manifest records provider-specific launcher name/path plus device/inode/size/hash, ordered effective config file identities and digest, controller UID, and auth-store absolute path/mode/device-inode/content fingerprints. Its provenance is the independently verified package/control-plane selection, not `resolve_provider_inputs` and not rehearsal JSON. Auth values never enter the manifest.

`resolve_provider_inputs(provider)` returns the production candidate `{"binary": <absolute path>, "config_files": [...], "auth_store": <absolute path>}`. Runtime registry calls both it and `enforcement_latch`; activation accepts the candidate only when every field matches the independently parsed root manifest and live identities. The frozen oracle opens the fixed manifest directly, validates root ownership/mode/provenance, enforces the provider-specific launcher name and root path, hashes the actual executable and ordered config files, checks the auth-store identity/fingerprint against attested controller state, and only then compares the production resolver output. It never asks the resolver what the expected path is. Two executable counterexamples are mandatory: a resolver returning `/bin/true`, and a copied manifest/resolver pair rewritten consistently to `/bin/true`; the first must mismatch the real manifest and the second must fail the oracle's provider-specific root/name/identity rule. The enforcement latch also rejects the altered manifest.

The production-shaped rehearsal is mandatory for **Codex, Claude, Grok, and OpenCode**. For each provider it must:

1. start the real CLI as the controller identity;
2. complete one authenticated model turn;
3. exercise token refresh/reauthentication (or a provider-documented equivalent with expiry forced in an isolated credential copy);
4. have the model attempt direct provider-store reads through native Read, Bash, a project test, project MCP, and background run;
5. show all project attempts execute under the project UID and receive `EACCES` while the authenticated controller remains usable;
6. scan argv, environ, project configuration, worktree files, and task logs for canary values, not just variable names; the protected credential store itself is the positive controller-readable control and is excluded from the leakage set.

C cannot ship until all four rows pass on the exact deployed binary/config hashes. The frozen oracle mutates authenticated-turn, refresh, EACCES, leak-count, binary-hash, and config-hash evidence and removes/adds a provider; every mutation must hold the latch closed. A failure is not waived by disabling one assertion or calling a provider “trusted.” Rehearsal uses isolated controller-owned copies and leaves the B-era stores untouched. Activation waits for current turns, drains every B-era credential-bearing CLI, atomically selects the controller-owned store/policy, and retains prior files. A pre-commit failure may restore the explicitly documented B baseline because it was never removed; after C commits, rollback selects the previous **verified C controller release** or disables providers fail-closed—it never returns credentials to the project UID. Refreshed controller tokens are versioned and never deleted by rollback. T-C also regenerates and reruns Release B evidence after backends move from whole-CLI project UID to controller+broker.

Like B, C is accepted only with a consumed signed schema-v2 `release-c.json` from the installed root control plane after a fresh exit-0 run. The activation id and attestation both bind the independently parsed provider-manifest digest and current protected-store fingerprints. Manifest/store drift, a shared-resolver lie, stale auth evidence, or replay keeps the latch closed even when application code hashes are unchanged.

### Release D — scoped environments, path guard, service-secret removal, observability

Files:

- `app/runtime_env.py`: replace import-time `MCP_BASE_ENV` inheritance with explicit `WORKER_ENV_ALLOWLIST`, `build_worker_env`, per-server `build_mcp_server_env`, target audit, and registered-copy cleanup; strip activation variables/service PATH and pass only named keys.
- `app/mcp_capability.py` (new), `app/main.py`, `app/mcp_stdio.py`, `app/manager.py`: replace the global `INTERNAL_TOKEN` in MCP children with an opaque session/scope/access-mode capability. Middleware validates the capability and route claims server-side; the token cannot authenticate as another session or as an operator.
- `app/runtime_registry.py`: keep each custom MCP server's env attached only to that server; never flatten server env into the model CLI.
- `app/project_tool_broker.py`: project operations consume `build_worker_env`; controller adapters keep C's separate credential-free controller environment and file-based auth store.
- `app/backend_codex.py`, `app/backend_claude.py`, `app/backend_grok.py`, `app/backend_opencode.py`: remove inherited service environment, consume only their C controller policy plus explicit non-secret proxy/locale keys, and log only key/action metadata.
- `app/workspace.py`: remove `.env` from unconditional `PROJECT_FILES`; add an explicit per-project scoped-secret manifest.
- `scripts/audit-worker-boundary.py` (new): environment/argv/config/file/process audit and structured `ENV_BOUNDARY_EVENT` validation.
- `docs/tasks/303/release-d-evidence.json` (generated): guard-disabled Release B rerun, canary counts, and archive/kill revocation results.

`build_worker_env(source, home, path)` copies only the named locale/terminal/proxy keys plus the supplied project HOME/PATH; activation variables, service/provider credentials, and arbitrary `.env` keys are absent. `build_mcp_server_env` starts from the same base, adds only one server's declared keys plus a scoped `ORCHESTRA_CAPABILITY`, and rejects any server attempt to set a service-only key. Two-server tests prove no cross-server value appears.

The Phase 3 constant is verbatim (session/provider metadata and the capability are explicit function arguments, never inherited):

```python
WORKER_ENV_ALLOWLIST = frozenset({
    "HOME", "PATH", "XDG_CACHE_HOME", "UV_CACHE_DIR", "PIP_CACHE_DIR",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TZ", "TMPDIR",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
})
```

The configured-target guard canonicalizes existing and not-yet-created parents, resolves symlink aliases, and rejects `VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT`, pip/uv `--python`, or MCP-provided target paths that resolve outside the worktree/project cache or inside protected service/runtime roots. It emits exactly `type`, `session_id`, `provider`, `source`, `key`, normalized `target_class`, and `action`—never a value or path. The guard is diagnostic/defence in depth; the D evidence is generated by rerunning the Release B direct attacks with the guard explicitly disabled, and every attack must still receive kernel `EACCES`.

`McpCapabilityStore` issues opaque, revocable claims bound to exact session id, canonical scope, and access mode. Middleware re-resolves those claims server-side on every request; cross-session/scope/mode use and every operator route raise 403. Spawn/reconnect/identity refresh reissues; archive and kill revoke before teardown. This capability replaces, never wraps, the worker-visible global `INTERNAL_TOKEN`.

Secrets migration is fail-closed and non-destructive:

- Stop new default `.env` copies.
- Inventory existing injected `.env` files from a fresh worktree registry and compare source/destination/copied hashes in the same operation. `cleanup_injected_env_copies(records, manifest_complete=True)` refuses empty/incomplete inventories; it removes only a registered unchanged copy with `replacement_ready=true`. Modified, ambiguous, missing-registry, or replacement-not-ready paths are reported and left untouched. The frozen oracle performs this deletion only in a temporary directory.
- Service `.env`, database/transcripts, provider stores, and the global internal token never enter project worktrees/processes. Project-specific credentials are individually declared and scoped; no wildcard pass-through.
- Reissue MCP capabilities on spawn/reconnect/identity refresh; revoke on archive/kill. A stolen capability is limited to its bound session/scope/access mode and cannot mutate operator-only routes.

Rollback restores the exact scoped-secret manifest and environment-policy version, not the global token in worker environments. If scoped capability validation fails, MCP fails closed and the prior application version is selected through Release A's rollback; secrets are not widened to regain availability. D regenerates Release B and C evidence after environment/capability changes and all three predecessor RED commands must remain green.

The guard-disabled run is accepted only with the installed root control plane's consumed signed schema-v2 `release-d.json`. The oracle applies the shared activation/host/boot/PID/starttime/runtime/expiry/one-use checks and installed producer-role/result binding before reading any D claim; repository wrapper hashes cannot authorize it.

## Cross-release bypass and regression matrix

| Vector / regression | A | B | C | D | Required evidence |
|---|---|---|---|---|---|
| hostile worktree replaces manager/probe/hook | installed root copy still executes; hostile sentinel absent | unchanged | unchanged | unchanged | A direct hostile-worktree arm |
| package symlink / path swap / post-verify replacement | reject symlink/identity drift or keep the already-open verified inode | unchanged | unchanged | unchanged | A symlink + FD-pinned TOCTOU arms |
| inherited `VIRTUAL_ENV` / `uv run --active` | Direct ExecStart avoids accidental inheritance after restart; no enforcement claim | DAC denies service target | Project tools stay in project UID | variables stripped/audited | B EACCES + positive local uv |
| inline `UV_PROJECT_ENVIRONMENT` | Still bypasses A | DAC denies | project broker UID denies | guard may be bypassed; audit if visible | B EACCES |
| `uv venv --clear`, `uv pip --python`, direct filesystem | Still bypasses A | DAC denies | broker UID denies | no command-name claim | B EACCES |
| symlink/alternate path | Still bypasses A | target ownership denies | broker UID denies | realpath guard rejects configured paths | B EACCES + D event |
| absolute uv/wrapper bypass | Still bypasses A | DAC denies | broker UID denies | wrapper not trusted | B EACCES |
| sudo/external launcher | Same current risk | project user has no sudo; all local launchers verified | controller cannot expose privileged launcher | audit unexpected UID/process | negative sudo + PID inventory |
| bg/cron/local SSH | A only preserves them across restart where applicable | local child project UID | no provider auth in child | minimal env/capability | child UID + EACCES |
| project MCP env injection | Not addressed | MCP child project UID cannot write service | no provider store | per-server allowlist; no CLI flatten | config/env inspection + target attack |
| acceptance / merge pytest | Recovery preserves result continuity | project UID | no provider store | minimal env | child UID + EACCES + focused tests |
| active Claude/Grok turn during activation | existing restart waits up to 900 s, then aborts | same | same | same | no signal while blocker exists |
| active Codex + old MCP | CLI handoff; stale MCP refresh next boundary | claim waits for old UID/MCP absence | claim waits for controller/tool policy hash | new capability appears only after refresh | turn completes + PID/path inventory |
| failed activation | exact selector rollback; no in-place rebuild | exact uid/ownership manifest rollback | provider registry rollback | policy-version rollback; no secret widening | rehearsal at every failure cut |
| stale/cross-host/cross-PID/replayed attestation | no selector/admission change | fail closed | fail closed | fail closed | schema-v2 live-binding mutations + one-use receipt |
| provider login/refresh | unchanged | remains delegated and exposed as baseline | must pass positive controller check | never passed to project env | per-provider live matrix |
| provider direct-read exfiltration | unchanged | unresolved and explicitly reported | native/project attempts get EACCES | canary absent from env/argv/config/log/files | all four provider rows green |

## Migration and operator activation

Implementation commits may add code, unit templates, rehearsal tooling, and unprivileged package artifacts, but they do not install or activate production. During implementation each release produces only the V12 pending delivery report. The signed/host-bound rehearsal record is produced later, in the separately authorized privileged lane. Activation needs a new explicit user authorization because it changes a live service, Unix identities, filesystem ownership, or credential routing.

Minimal staged rollout and rollback:

1. **A0, already active:** retain the measured `/opt/orchestra/runtimes/...` direct ExecStart, env unsetting, read-only runtime, and `NoNewPrivileges`. No operator action is part of this plan turn.
2. **A-delivery, authorized after this plan gate:** implement source, build the installable package unprivileged, and stop with `activation_ready=false` / `privileged_evidence=pending`. This step does not copy into `/opt` or `/usr/libexec`, install units, call PID 1, close admission, drain turns, or claim isolation.
3. **A-activation, separately authorized later:** install the versioned root-owned package/manager and recovery unit beside A0 without starting them. After all active turns have drained through the existing handoff, an explicitly authorized operator starts the fixed recovery unit and admission stays closed until postchecks. Any failure restores the exact A0 ExecStart/selector bytes and starts the measured healthy runtime; old MCP is refreshed only at turn boundaries.
4. **B-delivery then B-activation:** first implement/package with a pending-only report. In the later operator window, install the fixed boundary-activation unit, create controller/project identities and the executor service, migrate one seam inventory under a closed gate, drain every old-UID child, then use that unit to atomically authorize/apply the switch to `orchestra-controller`. Any missing seam, UID mismatch, compatibility failure, replay, or unit/manager identity mismatch restores the ownership manifest and A launcher policy before admission reopens.
5. **C-delivery then C-activation:** first implement/package without moving credentials. In the later operator window, migrate one provider at a time in rehearsal but activate only when all four provider rows pass; then select the controller/broker policy atomically. Pre-commit rollback restores the explicit B baseline; post-commit rollback selects the previous verified C release or disables the failing provider, never returns credentials to `orchestra-project`. Any provider that cannot pass startup, authenticated turn, refresh, and all adversarial EACCES arms stops C for architecture approval.
6. **D-delivery then D-activation:** first implement/package the defence-in-depth code. Later install env/capability/guard policy only after B+C remain green with guards disabled. Rollback selects the previous policy version and never restores a global worker token.

Every activation uses a fresh bound one-use record through the public manager consumer. A delivery report is never an input to that consumer. At every activation step, a failed precondition leaves or restores the exact previous selector/policy; the append-only attempt record is the only retained delta. Start/stop/restart and identity/credential activation remain separate explicit operator actions.

## What not to touch

- Do not repair, sync, delete, chmod, or repoint `/home/kesha/orchestra/.venv` during implementation or tests.
- Do not restart/start/stop Orchestra or `telegram-bot-api` without a new explicit user command.
- Do not alter external VPS deployments, remote Git histories, provider login files, or other projects' worktrees during implementation.
- Do not weaken, skip, rename, or edit any preserved V9–V11 oracle file. V3–v8 plus their reviews/audits remain historical rejection evidence only. V9 is preserved approved seam evidence; V10 is preserved approved delivery/activation-split evidence; V11 is preserved approved link/TOCTOU evidence but is unsatisfiable across fresh runtime prefixes. Only the V12 hashes and commands recorded by `plan-baselines.json` may be used for implementation.
- Do not create, edit, chmod, chown, mount, or synthesize `/var/lib/orchestra-runtime`, `/opt/orchestra/runtimes`, `/usr/libexec/orchestra-runtime`, installed unit files, Unix accounts, provider stores, or PID 1 state during implementation. Do not copy their shape into a temporary fake root and call that activation evidence.
- Do not mark a privileged activation command green, skipped, unavailable-as-success, or satisfied by a delivery report. `activation_ready=false` and `privileged_evidence=pending` are the only valid implementation-phase values.
- Do not claim Release A is prevention, B is provider-secret isolation, a D path guard is enforcement, or the final Sol research verdict was approved.
- Do not delete ambiguous `.env` files or old runtimes. Cleanup requires a positive registry/reference result.

## Tickets

### T-A — Finish the emergency versioned-runtime control plane
- Files: `scripts/build-orchestra-runtime-package.py` (new); `scripts/manage_orchestra_runtime.py` (new); `scripts/rehearse-runtime-recovery.py` (new); `scripts/runtime-activation-probe.py` (new); `scripts/runtime-activation-hook.py` (new); `scripts/attestation-policy.py` (new); `scripts/attest-boundary-rehearsal.py` (new); `app/runtime_activation.py` (new); `app/main.py`; `app/manager.py`; `app/routes/system.py`; `deploy/orchestra.service`; `deploy/orchestra.service.template`; `deploy/orchestra-runtime-recovery@.service` (new); `deploy/orchestra-boundary-activate@.service` (new); `deploy/orchestra-authority-surface.json` (new); `deploy/install.sh`; `docs/tasks/303/recovery-runbook.md`; installed generated state under `/usr/libexec/orchestra-runtime/control-planes/`, `/opt/orchestra/runtimes/`, `/etc/systemd/system/`, and `/var/lib/orchestra-runtime/` (not committed)
- Test: V12 unprivileged delivery runner plus the exact A source/package node ids embedded in it — committed RED in the V12 freeze named under `## Frozen RED gate`
- Delivery RED command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 python docs/tasks/303/v12_delivery_gate.py A`
- Failing assertion: `AssertionError: T-A missing behavior: the live unit still starts through a mutable uv environment`
- Deferred privileged activation command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 pytest -p no:cacheprovider -q docs/tasks/303/test_authority_oracle_selftest.py docs/tasks/303/test_release_a_recovery.py::test_ta_activation_control_plane_and_service_source_are_root_owned_and_pinned docs/tasks/303/test_release_a_recovery.py::test_ta_package_open_rejects_symlinks_and_copy_is_fd_pinned docs/tasks/303/test_release_a_recovery.py::test_ta_real_installed_artifacts_cannot_change_between_verification_and_execution docs/tasks/303/test_release_a_recovery.py::test_ta_scratch_transaction_handoff_and_failure_cuts`
- Delivery AC: the delivery command is green from a clean committed tree and creates `release-a-delivery-evidence.json`; the frozen validator accepts the independently inspected archive/manifest; the report says exactly `activation_ready=false`, `privileged_evidence=pending`, `activation_authorized=false`, `isolation_claimed=false`, and `activation_receipt=null`; the already-measured emergency layer remains unchanged; no `/opt`, `/var/lib`, installed unit, PID 1, service process, account, or secret mutation occurs. This closes T-A implementation only, not Release A activation.
- Release/activation AC (not authorized in this implementation phase): the deferred command is green on the real installed host and proves every V9 root/systemd/TOCTOU/drain/handoff/rollback arm. Until then Release A remains unactivated and its delivery report cannot be consumed as authority. Report wording is exactly `Isolation: not provided by Release A`.
- blocked-by: none

### T-B — Kernel-enforced project execution identity
- Files: `app/execution_identity.py` (new); `deploy/manage-project-execution-user.sh` (new); `deploy/orchestra-project-executor.socket` (new); `deploy/orchestra-project-executor@.service` (new); `deploy/orchestra-boundary-activate@.service` (installed by T-A, activated first by T-B); `deploy/orchestra.service`; `app/backend_codex.py`; `app/backend_claude.py`; `app/backend_grok.py`; `app/backend_opencode.py`; `app/bg_jobs.py`; `app/acceptance.py`; `app/merge_test_gate.py`; `app/workspace.py`; `app/prompting.py`; `app/runtime_registry.py`; `scripts/rehearse-project-identity.py` (new packaged producer); `scripts/attest-boundary-rehearsal.py` and `scripts/attestation-policy.py` (new packaged root roles); `docs/tasks/303/release-b-evidence.json` (generated); root-only activation/attestation/result/consumption state (generated, not committed)
- Test: V12 unprivileged delivery runner plus the exact B source/package node ids embedded in it — committed RED in the V12 freeze
- Delivery RED command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 python docs/tasks/303/v12_delivery_gate.py B`
- Failing assertion: `AssertionError: T-B missing behavior: no mandatory project-execution identity boundary exists`
- Deferred privileged activation command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 pytest -p no:cacheprovider -q docs/tasks/303/test_authority_oracle_selftest.py docs/tasks/303/test_release_b_identity.py::test_tb_public_activation_consumer_atomically_consumes_concurrent_replay docs/tasks/303/test_release_b_identity.py::test_tb_privileged_rehearsal_observes_uid_eacces_and_real_uv_compatibility`
- Delivery AC: the delivery command is green and writes the same pending-only schema for B; every named arbitrary-code consumer calls the fail-closed launcher; the package contains the executor service and rehearsal producer but no account state, credential-store/config payload, attestation, receipt, private-key material, or recognized literal token, while exact comparison against protected root-only values remains explicitly pending; no UID or service change occurs. This does not claim that the live service or children use the new identities.
- Release/activation AC (deferred): the privileged command is green on the real installed host and proves the actual boundary unit/manager seam, independent Ed25519 controls, atomic concurrent replay, every observed UID/EACCES/bypass row, representative real-project `uv` compatibility, ownership rollback, and zero old shared-UID children. Until then `Provider credential confidentiality: unresolved until C`, and B isolation is not active.
- blocked-by: T-A

### T-C — Credential controller and uncredentialed project tool broker
- Files: `app/provider_boundary.py` (new); `app/provider_inputs.py` (new production resolver); `app/project_tool_broker.py` (new); `deploy/manage-provider-controller-user.sh` (new); `deploy/orchestra-provider-controller@.service` (new); `app/backend_codex.py`; `app/backend_claude.py`; `app/backend_grok.py`; `app/backend_opencode.py`; `app/runtime_registry.py`; `scripts/rehearse-provider-boundary.py` (new packaged producer); `docs/tasks/303/release-b-evidence.json` (regenerated); `docs/tasks/303/release-c-evidence.json` (generated); root-owned provider binary trees and `/var/lib/orchestra-runtime/provider-selection.json`; root-only activation/attestation/result/consumption state (generated, not committed)
- Test: V12 unprivileged delivery runner plus the exact C source/package node ids embedded in it — committed RED in the V12 freeze
- Delivery RED command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 python docs/tasks/303/v12_delivery_gate.py C`
- Failing assertion: `AssertionError: T-C missing behavior: provider credentials and project tools share one authority domain`
- Deferred privileged activation command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 pytest -p no:cacheprovider -q docs/tasks/303/test_release_c_credentials.py::test_tc_all_provider_probe_rows_are_current_complete_and_non_leaking docs/tasks/303/test_release_c_credentials.py::test_tc_one_failed_or_unknown_provider_holds_the_global_latch_closed`
- Delivery AC: the delivery command is green and writes the pending-only C report; the package contains controller/broker/resolver source but no credential-store/config payload, auth store, selection, signed evidence, private-key/recognized-token material, or receipt; `protected_secret_comparison` remains `pending_privileged_activation`; no provider process/login/refresh or secret movement occurs.
- Release/activation AC (deferred, global fail-closed): the privileged command and B activation command are green with fresh installed evidence; the oracle independently pins exact deployed provider executable/config/auth identities and rejects both `/bin/true` lies; all four providers pass startup, authenticated turn, refresh, and project-UID EACCES across Read/Bash/test/MCP/background with zero canary leakage. A missing, unknown, stale, partial, or failed provider keeps the entire C latch closed. If any deployed subscription CLI cannot pass, STOP for architecture approval; no partial provider list ships.
- blocked-by: T-B

### T-D — Scoped env/capability, path diagnostics, and secret cleanup
- Files: `app/runtime_env.py`; `app/mcp_capability.py` (new); `app/main.py`; `app/mcp_stdio.py`; `app/manager.py`; `app/runtime_registry.py`; `app/project_tool_broker.py`; `app/backend_codex.py`; `app/backend_claude.py`; `app/backend_grok.py`; `app/backend_opencode.py`; `app/workspace.py`; `scripts/audit-worker-boundary.py` (new); `docs/tasks/303/release-b-evidence.json` and `release-c-evidence.json` (regenerated); `docs/tasks/303/release-d-evidence.json` (generated); root-owned B/C/D attestations under `/var/lib/orchestra-runtime/attestations/task303/` (generated, not committed)
- Test: V12 unprivileged delivery runner plus the exact D source/package node ids embedded in it — committed RED in the V12 freeze
- Delivery RED command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 python docs/tasks/303/v12_delivery_gate.py D`
- Failing assertion: `AttributeError: module 'task303_runtime_env' has no attribute 'build_worker_env'`
- Deferred privileged activation command: `env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 pytest -p no:cacheprovider -q docs/tasks/303/test_release_d_env.py::test_td_release_b_attacks_still_fail_with_the_path_guard_disabled`
- Delivery AC: the delivery command is green and writes the pending-only D report; worker/MCP env builders, capabilities, path diagnostics, and safe cleanup pass in scratch; the typed package contains no credential store, recognized token/private key, protected-state record, or activation evidence, while exact protected-value comparison remains pending. This is implementation only and makes no live enforcement claim.
- Release/activation AC (deferred): A/B/C activation gates remain green; the D privileged command proves B's entire direct attack set still returns EACCES with the guard disabled, two-server non-leakage, revocation, canary-zero surfaces, and no rollback reintroduction of `INTERNAL_TOKEN`. D never substitutes for B or C.
- blocked-by: T-C

## Review decision gate

- Changed now: task-local Phase 2 plan plus new V12 delivery validator/runner/self-test; preserved V9–V11 oracle bytes are read-only dependencies. Consumers are the fresh targeted enforcement-oracle auditor, future Phase 3 implementers, and the operator deciding each later release activation.
- Future surfaces: shared supervisor/runtime, auth, Unix permissions, secrets, subprocess/MCP execution, restart lifecycle, and externally consumed provider protocols. Risk floor is mandatory Sol review regardless of diff size.
- Author model/runtime: `gpt-5.6-sol` / Codex, taken from the session metadata used in Phase 1; same-family Sol is adversarial but not cross-family independence.
- Strong oracle status: V9–V11 retain their approved authority, pending-only, link, exact-inventory, and TOCTOU controls. V12 adds the real two-build positive control (3438 members and 408 directories in each, 38 raw differences, zero after normalization), exact five-template plus shebang classifiers, owning-`RECORD` recomputation, a derived full-commit/release install prefix, and attacks for arbitrary prefix, unclassified path, shebang/`RECORD` mismatch, manifest prefix mismatch, and candidate/manifest common-mode lies. Each of the five new guards was disabled once and made its targeted test RED before the clean selftest returned 15 passed. Privileged identity creation, installed ownership/modes, protected-value comparison, PID 1 effective units, live provider turns/refresh, activation/rollback, and secret movement remain non-delegable deferred evidence.
- Completed fresh review: the targeted Sol session inspected only the V12 prefix-normalization contract and frozen tests, attempted the named bypasses and candidate/reference common-mode lies, confirmed root activation remains extraction-only, confirmed package GREEN cannot authorize activation or claim isolation, verified all 23 registered hashes, and returned exact verdict `APPROVED`. `cross-family verdict unavailable` remains explicit.

### First plan review — dissent preserved

Sol round 1 ended `CHANGES REQUIRED` with six blocking findings and one suggestion (`codex-review-plan.md`): one T-A test was already green; A's source-string oracle did not execute failure cuts; B's imports did not prove launch/UID/EACCES; C's empty functions/anchor text did not prove the four-provider gate; D lacked capability/cleanup/per-server/guard-disabled behavior; and A had no rollback owner after supervisor death. It also asked that the installer template be covered without freezing `/home/kesha` into new installs.

The response is the superseding behavioral oracle, current-hash evidence schemas, parameterized template check, and the external transient-unit/closed-admission transaction above. These changes do not erase round-1 dissent; the artifact remains the evidence of why `ff6a8c03` is excluded.

### Second plan review — dissent preserved

Sol round 2 confirmed all seven prior findings resolved, then ended `CHANGES REQUIRED` on two new blockers: B/C/D JSON was not operationally tied to an actual producer run, and C trusted binary/config paths supplied by its own evidence. It also suggested resolving direct-import/alias spellings in B's raw-launch gate.

The response is the fixed root attestation wrapper/nonce/result-digest contract for all privileged producers, independent `provider_inputs` resolution plus byte-level effective-config hashing for C, and alias-aware AST resolution for B. The second-round findings remain appended in `codex-review-plan.md`.

### Third plan review — rejected baseline preserved

Sol round 3 ended `CHANGES REQUIRED — third-round ceiling reached` on three blockers. First, the root wrapper/producers were loaded from the repo-writable worktree, so current hashes proved identity but not trust. Second, attestations lacked activation/live-state/expiry/one-use binding and were replayable. Third, C's oracle asked the same new resolver as production for expected provider paths, so `/bin/true` could be a common-mode result. `ff6aacb7` and its v3 outputs are therefore rejected evidence.

The corrected baseline changes the architecture, not only prose: root runs only a copied independently verified commit-pinned package; an executable A oracle attacks worktree replacement, links and TOCTOU; schema-v2 attestations bind activation/host/boot/PID/starttime/runtime/expiry and atomic consumption; and C reads a fixed root manifest independently and attacks `/bin/true` in both resolver-only and common-mode forms. The orchestrator explicitly authorized one fresh targeted Sol review of only these corrections. Any remaining blocker stops Phase 2 again.

### Fresh targeted review — second rejected baseline preserved

The separately authorized targeted review in `codex-review-plan-corrected.md` ended exactly `CHANGES REQUIRED — corrected three-gate Phase 2 baseline is not valid`. It closed Gate 3 but found that Gate 1 still trusted rehearsal JSON instead of executing a real installed-artifact swap, Gate 2 accepted a shape-valid signature without Ed25519 verification, and Gate 2 tested validation and consumption as disconnected helpers rather than the real activation operation. `622e740e2cd934d7bfe6fac40ab894afef27ac9c` and `red-release-{a,b,c,d}-v4.txt` are therefore rejected, not the implementation baseline. This v5 correction replaces those three mechanisms and deliberately stops before the orchestrator's separate enforcement-oracle audit.

### V5 enforcement audit — third rejected baseline preserved

The independent audit at `docs/reviews/303/enforcement-oracle-audit.md` ended exactly `CHANGES REQUIRED`. Its deterministic counterexample made both contenders pass a check-then-write ledger (`apply_count=2`) while the v5 sequential oracle stayed green. It also showed that Gate 1 called an injected callback adapter rather than the transient manager command, and Gate 2 directly called a helper with injected policy/apply callbacks; both compared oracle-created stand-in files rather than the production state backend. V5 commit `8fe615b9cc89b0f94a8cce9e1d7d8d9f659b2e4e` and hash registry `52d56bba` are therefore rejected evidence. V6 removed injected authority callables and added deterministic concurrency.

### V6 enforcement audit — fourth rejected baseline preserved

The targeted same-family audit in `enforcement-oracle-audit-v6.md` ended exactly `CHANGES REQUIRED`; its background wrapper also marked the artifact blind because execution did not complete, so it is not an approval under either interpretation. It accepted atomic replay and the recovery-versus-prevention split, but found both selected public commands could be correct yet unused: the installer only contained independent `systemd-run`/manager strings and the control selection merely declared expected argv. V6 commit `1ec850dbf5b69a35bdcd6422eca1001f5a3576f8` and hash registry `60e211c6` are rejected evidence. V7 removes generated transient argv and declarative command acceptance: installation cannot activate, the separately authorized operator starts a fixed root-owned unit, and both behavioral gates derive the only allowed manager argv from that unit's actual `ExecStart` before reaching production-shaped authority state.

### V7 enforcement audit — fifth rejected baseline preserved

The fresh audit in `enforcement-oracle-audit-v7.md` ended exactly `CHANGES REQUIRED`. It accepted the real fixed-systemd-unit binding and deterministic two-process replay, but found a remaining false-green path: `deploy/install.sh` was checked only for a few literal forbidden strings, and neither that check nor the unit behavior covered all other shipped scripts/application routes. An installer could construct the unit name before `systemctl start`, invoke a manager variable directly, or ship an alternate application authority route while the tested fixed unit remained correct but unused. V7 commit `c83f4437e73432e6b3752014b7786126e59b48a2`, registry `316c8d5a`, and the audit's first round are rejected evidence. V8 replaces the substring denylist with an independent whole-corpus inventory and exact synthetic mutations for all three counterexamples; it does not change the already accepted unit/replay mechanics.

### V8 enforcement audit — sixth rejected baseline preserved

Round 2 appended to `enforcement-oracle-audit-v7.md` ended exactly `CHANGES REQUIRED`. It confirmed all V8 hashes, both release-to-inventory calls, the three recorded mutations, root-only mode `0500`, and the unchanged unit/replay mechanics. It then executed a stronger installer mutation that assembled `/usr/bin/systemctl` from `sys`+`temctl` and `start` from `sta`+`rt`; the lexical inventory returned `FALSE_GREEN: 7 files scanned`. V8 commit `9c80ec07d30e918e8f9a8d79c4be8bc984afeafe` and registry `75fc5e99` are rejected evidence. V9 removes the root shell authority surface instead of extending the denylist: the whole installer source is an exact frozen non-root package-builder wrapper, so every appended or rewritten command changes bytes and fails.

### V9 enforcement audit — accepted Phase 2 baseline

The final executable-artifact round appended to `enforcement-oracle-audit-v7.md` ended exactly `APPROVED`. It independently matched every V9 hash, reran the selftest and focused A/B RED commands, and changed the prior finding to `FIXED`. The exact constructed `sys`+`temctl`/`sta`+`rt` attack was rejected by whole-file equality; the reviewer found no byte-preserving alternate invocation that gained root activation authority. The reviewed contract also keeps root bootstrap outside checkout shell code, makes every installed control artifact root-only mode `0500`, and preserves whole-corpus detection plus DAC denial for alternate application routes. The audit states `cross-family verdict unavailable`.

### V10 refreeze — delivery separated from activation

V9's authority design is unchanged, but its combined commands are excluded from Phase 3 implementation acceptance. V10 preserves every V9 oracle byte and maps its source-only nodes into the unprivileged package runner while leaving every installed/root/PID1/live-attestation node in a separately recorded activation command. `oracle_v10_support.py`, `v10_delivery_gate.py`, and `test_v10_delivery_oracle.py` are new frozen evidence-boundary code. The delivery artifact has no signature, activation id, nonce, live PID, consumed receipt, or authority-state payload; adding any such field fails its exact schema. A successful package build therefore ends in `activation_ready=false` and cannot be presented to `authorize-commit`.

The V10 targeted audit is a fresh Sol session rather than a continuation of V9. Its required question is narrow: can any package/source GREEN path authorize installation/activation, satisfy or bypass the preserved privileged tests, or claim A/B/C isolation? The exact verdict and artifact identity are recorded in `plan-baselines.json` after completion. `cross-family verdict unavailable`.

V10 round 1 ended `CHANGES REQUIRED` on one verified blocker. The activation split itself, all nine commands, all hashes, V9 preservation, pending-only report fields, real privileged consumer separation, and mandatory host gates passed review. The package inspector nevertheless accepted extra credential/receipt files under alternative names and a relative symlink to such a file because it trusted seven forbidden components plus manifest booleans. Initial freeze `3174b10f209925a29093fe86c89251dd3cb7cbbd` and registry commit `e51e3c660ea81a540dfbb5551dddd96cf32f3197` are rejected implementation evidence and preserved by `oracle-v10-round1-evidence.json` plus audit round 1. The round-1 correction derived an exact allowed inventory from Git-tracked application inputs, fixed cumulative control/unit mappings, and a separate neutral-home frozen-lock runtime build; archive names, types, modes, bytes, and resolved symlink targets had to equal that inventory.

Round 2 confirmed all four round-1 attacks were rejected and every delivery/activation separation claim remained intact, but returned `CHANGES REQUIRED`: an attacker could first make `app/provider-credentials.json` Git-tracked and thereby put the same payload into the derived allowlist. The final executable correction adds the independent typed public-source/content policy on both pre-build inputs and extracted archive bytes, owner-only package storage plus rejection cleanup, and four allowed-inventory content mutations. It also removes the unsound claim that an unprivileged scanner can compare arbitrary source text with root-only provider/service values: both manifest and delivery report must say `protected_secret_comparison="pending_privileged_activation"`, and only the installed privileged gate may complete that comparison before state mutation. This final follow-up is permitted because the executable oracle and report contract changed to close the verified round-2 blocker.

Round 3, the executable-review ceiling, reran the selftest and tracked-source attacks, verified all 18 registered hashes and the unchanged V9 bytes, and returned exact verdict `APPROVED`. It also proved that attempts to claim activation, privileged evidence, isolation, or completed protected-secret comparison are rejected. Its only suggestion is the owner-only residual archive described in the delivery gate above. `cross-family verdict unavailable`; the Sol review is same-family adversarial evidence, not cross-family independence.

## Frozen RED gate

V12 is the only implementation candidate. Its RED commit and immutable hashes are recorded in `oracle-v12-evidence.json` after the refreeze commit. V11 commit `4d5a49aa145772307e9f4333859ddea7a8c6daf5`, its exact `APPROVED` review, and all twelve inherited oracle hashes remain preserved, but `plan-baselines.json` marks it `superseded_for_implementation_runtime_prefix_instability`. V10 and V9 retain their earlier approved seam evidence; V3–v8 remain historical rejection evidence. No production/runtime/config code is present in V12.

The V10 evidence set is:

- green oracle self-test: `oracle-selftest-v10.txt`;
- four unprivileged missing-behavior outputs: `red-delivery-{a,b,c,d}-v10.txt`;
- four deferred host-bound outputs: `red-activation-{a,b,c,d}-v10.txt`;
- machine registry: `oracle-v10-evidence.json` with `activation_ready=false` and `privileged_evidence=pending` for every release;
- fresh audit: `enforcement-oracle-audit-v10.md` (must end exactly `APPROVED` before this plan is PLAN READY).

```text
V10 delivery-oracle selftest → GREEN; mutations of activation/isolation claims, activation-only fields,
authority-state archive members, and escaping symlinks all fail.

Release A/B/C/D delivery commands → RED only for missing production source/package behavior.
They do not read or write root-owned activation state and cannot emit a delivery report while RED.

Release A/B/C/D activation commands → RED/pending on the real absent/incomplete installed evidence.
These are required future RELEASE gates, never Phase 3 implementation AC.
```

### V11 refreeze — canonical internal runtime directory links

The implementation stop at `987b4841` is accepted as a false-premise finding against V10, not as production evidence. Its exact A delivery command reached 12 passing source nodes, then the candidate builder reported `package input is not a regular file: .../lib`; an independent call to V10's reference inventory reported `runtime directory/device link is unsupported: .../reference/lib64`. A fresh task-local reproduction returned `LIB64_TARGET=lib` and `LIB64_TARGET_IS_DIR=True`. The same real `uv sync` passed V11's scanner with `LIB64_ENTRY {'type': 'symlink', 'mode': '0777', 'target': 'lib'}`, 3438 member entries, and 408 independently enumerated real directories.

V11 does not edit V10. `oracle_v11_support.py`, `v11_delivery_gate.py`, and `test_v11_delivery_oracle.py` import the frozen V10 pending-only/content policy and add only the directory-link inventory plus the descriptor-pinned package check required by audit round 1. The reference side scans real directories without following links; resolves every relative hop below the runtime root; requires the final `lstat` node to be a real directory in that independent set; rejects protected top-level runtime state; and requires the stored target to equal the canonical relative path. The archive side accepts the link only against that separate real-directory set and still compares the complete observed file/link mapping byte-for-byte with the reference mapping and candidate manifest. The canonical archive representation contains no explicit directory entries; any such entry is rejected instead of discarded. Package and manifest are each opened once without following the final path, snapshotted anonymously, verified stable through validation, and never reopened for report digests.

The V11 evidence set is:

- green self-test: `oracle-selftest-v11.txt`;
- real-reference positive control: `reference-runtime-v11.txt`;
- four unprivileged missing-behavior outputs: `red-delivery-{a,b,c,d}-v11.txt`;
- the unchanged four deferred V10 host-bound outputs: `red-activation-{a,b,c,d}-v10.txt` (still mandatory pending; not rerun as implementation evidence);
- machine registry: `oracle-v11-evidence.json`, including exact V9/V10 preservation hashes and pending-only report requirements;
- fresh targeted audit: `enforcement-oracle-audit-v11.md`, whose appended round 2 ends exactly `APPROVED`.

```text
V11 delivery-oracle selftest → GREEN; canonical lib64 -> lib passes.
Absolute, escape, dangling, chained escape, cyclic link, special device, protected
state, noncanonical spelling, explicit directory entry, path replacement during
validation, report pathname-reopen, and both candidate/reference mismatch mutations fail.

Release A/B/C/D V11 delivery commands → RED only for missing production behavior.
No RED delivery command emits an authority report or changes production state.

Release A/B/C/D V9/V10 activation commands → mandatory RED/pending until a separately
authorized installed-host window. Delivery GREEN can never satisfy these commands.
```

V11 audit round 1 ended `CHANGES REQUIRED` on two executable false-green paths: explicit tar directory entries were discarded from the observed inventory, and package/manifest paths were reopened between digest, inspection, and delivery-report construction. Freeze `3431c689ec78cada281d7ac432bf3d163b95e89e` and registry `425de74f5e9fc0ec8d58c7bb70ee0b010fbce982` are rejected evidence and remain listed in `plan-baselines.json` with the preserved round-1 artifact.

The corrected executable freeze `4d5a49aa145772307e9f4333859ddea7a8c6daf5` forbids every explicit directory entry; opens package and manifest once with `O_NOFOLLOW`; binds digest and parsing to the same anonymous snapshots; checks pathname identity through validation; and uses only returned validated digests in the report. Each new guard was mutation-tested before the clean 30-test selftest. The resumed targeted audit independently exercised the positive `lib64 -> lib` case, explicit-directory and replacement attacks, pending-only report behavior, and V9/V10 preservation; it classified both prior blockers `FIXED`, found no new issue, and ended exactly `APPROVED`. `cross-family verdict unavailable` remains explicit.

### V12 refreeze — deterministic final runtime prefix

Implementation commits `0904572a` and `2d1aec30` are accepted as a false-premise finding against V11, not as production evidence. After canonical `lib64 -> lib` passed, two fresh frozen-lock runtimes each contained 3438 members and the same 408 real directories but differed in 38 byte entries: five activation assignments, seventeen `#!<scratch>/bin/python` console scripts, and sixteen owning wheel `RECORD` files. The implementation correctly stopped rather than copying the oracle's private scratch path into the candidate. V11 freeze and review remain immutable approved evidence, but V11 commands are excluded from implementation acceptance.

The selected V12 contract normalizes only those measured grammars to `/opt/orchestra/runtimes/<full-source-commit>-<release-a-d>-py312`; recomputes only the `RECORD` rows owning changed console scripts using the packaging specification's SHA-256 urlsafe-base64-without-padding form and decimal byte size; rejects any unclassified reference-prefix occurrence; and requires the candidate's raw archive plus schema-v2 manifest to match the independent normalized inventory and independently derived install prefix. The builder receives the final prefix but never the reference path. Two fresh real builds produced zero normalized differences, zero residual private-prefix entries, and the same normalized content digest `972672ddaa8d84856ff5f9e697490e49a3a18b1afd9bdaa75bff884dc4f54ac1`.

The alternative wheel-input design is not selected. `uv sync --offline --frozen --no-build` against an empty isolated cache exited 1 after creating a partial target; the lock contains 98 registry packages with wheels plus the virtual project, while `uv export` exposes 1475 cross-platform artifact hashes and uv 0.11.28 has no download subcommand. A self-contained wheel path therefore requires a new platform selector/downloader/manifest and would make the privileged manager run a package installer and attest newly materialized bytes. Normalization leaves delivery possibly dependent on lock-hashed downloads/cache but makes activation offline and descriptor-pinned extraction-only; it is smaller, deterministic before privilege, and preserves side-by-side rollback. Official uv documentation confirms `--offline` only disables network and `--no-build` only forbids source builds; the installed-files specification requires `RECORD` paths, hashes, and sizes to describe installed files.[1][2]

The V12 evidence set is:

- green self-test: `oracle-selftest-v12.txt`;
- two-build positive control: `reference-runtime-v12.txt`;
- option comparison: `option-evaluation-v12.txt`;
- five guard mutations: `mutation-v12.txt`;
- four unprivileged missing-behavior outputs: `red-delivery-{a,b,c,d}-v12.txt`;
- all unchanged deferred V10 host-bound outputs remain mandatory pending;
- machine registry: `oracle-v12-evidence.json`;
- fresh targeted audit: `enforcement-oracle-audit-v12.md`, round 1 verdict exactly `APPROVED`.

```text
V12 selftest → GREEN: 15 passed, including two fresh real uv builds.
Raw prefix-dependent differences 38 → normalized differences 0.
Arbitrary prefix, unclassified embedded path, stale RECORD, install-prefix mismatch,
and candidate/manifest common-mode lie mutations each make the targeted oracle RED.

Release A/B/C/D V12 delivery commands → RED only for missing production behavior.
Release A/B/C/D V9/V10 activation commands → mandatory RED/pending.
```

The fresh targeted Sol audit independently reran the 15-test selftest and all four delivery commands; recomputed all 23 registered hashes with zero mismatches; reproduced both fresh 3438-member, 408-directory normalized runtimes; and attacked arbitrary, overlapping, missing, duplicate, stale, and common-mode prefix/`RECORD` cases. It found no blocking findings or suggestions and ended exactly `APPROVED`. Package GREEN remains unable to authorize activation or claim isolation. The audit is same-family adversarial evidence; `cross-family verdict unavailable`.

Sources:

1. uv command reference: `--offline`, `--no-build`, `--find-links`, and `--no-index` semantics — https://docs.astral.sh/uv/reference/cli/
2. PyPA Recording installed projects specification: `RECORD` CSV path/hash/size requirements — https://packaging.python.org/en/latest/specifications/recording-installed-packages/
