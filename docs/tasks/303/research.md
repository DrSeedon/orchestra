# Task #303 — service-venv authority boundary research

**Status:** Phase 1 research only. No runtime, service, production configuration, or live virtual environment was changed. Scratch experiments were confined to `docs/tasks/303/.probe-uv.*` and removed after each run.

## Question

- **Context:** a personal, multi-project Orchestra instance on one VPS. FastAPI/systemd runs Orchestra while many autonomous agents, MCP subprocesses, background jobs, project tests, and Git worktrees execute concurrently.
- **Change under test:** the smallest enforceable authority boundary that prevents any project-controlled execution from replacing or reading sensitive parts of the live Orchestra runtime while retaining ordinary per-project `uv` workflows.
- **Baseline:** the service and workers share Unix UID `kesha`; workers inherit the service environment; Codex runs with `sandbox="danger-full-access"`; worktrees and `owned_dirs` constrain Git collaboration but not absolute filesystem access.
- **Measurable outcome:** reconstruct the 2026-08-16 incident from ordered records; enumerate every in-repository process-launch seam; reproduce target selection and candidate bypasses in scratch directories; show which legitimate `uv` commands remain viable; and give a recovery sequence that preserves active agent turns.

The acceptance threshold is not enterprise hardening or perfect coverage. A proposal fails if a project-controlled process can still corrupt the service environment, escape through another execution seam, kill active agents during recovery, or inherit service secrets.

## Hypotheses considered

1. **H1 — shared authority caused the incident:** a DND worker selected the service environment through inherited `VIRTUAL_ENV` and later explicit `UV_PROJECT_ENVIRONMENT`; `uv run` synchronized the target to the DND project, replacing Python 3.12 files with a Python 3.11 environment. **Falsifier:** the command did not target `/home/kesha/orchestra/.venv`, `uv --frozen` did not synchronize, or failures began before the replacement.
2. **H2 — environment stripping or a wrapper is sufficient:** removing `VIRTUAL_ENV`/`UV_PROJECT_ENVIRONMENT` at worker launch, or guarding `uv`, prevents cross-project replacement while normal project-local `uv` still works. **Falsifier:** a child can set the variable inline, call `uv` by absolute path, use a symlink, or modify the target without those variables.
3. **H3 — immutable/versioned service runtime alone is sufficient:** a root/service-owned runtime plus direct Python `ExecStart` prevents corruption. **Falsifier:** project-controlled code still executes as an identity able to modify the runtime or obtain root, or another live mutable service path/secret remains accessible.
4. **H4 — a separate non-sudo project-execution identity is the minimum service boundary:** all project-controlled code runs as that identity; the service runtime and state are non-writable, service secrets are non-readable, and only explicit worktree/cache/output roots are writable. **Falsifier:** any project-controlled seam stays under the service identity, any direct service-secret read succeeds, or legitimate project-local `uv` cannot operate within its writable roots.
5. **H5 — one project-execution identity also protects provider credentials:** the model CLI and its arbitrary tool subprocesses can share one UID while provider authentication remains secret. **Falsifier:** the CLI must read a mode-0600 provider store and project-selected code under the same UID can open it.

## Findings

### F1. The incident was a repeated in-place environment replacement, not an import-cache anomaly

**CONFIRMED — tier 1 direct DB, process, and filesystem measurements, corroborated by an independent task-302 reproduction.**

The exact ordered chain was:

1. The incident service had started at `2026-08-16 10:09:47 CEST`. Its live Uvicorn child was Python 3.12.
2. At `12:47:33Z`, DND worker `research-durable-coordinator` ran `uv run --active` while inheriting `VIRTUAL_ENV=/home/kesha/orchestra/.venv` (log `128859`). At `12:47:42Z`, uv reported `Using CPython 3.11.15`, `Removed virtual environment at: /home/kesha/orchestra/.venv`, then created it and installed 97 packages (log `128874`).
3. At `12:48:33Z`, Orchestra worker `feat-runtime-switch` recreated that same path as the Orchestra Python 3.12/74-package environment (log `128932`). This is counter-evidence to a one-shot explanation: two projects were already fighting over one mutable target.
4. The named DND session `research-typed-world-tools` (`c4b3d2b6-95a9-43c6-b622-991dce60d172`, task 9, Codex/Sol) ran `VIRTUAL_ENV=/home/kesha/orchestra/.venv uv run --active --frozen python -V` at `13:19:55Z` (log `130428`). One second later uv again reported removal/recreation and Python 3.11.15 (log `130429`).
5. Other sessions then failed: `ModuleNotFoundError: No module named 'httpcore'` at `13:20:06Z` (log `130434`) and `FileNotFoundError` at `13:20:10Z` (log `130438`).
6. Orchestra briefly restored the 74-package environment at `13:21:01Z` (log `130486`).
7. At `13:21:24.881586Z`, the incident worker issued the exact command:

   ```text
   sha256sum uv.lock; UV_PROJECT_ENVIRONMENT=/home/kesha/orchestra/.venv uv run --frozen pytest -q tests/test_world_repository.py tests/test_world_graph.py tests/test_dice_combat.py tests/test_campaign_views.py; sha256sum uv.lock; git status --short
   ```

   At `13:21:30Z`, uv again removed/created the service environment, installed 97 DND packages, and reported `102 passed in 3.41s` (logs `130504`, `130508`). The unchanged lock digest did not protect the selected environment.
8. Subsequent MCP/TG paths produced `FileNotFoundError` (logs `130609`, `131203`). Task #302 independently reproduced the voice-path failure: the remembered `certifi.where()` pointed into the deleted Python 3.12 tree, and `ssl.create_default_context(cafile=...)` raised `[Errno 2] No such file or directory`.[M1][M2]

At collection time, the running Uvicorn PID `481449` resolved to `/usr/bin/python3.12` and had **191** `(deleted)` mappings. On disk, `/home/kesha/orchestra/.venv` had inode `2097326`, Python `3.11.15`, `version_info = 3.11`, and `prompt = dm-claude`; its Python 3.12 site-packages and old CA bundle no longer existed. Thirty Python 3.12 MCP processes each had 12 deleted mappings, one Python 3.11 MCP had 12, and three Python 3.11 MCPs had none.[M1]

Mechanistically, native modules already mapped into memory can continue, but later imports and data-file opens traverse paths that no longer exist. HTTPX 0.28.1 calls `ssl.create_default_context(cafile=certifi.where())`; the scratch reproduction using a removed CA path produced the same `FileNotFoundError`. Thus the missing `httpcore` import and missing certificate bundle are two consequences of the same directory replacement, not separate root causes.[M1][M2]

### F2. Both uv target selectors are destructive under these commands; `--frozen` is not `--no-sync`

**CONFIRMED — tier 1 scratch measurements plus tier 2 uv primary documentation.**

Uv documents that an absolute `UV_PROJECT_ENVIRONMENT` is used exactly as given and warns that multiple projects may overwrite the same environment. It also documents that `--active` selects `VIRTUAL_ENV`.[U1] Uv's synchronization documentation states that `uv run` locks and synchronizes by default; `--frozen` skips checking whether the lock is up to date, while `--no-sync` is the option that skips synchronization.[U2]

The scratch harness created project A (`>=3.12,<3.13`, prompt `probe-a`) and project B (`>=3.11,<3.12`, prompt `probe-b`) and measured:

- **P1:** absolute `UV_PROJECT_ENVIRONMENT` plus `uv run --frozen` changed the shared target from `version_info=3.12.3;prompt=probe-a` to `version_info=3.11;prompt=probe-b`; uv logged one removal.
- **P2:** inherited `VIRTUAL_ENV` plus `uv run --active --frozen` made the same replacement.
- **P5:** `--no-sync` preserved the target, but ran Python **3.12** for project B, whose declared constraint excludes 3.12. It avoids mutation by accepting a potentially incorrect runtime, so it is not a safe universal policy.
- **P6:** `uv venv --clear --python 3.11 PATH` replaced the target without either environment variable. Uv also officially permits direct environment selection using `uv pip --python`.[U3]

### F3. Environment stripping preserves normal project-local uv, but every user-space guard tested is bypassable

**CONFIRMED for the tested mechanisms — tier 1 scratch measurements.**

- **P3 compatibility:** after unsetting `VIRTUAL_ENV` and `UV_PROJECT_ENVIRONMENT`, ordinary project-B `uv run --frozen` exited 0, created `project-b/.venv`, and left the shared project-A environment byte-for-byte at the same fingerprint.
- **P4 inline bypass:** stripping both variables in the parent did not prevent a child shell from assigning `UV_PROJECT_ENVIRONMENT=<shared-target>` and replacing it.
- **P7 alias bypass:** selecting a symlink to the shared target replaced the real directory, defeating literal-path checks.
- **P8 same-UID permissions:** removing write bits first caused exit 2; because the process owned the path, it restored write permission and then replaced the environment with exit 0.
- **P9 wrapper bypass:** a shell function named `uv` returned 77, but `/home/kesha/.local/bin/uv` executed with exit 0. Equivalent bypasses include Python filesystem APIs and another package installer.

H2 is therefore **REFUTED** as an authority boundary. Environment stripping and a canonicalizing wrapper remain useful error-prevention and diagnostics, but enforcement must be below the command language.

### F4. Current worktree, trust, sandbox, ownership, and systemd controls do not enforce the boundary

**CONFIRMED — tier 1 live configuration and source measurements.**

- `owned_dirs` is parsed and checked only for overlap with another live session, then injected into the prompt; it does not change filesystem permissions (`app/manager.py:779-825`). The incident worker's owned directory was only `docs/tasks/377/phase3/r2`, yet it wrote an absolute path outside both its worktree and repository.[C1][M1]
- Git worktrees isolate branch state, not Unix path access.
- Codex is launched with `approvalPolicy="never"` and `sandbox="danger-full-access"` (`app/backend_codex.py:527-566`). Trust controls whether project configuration is consumed; it is not OS isolation.[C2]
- Claude's approval callback permits every tool except a short blocked-name set. Its optional `PreToolUse` hook detects background flags, recursive rm, chmod 777, and curl-to-shell; it neither recognizes uv target selection nor provides a filesystem boundary (`app/backend_claude.py:153-159,312-415`).[C3]
- OpenCode explicitly allows Bash and external-directory access; its optional `ORCHESTRA_AGENT_UID` switch is inactive on this host (`app/backend_opencode.py:169-220`). Codex and Grok have no equivalent UID switch in their spawn paths.[C4]
- The live unit has `NoNewPrivileges=no`, `ProtectSystem=no`, `ProtectHome=no`, `PrivateMounts=no`, `RestrictNamespaces=no`, and no read-only/inaccessible path list. `systemd-analyze security` scored it `9.2 UNSAFE` (a coarse exposure indicator, not proof of this specific flaw).[M1]
- Service and workers are UID 1001 (`kesha`); the repo runtime and `.env` are `kesha:kesha`; `.env` mode is 0644. The account is in `sudo`, and `sudo -n true` exited 0 under policy `(ALL) NOPASSWD: ALL`. A `setpriv --no-new-privs sudo -n true` probe exited 1, so NNP blocks that direct elevation path; however, systemd explicitly notes NNP affects descendants and not processes invoked through `at`, `crontab`, `systemd-run`, or arbitrary IPC.[S1][M1]

These facts refute H3 under the current identity: merely chmodding or mount-hiding the runtime while the same passwordless-sudo owner controls execution does not establish a complete authority boundary.

### F5. Every project-controlled execution seam must cross the same identity/environment boundary

**CONFIRMED for the inspected repository seams — tier 2 primary source inspection; completeness remains LIKELY rather than absolute because dynamically configured external programs can add paths.**

The repository contains these launch/inheritance seams:

1. **Codex CLI:** spawns with a caller-built environment; `_build_env()` starts from `dict(os.environ)` and adds `_mcp_env` (`app/backend_codex.py:527-533,1887-1895`).[C2]
2. **Grok CLI:** starts from `dict(os.environ)`, removes proxy variables, then adds `_mcp_env`; it runs `--always-approve` (`app/backend_grok.py:392-407,1299-1315`).[C5]
3. **Claude CLI/SDK:** options merge the service environment with supplied MCP options; the optional SDK `user=` applies only when `ORCHESTRA_AGENT_UID` is configured (`app/backend_claude.py:585-613`).[C3]
4. **OpenCode daemon:** starts from the service environment and optionally prefixes `gosu` only when `ORCHESTRA_AGENT_UID` is configured (`app/backend_opencode.py:192-220`).[C4]
5. **MCP configuration:** for Codex, environment entries from all scope/project MCP servers are flattened into one `_mcp_env`, then promoted into the entire CLI environment (`app/runtime_registry.py:230-246`). A repository `.mcp.json` can therefore inject `UV_PROJECT_ENVIRONMENT`, not merely configure its own server. Grok performs a narrower flatten from custom context servers but still promotes it globally (`app/runtime_registry.py:254-287`).[C6]
6. **Project MCP servers:** the CLI starts configured external programs; those programs inherit whatever environment the backend supplies and can execute arbitrary code.
7. **Agent-exposed background jobs:** `bg_create` exposes `run`, `command`, `cron_command`, and `ssh`. `bg_jobs.py` executes local command strings through a shell and launches a local SSH client with an agent-selected host/remote command from the long-lived service (`app/mcp_stdio.py:1986-2033`; `app/bg_jobs.py:698-711,794-805,823-873`). A local UID boundary constrains the SSH client and its local credential reads; remote-host authority needs its own credential/policy boundary.[C7]
8. **Acceptance commands:** operator-registered commands execute arbitrary argv in the worktree without an explicit environment, hence inherit the service process environment (`app/acceptance.py:27-66`).[C8]
9. **Merge/test gate:** executes project pytest under `sys.executable` with `os.environ.copy()`. Imported project test and fixture code has the service process's identity and absolute-path authority (`app/merge_test_gate.py:97-118`).[C9]
10. **Children of any of the above:** shell inline assignments, scripts, test helpers, compilers/build tools, `uv`, `pip`, and filesystem APIs inherit the executing identity even if the immediate launcher strips two variables.

The worker environment measurement confirms this is not theoretical: the incident Codex process inherited `VIRTUAL_ENV=/home/kesha/orchestra/.venv`, a PATH prefixed by its `bin`, and 49 variables. Sensitive **names** present were `DASHBOARD_PASSWORD`, `DEEPGRAM_API_KEY`, `INTERNAL_TOKEN`, and `TG_BRIDGE_TOKEN`; values were not recorded.[M1] Direct reads are an independent exposure: the live service `.env` and this worker's copied `.env` were mode 0644; the incident DND worktree's `.env` was 0664. Source explicitly classifies `.env` as a secret-bearing file copied into worktrees (`app/workspace.py:26-29`).[C12][M1] Systemd's documentation warns that environment variables propagate down the process tree and are unsuitable for secrets.[S2]

### F6. One non-sudo project UID is the minimum service-integrity boundary; the full secret criterion requires a separate credential domain

**LIKELY — supported by POSIX/systemd enforcement semantics, the seam inventory, and bypass experiments; implementation is not yet tested because Phase 1 forbids runtime/config changes.**

The minimum service-runtime boundary is:

1. Run **every arbitrary project-code path** enumerated in F5 as a dedicated, non-sudo project-execution identity. This includes project MCP programs, shell/tool children, agent-created background/cron/SSH commands, acceptance commands that run project code, and merge/test subprocesses. A partial switch is a bypass, not incremental enforcement.
2. Make the live Orchestra runtime and mutable service state owned by root or a service identity that the project UID cannot write. Make service secrets, `.env`, sensitive configuration, database/transcripts, and service credential stores **unreadable and unwritable** by the project UID: service-owned mode 0600, ACLs, or an equivalent inaccessible-path rule. Verify direct `open()` denial as the project identity. Give that identity access only to source it legitimately needs plus its worktree and explicitly named cache/artifact directories. Give it no sudo and no writable control socket/service unit that can act for the service identity.
3. Build service environments side-by-side as versioned, immutable directories. Start Uvicorn with `<runtime>/bin/python -m uvicorn`, not `uv run`. A root-controlled `current` symlink selects a verified version; agents never synchronize the live target in place.
4. Construct worker/tool environments from an allowlist. At minimum remove `VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT`, `CONDA_PREFIX`, service PATH prefixes, and service-only credentials. Do not flatten arbitrary MCP `env` keys into the CLI. Pass only each MCP server's own allowlisted variables to that server. Replace the broad internal/service token with a scoped broker/token where practical. Stop copying the Orchestra service `.env` into worktrees; project credentials, when unavoidable, must be a project-scoped subset rather than service-wide authority.
5. Add a canonicalizing uv/target guard only for a clear error message. It should reject targets outside the current worktree or a named development environment, but it is defence in depth because P4/P6/P7/P9 bypass it.

Why this is the smallest *service-integrity* boundary: a separate project UID applies once at each project-code creation seam and the kernel checks every later filesystem syscall, independent of command spelling or symlinks. Root/service ownership makes the target non-writable to that UID. Environment stripping alone is bypassed by P4; wrappers by P9; chmod by P8; `--no-sync` runs the wrong environment in P5; a mount namespace alone is broader operationally and can be escaped through an external same-UID execution path unless every such path is also closed. Systemd documents both read-only path controls and their namespace/privilege limitations.[S3]

The second review exposed a necessary third authority domain. Codex and Claude authentication files are both mode 0600 owned by the current UID 1001. Managed Codex homes symlink the common `auth.json`, and Grok uses the same symlink design when its user auth exists (`app/backend_codex.py:1836-1870`; `app/backend_grok.py:132-155`).[C13][M1] The model CLIs must read those provider stores to start or refresh. Any arbitrary shell/read/tool code under that same UID can also read them; mode 0600 cannot distinguish two processes with one UID. Current Codex is `danger-full-access`, Claude auto-approves almost all tools, Grok always approves, and OpenCode permits Bash/external directories.[C2][C3][C4][C5]

H5 is therefore **REFUTED**. The full boundary has three domains:

1. **Service identity:** owns the immutable runtime, database, service configuration, and service secrets; neither controller nor project execution may read service secrets or write service state.
2. **Credential-bearing controller/broker:** may read only the provider authentication required to start/refresh a model runtime; it must not expose reusable credentials in argv, environment, worktrees, MCP config, logs, or project-readable files.
3. **Uncredentialed project execution:** every project-selected file, process, network, MCP, test, background, and SSH operation runs here; it may write the worktree/cache but direct reads of both service and provider credentials must return `EACCES`.

For a backend whose CLI combines the credential-bearing controller with in-process file/shell tools, a second UID label alone is insufficient. It must either (a) put every project-selected operation behind a mandatory per-tool UID/mount/sandbox transition that hides provider stores, or (b) broker provider authentication outside the project-exposed CLI so no reusable credential is mounted there. The production-shaped acceptance is two-sided: provider startup, one authenticated model turn, and token refresh succeed in the controller domain; an adversarial Read/Bash/test/MCP/background probe in the project domain cannot read the provider store. If a backend cannot prove both, it remains outside the claimed secret-confidentiality boundary.

H4 is supported but compatibility remains **LIKELY**, not confirmed. P3 proves only that a dependency-free project-local `uv run --frozen` works when activation variables are stripped, provided the worktree/cache are writable. It does not cover a representative dependency set, native build subprocess, uv cache/home, or migration of existing `kesha`-owned worktrees to a new UID. Before implementation approval, run a real project `uv sync`, `uv run`, and focused test under the proposed UID, with explicit writable worktree/cache/home, and record child UIDs. The measured compatibility cost is that Orchestra's current development habit must change: before the incident window, Orchestra-scope sessions issued **59** `uv run --active` commands across two sessions, none with `--no-sync`; DND issued three across three sessions, two sync-capable and one `--no-sync`.[M1] Those commands must target a per-worktree `.venv` or a distinct mutable development/test environment, never the live service runtime.

The environment allowlist is not redundant with identity separation. UID/DAC prevents service-runtime corruption; confidentiality requires both minimal inheritance **and** filesystem denial for direct reads. The project-domain acceptance check must prove: worktree/cache writes succeed; service canary writes fail; direct reads of service `.env`, sensitive configuration, database/transcripts, service credentials, and provider authentication stores fail with `EACCES`; and service/provider credential names and values are absent from `environ`, argv, MCP configs, logs, and copied worktree files. The controller-domain check must independently prove provider startup/authentication/refresh. Because the task defines secret exposure as blocking, these are required boundary conditions, not later hardening.

### F7. Safe recovery requires side-by-side construction and Orchestra's drain/handoff path

**LIKELY — source-backed and locally rehearsed build, but no live restart was authorized or performed.**

The current environment must not be “repaired” in place: 34 logical CLIs and many MCP processes were live at measurement time, and old processes still referenced deleted inodes.[M1] A scratch side-by-side build using the current frozen lock and Python 3.12 exited 0; required imports and the 236095-byte certifi bundle were present.[M1]

The safe sequence is documented in [recovery-runbook.md](recovery-runbook.md): build and verify a versioned runtime; install it with service/root ownership; configure direct Python execution; then use the **authorized application restart endpoint**. The application path closes admission, drains mutating calls, waits for active Claude/Grok turns, hands active Codex pipes to systemd, and only then exits.[C10] Manual `systemctl restart` bypasses that preflight.[M3]

One edge is explicit: Codex CLIs that survive handoff retain their old MCP subprocesses. The adoption path marks tools stale and respawns the CLI/MCP pair only at the next turn boundary, because doing so mid-turn would kill the protected turn (`app/session.py:917-942`).[C11] Recovery must therefore let active turns finish, verify next-boundary refresh, and remove the old environment only after `/proc` shows zero references.

## Candidate decision table

| Candidate | Stops named command | Stops direct/alias bypass | Preserves normal project uv | Covers secrets | Decision |
|---|---:|---:|---:|---:|---|
| Strip `VIRTUAL_ENV`/`UV_PROJECT_ENVIRONMENT` | Yes, if command unchanged | No (P4, P6) | Yes (P3) | Partly | Adopt as hygiene, not boundary |
| Force `--no-sync` | Yes | No | No: P5 used incompatible Python | No | Reject as general policy |
| uv/PATH wrapper | Often | No (P9; other programs) | Usually | No | Optional UX guard |
| chmod/read-only mode, same UID | Initially | No (P8; sudo) | N/A | No | Reject |
| Mount namespace only | Yes inside namespace | Not against external same-UID path | With bind exceptions | Partly | Optional defence in depth |
| Root-owned immutable runtime only, current worker identity | Usually | Passwordless sudo defeats it | Yes | No | Incomplete on this host |
| Dedicated non-sudo project UID + root/service-owned versioned runtime | Yes | Yes, if every project-code seam crosses it | Likely; real-project UID probe required | Service secrets only; provider auth remains exposed to same-UID tools | **Core service-integrity minimum** |
| Service UID + credential controller/broker + uncredentialed project domain | Yes | Yes | Likely; real-project UID probe required | Yes if dual startup/denial probes pass | **Recommended full boundary** |

The full machine-oriented comparison, including regressions and recovery risks, is [attack-regression-matrix.csv](attack-regression-matrix.csv). Raw structured measurements are in [evidence.json](evidence.json); the reproducible scratch experiment is [probe_uv_boundary.sh](probe_uv_boundary.sh).

## Counter-evidence, uncertainty, and limitations

- `--no-sync` genuinely prevented the measured replacement. It is rejected only as a general boundary because it is optional, directly bypassable, and P5 ran an interpreter outside the project's declared constraint.
- NNP genuinely stopped the direct passwordless-sudo probe. It is not called useless; it is insufficient alone because the same UID still owns service paths and upstream documents external-invocation exceptions.[S1]
- A mount namespace can make paths read-only or inaccessible for descendants and is valuable defence in depth.[S3] It was not live-tested because that would change production execution policy. It is not the smallest boundary for this topology because every escape-capable execution path still needs classification, whereas UID/DAC follows the syscall across ordinary descendants.
- A dedicated UID is not magic. Any missed launcher, writable privileged socket, setuid helper, world/group-writable service path, or agent-writable unit/config reopens the boundary. Phase 2 must enumerate ownership and launcher tests before implementation.
- Existing worktree `.env` copying is direct counter-evidence to the first draft's confidentiality claim. Merely changing the process environment would leave secrets readable from disk; the boundary now requires direct-read denial and removal of service `.env` copies.
- A single agent UID does not protect provider authentication from its own arbitrary tool subprocesses. The three-domain design is an evidence-derived expansion, not enterprise ceremony; without it the stated secret-exposure criterion is false. Backend-specific feasibility is still UNCERTAIN until startup/refresh and adversarial direct-read probes run.
- The source seam inventory covers the inspected Orchestra repository at commit `b0b72d65...`, plus the loaded restart revision comparison. It cannot prove absence of out-of-repository operator scripts or future plugins; the enforcement test must therefore be based on observed UID and denied filesystem access, not a frozen list of command names.
- The incident's exact command and failure ordering are confirmed. The initial intent behind explicitly choosing the service path is not inferable from logs and is irrelevant to the boundary: accidental and adversarial commands have the same authority.
- The cross-family Opus review requested by the canonical review route was unavailable because the Anthropic weekly pool measured 100% used (reset `2026-08-18T07:00:00Z`). A fresh Sol adversarial review is recorded separately; it is not mislabelled as cross-family independence.

## Affected files and Phase-2 risk map

No code change is proposed in this phase. A future plan will likely touch:

- backend environment/identity and credential launchers: `app/backend_codex.py`, `app/backend_claude.py`, `app/backend_grok.py`, `app/backend_opencode.py`, `app/runtime_registry.py`;
- secondary execution: `app/bg_jobs.py`, `app/acceptance.py`, `app/merge_test_gate.py`, MCP-server launch configuration;
- deployment/unit/runtime construction outside the repository or in deployment assets;
- tests that assert controller/project child identities, provider startup/authentication/refresh, environment/argv/config allowlists, per-server env scoping, denied project-domain reads and writes to service/provider canary paths, representative dependency-bearing project-local `uv sync/run/test`, and drain/handoff continuity.

Highest risks are: leaving one same-UID project-code seam; letting a credential-bearing CLI execute an in-process tool outside the project sandbox; breaking provider login/refresh; depriving legitimate integrations of required scoped variables; making worktree/cache paths unwritable; applying the UID switch after an SDK has already spawned children; assuming a read-only mount covers external schedulers; restarting before active-turn handoff; and deleting the old runtime before stale MCP processes refresh.

## Verdict

The causal hypothesis H1 is **CONFIRMED**. `uv run --frozen` synchronized exactly the absolute/inherited target it was given; repeated DND and Orchestra commands alternated Python 3.11 and 3.12 at the live path. Running processes retained deleted mappings, and later imports/CA-bundle opens failed.

H2 and the current form of H3 are **REFUTED**. Prompt ownership, worktrees, Codex trust, danger-full-access, variable stripping, wrappers, `--no-sync`, chmod, and current systemd settings do not constitute an enforceable authority boundary.

For the incident's service-environment corruption, the smallest enforceable boundary is **one dedicated non-sudo project-execution identity applied to every arbitrary project-code seam, with a service/root-owned versioned runtime that is never synchronized in place**. For the task's full secret-exposure criterion, one agent UID is insufficient: the minimum becomes **service identity + credential-bearing controller/broker + uncredentialed project-execution domain**, with dual positive authentication and negative direct-read probes. Service `.env` copies must leave worktrees, and project environments must be constructed from scoped allowlists. Keep target guards and systemd namespace restrictions as defence in depth. Recover by building side-by-side and using Orchestra's authorized drain/handoff restart; never overwrite the current environment or manually restart while active work remains.

## Sources

### Direct measurements (tier 1)

[M1] `docs/tasks/303/evidence.json` and `docs/tasks/303/probe_uv_boundary.sh`: SQLite log IDs/timestamps, `/proc` mappings/environment, filesystem metadata, systemd properties, scratch P1–P9 results, command-frequency counts, and side-by-side recovery build. Collected 2026-08-16.

[M2] `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-voice-upload/docs/tasks/302/report.md`: independently collected incident voice-path evidence and SSL/certifi reproduction. Read 2026-08-16; external to this worktree and not modified.

[M3] `docs/tasks/230/report.md:109-128`: measured application restart/handoff and manual-systemd bypass behavior.

### Repository primary sources (tier 2)

[C1] `app/manager.py:779-825`, `owned_dirs` overlap validation and prompt injection.

[C2] `app/backend_codex.py:527-566,1887-1895`, subprocess environment and danger-full-access/never-approve configuration.

[C3] `app/backend_claude.py:153-159,312-415,585-613`, auto-approval, Bash hook scope, environment and optional SDK user.

[C4] `app/backend_opencode.py:169-220`, broad permissions, inherited environment, optional `gosu` identity switch.

[C5] `app/backend_grok.py:392-407,1299-1315`, always-approve spawn and inherited/augmented environment.

[C6] `app/runtime_registry.py:230-287`, project/scope MCP environment flattening into CLI environments.

[C7] `app/mcp_stdio.py:1986-2033`; `app/bg_jobs.py:698-711,794-805,851-873`, agent-exposed command/cron/run execution.

[C8] `app/acceptance.py:27-66`, inherited-environment operator command runner.

[C9] `app/merge_test_gate.py:97-118`, project pytest via service interpreter and copied environment.

[C10] `app/routes/system.py:1748-1996`; `app/session.py:2483-2725`, application restart admission/drain/handoff.

[C11] `app/session.py:917-942`, stale adopted backend refresh at a turn boundary.

[C12] `app/workspace.py:26-29,449-458`, `.env` identified as secret-bearing and copied/injected into worktrees.

[C13] `app/backend_codex.py:1836-1870`; `app/backend_grok.py:132-155`, provider-authentication symlinks into managed per-session homes.

### External primary sources (tier 2; opened 2026-08-16)

[U1] uv documentation, [Project environment path and active environments](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path), including absolute-path and overwrite warning.

[U2] uv documentation, [Automatic lock and sync](https://docs.astral.sh/uv/concepts/projects/sync/#automatic-lock-and-sync), distinction among default sync, `--frozen`, and `--no-sync`.

[U3] uv documentation, [Using Python environments](https://docs.astral.sh/uv/pip/environments/), `VIRTUAL_ENV` and `uv pip --python` target selection.

[S1] systemd upstream manual, [`NoNewPrivileges=`](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml#L820-L836), descendant scope and external-invocation caveat.

[S2] systemd upstream manual, [environment variable security and propagation](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml#L2906-L2912) and [`UnsetEnvironment=`](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml#L2995-L3007).

[S3] systemd upstream manual, [`ReadOnlyPaths=`/`InaccessiblePaths=`](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml#L1611-L1660) and [filesystem namespace behavior](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml#L2544-L2569).
