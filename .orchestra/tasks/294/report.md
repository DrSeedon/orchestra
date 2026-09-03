# #294 Phase 3 report — private artifact links

## Outcome

The private artifact-link runtime is implemented and the frozen T1–T3 security contract is green.
Generated HTML is copied into a private registry-backed store, redeemed through a fragment-derived
path-scoped grant, served from the exact verified immutable buffer, and confined beneath a trusted
wrapper in a sandboxed child. `/api/files/raw` remains authenticated and Telegram document delivery
remains an explicit fallback.

The feature is **not released**. The server/Chromium gates pass, but the exact Firefox and WebKit
commands stop at the frozen Chromium-only assertion before launching either engine. All Telegram
real-device rows are also unmeasured. The release decision is therefore **KEEP DISABLED**:
`ARTIFACT_PUBLIC_LINKS_ENABLED` must remain unset or `0`; no deploy or restart occurred.

## Commits and changed runtime

- `2c78b013` — frozen T1–T3 oracle commit on this branch.
- `6f76d205` — implementation commit, fast-forwarded unchanged from the reviewed child.
- Runtime files: `app/artifacts.py` (+440), `app/routes/artifacts.py` (+277), `app/auth.py`,
  `app/db.py`, `app/main.py`, `app/mcp_stdio.py`, and `app/tg_bridge.py` (788 additions, 4
  deletions in total).
- This finalization adds only documentation under `docs/tasks/294/`.

Key implementation seams:

- `app/artifacts.py:79` validates fail-closed configuration; `:158` walks source components through
  directory descriptors with `O_NOFOLLOW`; `:224` makes the private snapshot/registry entry;
  `:361` reads and verifies the one returned buffer.
- `app/routes/artifacts.py:119` binds publication to the registered publisher, activates before
  delivery, and compensates every failure/cancellation with revocation and private-copy deletion;
  `:212`, `:222`, and `:254` implement the trusted open/redeem/content chain.
- `app/auth.py:78` retains normal auth unless the exact public method/path and full enabled config
  validate. `app/db.py:99` adds the idempotent registry table/index. `app/main.py:283` performs
  registry-scoped cleanup after DB initialization even while links are disabled.
- `app/mcp_stdio.py:1254` exposes publication without returning the bearer. `app/tg_bridge.py:2652`
  adds preview-disabled text delivery without changing document delivery.

## Frozen-oracle integrity

Each current file was hashed and compared with the same path at `2c78b013`; all eight matched:

| File | SHA-256 |
|---|---|
| `tests/conftest.py` | `e2263de82aaae11f4ab995d48f6a84ecd6d279a20e4c5346554aa75c4f653c4f` |
| `tests/route_surface_snapshot.json` | `d8c2654ff8c26c9b1b4afd9dd7d7e340803545564eebaea132364e785d27f9ba` |
| `tests/test_artifacts.py` | `3c6820d87ebdfd516d68b43df2f43293d5b5c23f9c2b084e2247998b979e0be2` |
| `tests/test_artifacts_browser.py` | `60e0e50ba49d1377b495a89816256ed1dad25e006e4d8e37f6decd07c7d6e74b` |
| `tests/test_auth.py` | `01e8474fe9531d29db4af683b23acc9488d704b13fed72e3423ba46e74c3c63d` |
| `tests/test_db.py` | `d2cf3ef71651ee60742429e2d6c9d64ee57f11a9d3e7573df631f55136efd34c` |
| `tests/test_mcp_stdio.py` | `4f0e88e7a8f40229ed9112a091c511233991b0fa05d4409315f28090db5e81c8` |
| `tests/test_tg_bridge.py` | `9cbb51ed3e1ca7abcf0770290d692d0669c57397aaebbca889cc1a7533ee9c95` |

`git diff --name-status 2c78b013..6f76d205` lists only the seven planned `app/` files; the
implementation did not mutate an oracle, fixture, route snapshot, or test configuration.

## Verification

### Server and fail-safe gates

```text
$ uv run pytest -x -q tests/test_artifacts.py tests/test_auth.py tests/test_db.py tests/test_mcp_stdio.py tests/test_tg_bridge.py tests/test_routes_surface.py
392 passed in 92.45s
```

Focused default-off/raw/fallback evidence:

```text
$ uv run pytest -q \
    tests/test_auth.py::test_t2_invalid_or_disabled_artifact_config_falls_through_auth \
    tests/test_artifacts.py::test_t2_content_head_and_raw_file_route_remain_authenticated \
    tests/test_mcp_stdio.py::test_t2_publish_failure_never_automatically_uses_document_fallback \
    tests/test_tg_bridge.py::test_t2_text_helper_threads_preview_disable_without_changing_document_fallback
4 passed in 15.75s

$ env -u ARTIFACT_PUBLIC_LINKS_ENABLED -u PUBLIC_BASE_URL -u ARTIFACT_LINK_SECRET \
    -u ARTIFACT_DEFAULT_TTL_SECONDS -u ARTIFACT_MAX_TTL_SECONDS -u ARTIFACT_MAX_BYTES \
    uv run python -c '<load config and assert disabled/authenticated open>'
default_enabled=False public_open_requires_auth=True
```

The orchestrator's independent post-merge gate additionally reported `393 passed, 2 deprecation
warnings`; that total includes the Chromium browser gate. The implementation review's recorded
targeted run was `27 passed, 2 warnings in 20.34s`, also including Chromium.

### Automatable T4 attempt

```text
$ ARTIFACT_BROWSER=firefox uv run pytest -x -q tests/test_artifacts_browser.py
1 failed in 5.64s
AssertionError: T3 is the Chromium gate; Firefox/WebKit are the out-of-scope T4 matrix

$ ARTIFACT_BROWSER=webkit uv run pytest -x -q tests/test_artifacts_browser.py
1 failed in 4.46s
AssertionError: T3 is the Chromium gate; Firefox/WebKit are the out-of-scope T4 matrix
```

Both failures occur at `tests/test_artifacts_browser.py:134` before engine launch. They prove the T4
automation is absent; they do not measure Firefox or WebKit behavior. The complete release state is
recorded in [browser-compatibility.md](browser-compatibility.md).

## Security review

High-risk/auth/persistence/shared-delivery changes required Sol review. The preserved three-round
record is [codex-review-impl.md](codex-review-impl.md). Round 1 found a parent-component symlink race,
failed-delivery snapshot retention, and a delivery/activation race. Round 2 confirmed two fixes but
found the remaining delivery race and a `root_fd` leak. Round 3 verified all four fixes and returned:

> **APPROVED — no blocking crash, corruption, security, or race findings in the reviewed surface.**

A cross-family verdict was unavailable during implementation because the Claude weekly pool was
unavailable. No cross-family approval is claimed.

## Plan deviation resolved during review

The approved plan activated a pending row only after Telegram returned explicit delivery success.
The reviewer demonstrated that this creates a user-visible race: a fast recipient can redeem while
the row is pending, lose the fragment, and keep a dead tab. The final reviewed implementation
instead activates immediately before exposing the URL and revokes/deletes the active artifact on
false delivery, exception, or cancellation. The capability remains only in process memory until the
send call, so a crash before exposure does not disclose it. This deviation trades an unreachable
active orphan until expiry for elimination of a delivered-but-not-yet-active link; fail-closed
configuration, expiry, HMAC verification, and cleanup remain enforced.

## Pre-mortem and consumer checks

| Possible next-consumer failure | Observable symptom | Check/evidence |
|---|---|---|
| Public flag accidentally defaults on | Anonymous artifact open bypasses auth | Clean-env probe: `default_enabled=False`, open requires auth |
| Raw route inherits public exemption | Anonymous arbitrary file read | Frozen raw test returns `401`; Gate A green |
| Link failure silently sends the document | Broader file disclosure than caller selected | MCP failure oracle asserts `send_file` was not awaited |
| Preview option breaks document fallback | Existing fallback sent as photo/text or fails | TG oracle confirms `as_document=True` remains a document |
| Implementation weakens its own oracle | Security suite goes green by test mutation | Eight frozen hashes match `2c78b013` byte-for-byte |
| Firefox/WebKit assumed equivalent to Chromium | Unsafe public enablement without evidence | Exact commands fail before launch; release decision is `KEEP DISABLED` |

## Migration, rollback, and remaining gates

- The SQLite migration is additive and idempotent; no live database was migrated because no service
  restart occurred. Existing code that predates #294 ignores the table and private files.
- Rollback remains setting `ARTIFACT_PUBLIC_LINKS_ENABLED=0` followed by an explicitly authorized
  restart. Secret rotation invalidates both fragments and grants. Registry-scoped cleanup remains
  safe while disabled.
- Remaining before enablement: generalize and freeze the Firefox/WebKit browser oracle, make both
  engine commands green with zero skips, and complete every Telegram Desktop/Android/iOS row,
  including secret-rotation rejection for both the old grant and original fragment.
- `.env.example` was not changed because the implementation slice was explicitly app-only. Any
  documentation/config change and any real secret installation require a separate authorized step.

## Breaking changes and operations

No existing authenticated/raw/document contract was intentionally broken. No public flag, live
secret, nginx/systemd setting, deployment, database, or running process was changed; no restart was
performed. `uv.lock` remained unchanged.
