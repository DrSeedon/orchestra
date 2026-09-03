# #294 — secure external HTML artifact links: Phase 2 implementation plan

Basis: the corrected contract in [research.md](research.md). The final research review artifact
honestly says `CHANGES REQUIRED` because its second and final prose round found an auth-test wording
contradiction; that exact line was corrected afterward. The three substantive security findings
(revoke-all, verify/serve atomicity, and top-level isolation) were confirmed fixed by that review.

This phase changes documentation only. It does not modify runtime, tests, configuration, nginx, or
the live service.

## Outcome and release boundary

The implementation adds an explicit MCP operation that securely snapshots one generated HTML file,
stores it outside the webroot, registers a short-lived opaque capability, and sends the fragment URL
to the caller's Telegram topic without a link preview. Opening the link redeems the fragment into a
narrow HttpOnly grant. A fixed trusted top-level page then embeds the verified HTML bytes only in a
sandboxed child frame.

The feature is **off by default**. Merge is allowed after the server-side security suite and the
Chromium gate are green, but deployment remains on Telegram document fallback. Operators may set
`ARTIFACT_PUBLIC_LINKS_ENABLED=1` only after Firefox, WebKit, Telegram Desktop, Android, and iOS have
all supplied the compatibility evidence defined in Gate C. No implementation step edits the live
`.env`, nginx, or systemd configuration.

The existing `/api/files/raw?path=...` route, dashboard preview, dashboard session cookie, upload
routes, and `send_file(..., as_document=True)` behavior remain unchanged.

## Non-negotiable invariants

1. Anonymous requests never provide or reach a filesystem source path. The public contract contains
   only a fixed-format locator.
2. `/api/files/raw` remains protected by normal dashboard/internal authentication. No fallback,
   redirect, or compatibility branch points a public link at it.
3. The caller's MCP identity is bound by `X-Orchestra-Session-Id` plus
   `X-Orchestra-Mcp-Proof`; request JSON `sender`/`scope` never selects an allowed root.
4. Source authorization walks from server-registered `cwd`/`worktree_path` directory descriptors,
   rejecting `..`, symlinks in any component, non-regular files, invalid UTF-8, and files over
   10 MiB. Bytes are read from the authorized descriptor exactly once.
5. Stored artifacts live under a private state directory, use server-generated names and private
   modes, and never retain an absolute source path.
6. The database stores only a domain-separated HMAC verifier, never the capability. Rotating
   `ARTIFACT_LINK_SECRET` invalidates old fragment redemption and old grant cookies.
7. Serving reads at most 10 MiB from one `O_NOFOLLOW` descriptor into immutable `bytes`, verifies
   length and SHA-256, closes the descriptor, and returns that exact buffer. It never verifies one
   object and streams another path/fd afterward.
8. Active artifact HTML is never a top-level document. The trusted wrapper owns the top-level page;
   only its `<iframe sandbox="allow-scripts">` receives artifact bytes.
9. Conditional public `GET /api/artifacts/open/<locator>/content` requires both a valid
   artifact-path grant and exact `Sec-Fetch-Dest: iframe`. A dashboard cookie, HEAD, another method,
   or direct top-level navigation cannot authorize content.
10. Public auth exemptions exist only for exact open/redeem/content method/path shapes and only when
    the feature flag, HTTPS public origin, and secret all validate. Disabled or invalid
    configuration falls through normal `/api` auth before routing.
11. Capability material exists only in process memory and the Telegram message. It is absent from
    route responses, database values, filenames, application/proxy logs, exception text, cookies,
    and HTTP request targets.
12. A new row is `pending` and therefore non-public until Telegram returns explicit success and the
    server atomically activates it. Every exception, cancellation, crash, or activation failure
    before that commit leaves a dead capability. Link failure never silently broadens into file
    publication: Telegram document fallback is an explicit `send_file(..., as_document=True)`
    choice, and rejected/failed link publication does not automatically resend the source through
    the broader legacy path.

## Exact configuration contract

`app/artifacts.py:load_artifact_config()` reads configuration on demand; it must not cache import-time
environment before `lifespan()` calls `load_dotenv()`.

| Variable | Contract |
|---|---|
| `ARTIFACT_PUBLIC_LINKS_ENABLED` | Only literal `1` enables; absent/other values disable |
| `PUBLIC_BASE_URL` | Exact HTTPS origin only: scheme `https`, hostname present, optional port, path empty or `/`, no userinfo/query/fragment; normalized without trailing slash |
| `ARTIFACT_LINK_SECRET` | Unpadded URL-safe base64 encoding that decodes to at least 32 random bytes (for example `secrets.token_urlsafe(32)`); missing/invalid disables all public exemptions and publication |
| `ARTIFACT_DEFAULT_TTL_SECONDS` | Default `86400`; integer `1..604800` |
| `ARTIFACT_MAX_TTL_SECONDS` | Default and hard ceiling `604800`; never above 7 days |
| `ARTIFACT_MAX_BYTES` | Default and hard ceiling `10485760` (10 MiB) |

The table defaults are product starting values from research, not compatibility evidence. Tests set
every variable explicitly; `tests/conftest.py` clears artifact variables so a live service env cannot
change test outcomes.

The public locator is `secrets.token_urlsafe(16)` (at least 128 random bits). The capability is
`secrets.token_urlsafe(32)` (256 random bits). The issued URL is:

```text
<PUBLIC_BASE_URL>/api/artifacts/open/<locator>#<capability>
```

The database verifier is:

```text
HMAC-SHA-256(key=ARTIFACT_LINK_SECRET,
            message=b"artifact-cap-v1\0" + capability_ascii)
```

The grant cookie is named `orchestra_artifact_grant` and contains a version, locator, absolute
expiry, and a domain-separated HMAC over those fields. It contains no capability and is set with:

```text
Secure; HttpOnly; SameSite=Strict; Path=/api/artifacts/open/<locator>; Max-Age<=link expiry
```

Grant verification always re-reads registry state/expiry and accepts only `active`. The signing domain is
`artifact-grant-v1\0`, distinct from the capability-verifier domain.

## Schema and storage migration

`app/db.py:init_db()` adds the table and index idempotently in its existing schema transaction:

```text
artifacts(
  id                    TEXT PRIMARY KEY,
  capability_verifier   BLOB NOT NULL CHECK(length(capability_verifier) = 32),
  stored_name            TEXT NOT NULL UNIQUE,
  content_sha256         BLOB NOT NULL CHECK(length(content_sha256) = 32),
  display_name           TEXT NOT NULL,
  publisher_session_id   TEXT NOT NULL,
  publisher_name         TEXT NOT NULL,
  scope                  TEXT NOT NULL,
  size_bytes             INTEGER NOT NULL CHECK(size_bytes > 0 AND size_bytes <= 10485760),
  created_at             INTEGER NOT NULL,
  expires_at             INTEGER NOT NULL CHECK(expires_at > created_at),
  state                  TEXT NOT NULL CHECK(state IN ('pending', 'active', 'revoked')),
  activated_at           INTEGER,
  revoked_at             INTEGER,
  last_opened_at         INTEGER,
  open_count             INTEGER NOT NULL DEFAULT 0 CHECK(open_count >= 0),
  CHECK((state = 'pending' AND activated_at IS NULL AND revoked_at IS NULL)
     OR (state = 'active' AND activated_at IS NOT NULL AND revoked_at IS NULL)
     OR (state = 'revoked' AND revoked_at IS NOT NULL))
)
CREATE INDEX idx_artifacts_expiry ON artifacts(state, expires_at)
```

There is deliberately no foreign key to `sessions`: archiving/deleting a publisher must not mutate
an issued artifact row. There is no source-path column and no grant table.

`app/artifacts.py` resolves the private store as one absolute path:

1. `$STATE_DIRECTORY/artifacts` when `STATE_DIRECTORY` contains exactly one path;
2. otherwise `$XDG_STATE_HOME/orchestra/artifacts`;
3. otherwise `~/.local/state/orchestra/artifacts`.

It opens every directory component from `/` with `O_DIRECTORY|O_NOFOLLOW`, creates missing
components as `0700`, verifies directory identity, writes `<locator>.html` as `0600` through an
exclusive temporary file, fsyncs file and directory, and atomically renames. A database insert
failure removes the just-created private copy; a process crash before the DB insert can leave only
an unaddressable orphan.

Startup cleanup runs after `init_db()` even when public links are disabled or the public
origin/secret is invalid. It depends only on the private-store resolver and registry rows; it never
creates an auth exemption or validates a public request. It deletes files for expired rows,
including abandoned `pending` rows, and then deletes those rows. Revoked rows remain until expiry so
the registry retains the deny decision. A missing file is safe and the row can be removed; an empty
registry returns without opening or sweeping the directory. Cleanup opens only server-generated
`stored_name` values from selected rows and never enumerates/deletes an unregistered entry.
Open-count telemetry is best effort and never suppresses an already verified response.

## HTTP and browser contract

### Authenticated/internal operations

- `POST /api/artifacts/publish` accepts `{path, caption, ttl_seconds}`. It requires the shared
  internal bearer **and** a valid per-session MCP proof. The session row comes from the header-bound
  session ID; its registered `cwd`/`worktree_path`, name, and scope are authoritative.
- `POST /api/artifacts/{locator}/revoke` accepts a dashboard operator session, or the original
  publisher's valid internal bearer + MCP proof. Other worker sessions receive `403`.
- Publish commits the private copy and row first with `state='pending'`. Public redeem, grant, open,
  and content checks accept only `state='active'`; possession of a pending locator/capability grants
  nothing. The route then constructs the fragment URL only in memory and sends it to the
  server-derived Telegram topic with previews disabled.
- Telegram delivery is guarded by a `try/finally` state machine. Only an explicit successful
  Telegram result may perform one compare-and-set transaction from `pending` to `active`; no await
  or cancellation point exists between that commit and returning safe metadata
  `{ok, artifact_id, expires_at, message_id}`. The response never returns the URL.
- Every other exit—including a false/non-success result, ordinary exception, `CancelledError`
  during or after dispatch, database activation failure, or process death before activation—leaves
  the row non-active. The `finally` path shields a best-effort compare-and-set from `pending` to
  `revoked` and deletes the private file when safe, but correctness does not depend on that cleanup:
  a crash-abandoned `pending` row is inert and expiry cleanup removes it later. Return/raise only a
  bearer-free instruction to use the explicit document fallback; never include URL/token/source
  path in an exception. A Telegram message may therefore contain a dead link after ambiguous
  delivery, but an unreported live capability cannot result.

### Conditional public operations

`app.artifacts:is_public_artifact_request(path, method)` is the single parser used by
`app.auth:requires_auth`. It returns true only for syntactically valid locators, validated enabled
configuration, and these exact pairs:

- `GET|HEAD /api/artifacts/open/<locator>`
- `POST /api/artifacts/open/<locator>/redeem`
- `GET /api/artifacts/open/<locator>/content`

All adjacent prefixes, suffixes, methods, and invalid/disabled configurations return false and
therefore retain normal `/api` authentication.

`GET|HEAD open` never changes capability state. Without a valid grant it returns a fixed bootstrap
that reads `location.hash`, locally validates its fixed shape, removes the fragment immediately
with `history.replaceState`, POSTs JSON to the current path's `/redeem` sibling, and reloads. A syntactically
valid locator may receive the same bootstrap even if absent, so GET does not become an existence
oracle. Redeem performs bounded non-reflecting parsing, HMAC comparison, and state checks; all
invalid/expired/revoked/missing outcomes are a generic `404` and never include submitted values.

With a valid grant, `GET open` returns fixed wrapper markup. Its hash-pinned script derives
`<current pathname>/content` from `location.pathname`; neither locator nor artifact text is
interpolated into executable markup. The wrapper creates exactly:

```html
<iframe id="artifact" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe>
```

The content endpoint accepts only the artifact grant cookie plus exact
`Sec-Fetch-Dest: iframe`; it intentionally ignores the dashboard session cookie. It opens the
stored name through the private store descriptor, reads into one capped immutable buffer, verifies
the registered length/SHA-256, and returns that same buffer. No `FileResponse`, pathname reopen,
range response, ETag, or conditional `304` is used.

### Headers

Bootstrap/wrapper:

```text
Content-Type: text/html; charset=utf-8
Content-Security-Policy: default-src 'none'; script-src 'sha256-{base64(sha256(exact_inline_script_bytes))}'; connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
Referrer-Policy: no-referrer
Cache-Control: no-store, private, max-age=0
X-Content-Type-Options: nosniff
```

Nested artifact content:

```text
Content-Type: text/html; charset=utf-8
Content-Security-Policy: sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'self'
Referrer-Policy: no-referrer
Cache-Control: no-store, private, max-age=0
X-Content-Type-Options: nosniff
```

The header hash is computed mechanically from the fixed inline script constant and the test
recomputes it from the response bytes; no human chooses a digest. Reject `Range` on content rather
than adding partial responses. Never add `allow-same-origin`, `allow-forms`, `allow-popups`,
`allow-downloads`, or `'unsafe-eval'`.

## File-level implementation map

### New files

- `app/artifacts.py`
  - `ArtifactConfig`, `load_artifact_config()`, `is_public_artifact_request()`.
  - descriptor-based source snapshot/private-store open/write/read/cleanup.
  - capability verifier, grant issue/verify, public URL construction.
  - `publish_snapshot()`, pending-to-active delivery transition, `open_artifact_buffer()`,
    `revoke_artifact()`, startup cleanup independent of public enablement.
- `app/routes/artifacts.py`
  - Pydantic publish request and publisher proof/session resolution.
  - authenticated publish/revoke routes and public open/redeem/content routes.
  - fixed bootstrap/wrapper templates and exact security headers.
- `tests/test_artifacts.py`
  - server-side groups 1–7 and 10–12 below, with deterministic clocks/race barriers.
- `tests/test_artifacts_browser.py`
  - isolated FastAPI/DB/store fixture and engine-selected browser confinement/render tests.

### Existing files

- `app/db.py`: idempotent table/index plus narrow create/get/revoke/touch/expiry/delete functions.
- `app/auth.py`: delegate exact conditional public-route recognition to `app.artifacts`; all other
  behavior unchanged.
- `app/main.py`: register artifacts router; after `init_db()`, run registry-scoped expiry cleanup
  independently of the public feature flag. Public route exemptions still require fully validated
  enabled configuration.
- `app/mcp_stdio.py`: add `publish_artifact(path, caption="", ttl_seconds=86400)`; send only path,
  caption, TTL because session identity/proof are already attached by `_auth_headers()`; result never
  contains a bearer. Existing `send_file` stays unchanged and is documented as fallback.
- `app/tg_bridge.py`: thread `disable_link_preview=False` through `_tg_send_safe()` and
  `send_text_to_tg()`; artifact publication alone passes true and aiogram receives
  `LinkPreviewOptions(is_disabled=True)`.
- `tests/conftest.py`: clear all artifact env variables in the hermetic autouse fixture.
- `tests/test_auth.py`: exact feature-on/off method/path matrix and protected raw regression.
- `tests/test_mcp_stdio.py`: MCP payload/result/error/fallback contract.
- `tests/test_tg_bridge.py`: link-preview flag propagation and existing document path regression.
- `tests/route_surface_snapshot.json`: add only the five intentional route/method entries.
- `.env.example`: document disabled-by-default variables; no real secret/value and no live config.
- `docs/tasks/294/browser-compatibility.md` (Gate C only): measured browser/device matrix with raw
  result, version, date, operator, and enable/keep-disabled decision.

## What not to touch

- Do not weaken, redirect, or refactor `app/routes/system.py:_is_safe_path` or
  `GET /api/files/raw`; #294 creates a separate publication boundary.
- Do not make `/uploads` an artifact store or expose the private store through StaticFiles/nginx.
- Do not change dashboard cookie flags, generic CSRF policy, CORS, or unrelated auth exemptions.
- Do not add a dashboard publishing UI in this release; the MCP-to-Telegram flow is the requested
  vertical path.
- Do not change `send_file`/`/api/tg/send_file`, infer HTML publication automatically, or
  auto-document-fallback after a security validation failure.
- Do not transform/rewrite artifact HTML, inject a CSP meta tag, enable external/CDN scripts, add
  a separate public origin, or add multi-tenant ACLs.
- Do not modify live `.env`, nginx, systemd, DNS, Telegram configuration, or restart/deploy without
  a separate explicit operator action.

## Twelve acceptance-test groups

These are the authoritative group boundaries; ticket tests below map to them verbatim.

1. **Auth surface.** Raw stays anonymous-`401`; exact public open/redeem/content pairs are exempt
   only under valid enabled config; content additionally requires grant + exact iframe destination;
   dashboard cookie/HEAD/other methods cannot authorize content; disabled/malformed config and
   adjacent routes fall through auth.
2. **Source path boundary.** Regular allowed UTF-8 HTML succeeds. Reject absolute outside roots,
   `..`, sibling prefixes, symlink at each directory/final position, FIFO/device, dot-directory,
   wrong extension, invalid UTF-8, empty file, and 10 MiB + 1 without a row/file.
3. **Race/atomicity.** Deterministically retarget source and stored pathnames and mutate an open
   stored inode while a read barrier is held. Only the originally authorized complete source is
   copied; serving either returns the exact registered immutable buffer or fails before response.
   Mutants that re-open a path or verify-then-stream must make the oracle red.
4. **Secret handling.** Capability is 256 bits; DB contains only the HMAC verifier; API/MCP
   response, filenames, grant cookie, app/proxy logs, and error text lack token/source path.
   Malformed JSON, oversized/non-string capability, DB failure, and unexpected exceptions remain
   non-reflecting.
5. **Fragment/bootstrap flow.** Captured ASGI/HTTP request target lacks fragment; fixed bootstrap
   contains no artifact bytes; successful redeem sets exact cookie flags, removes fragment, and
   reloads; invalid states are generic.
6. **Replay/revocation/expiry.** Repeat and second-browser redemption works until absolute server
   expiry. Row revocation blocks raw fragment and existing cookie immediately. Secret rotation
   blocks both. Pending rows cannot redeem or serve, including after Telegram exception,
   cancellation at deterministic pre/post-dispatch barriers, activation failure, or simulated
   process loss. Injected server time owns the decision.
7. **Telegram preview/scanners.** Artifact message passes preview-disabled. Anonymous preview
   GET/HEAD never redeems or changes rows. Explicit document fallback still sends as a document.
8. **Browser confinement.** Malicious artifact cannot fetch dashboard/external collector, read
   cookie/storage, form-submit, popup/frame, replace/navigate parent, or navigate its own child to
   an external origin. Same-origin child self-navigation stays nested and arrives without dashboard
   cookie. Direct `/content` top-level navigation fails.
9. **Rendering corpus.** Enumerate every current `docs/**/*.html|htm` (52 at research time) without
   hard-coding the count; each reaches a rendered DOM under the wrapper. The two external-script
   files record expected blocked network dependencies rather than weakening CSP.
10. **Cache/MIME.** Wrapper/content exact headers, no Range/ETag/Last-Modified/304, no stored body
    after revoke, fixed HTML MIME + `nosniff`/`no-referrer`/`no-store` through TestClient and the
    release curl probe.
11. **Origin/config construction.** Accept only exact HTTPS origin and bounded integer values;
    reject HTTP, userinfo, query, fragment, path, hostile Host/forwarded headers, bad secret and
    out-of-range TTL/size. Emitted Telegram URL uses configured origin exactly.
12. **Fallback/surface/migration/rollback.** DB init twice is stable and old rows untouched;
    feature-off with old/valid/invalid locators uses normal auth; route snapshot changes only as
    planned; existing document tests stay green; cleanup is registry-scoped and runs with public
    links disabled; old code can ignore table/files.

## Release gates

### Gate A — server-side security first

Must be green before any browser gate:

```bash
uv run pytest -x -q \
  tests/test_artifacts.py \
  tests/test_auth.py \
  tests/test_db.py \
  tests/test_mcp_stdio.py \
  tests/test_tg_bridge.py \
  tests/test_routes_surface.py
```

Required result: exit 0, zero skips for #294 tests. Then run the full suite exactly once as required
by the implementation phase. A modified `uv.lock` aborts the pass.

### Gate B — Chromium

Only after Gate A:

```bash
ARTIFACT_BROWSER=chromium uv run pytest -x -q tests/test_artifacts_browser.py
```

Required result: exit 0, zero skips, groups 5/8/9/10 green. Code may merge after Gate B, but the
feature remains disabled and document fallback remains the live behavior.

### Gate C — Firefox, WebKit, and real Telegram clients

Only after Gate B:

```bash
ARTIFACT_BROWSER=firefox uv run pytest -x -q tests/test_artifacts_browser.py
ARTIFACT_BROWSER=webkit uv run pytest -x -q tests/test_artifacts_browser.py
```

Both commands must exit 0 with zero skips. Then exercise the actual public HTTPS URL through
Telegram Desktop, Android in-app browser + external handoff, and iOS in-app browser + external
handoff. For each client record in `docs/tasks/294/browser-compatibility.md`: application/OS/browser
version, message preview absent, fragment absent from captured server request/log, fragment removed
after redeem, wrapper rendered, repeat open works, same-origin child navigation has no dashboard
cookie, external child navigation blocked, revoke blocks an already open grant, and document
fallback opens. On the isolated public-HTTPS test instance, each engine/client must also open and
redeem a link, then survive a controlled test-service restart with a newly generated
`ARTIFACT_LINK_SECRET`: both its already stored grant cookie and its original fragment must be
rejected afterward. Record those two results separately per row; restoring a previous secret or
reusing production capability material is forbidden.

Any missing client, omitted header, skip, mismatch, or unmeasured row means
`ARTIFACT_PUBLIC_LINKS_ENABLED` stays `0`. The result is a successful safe fallback, not permission
to weaken CSP/cookie/Fetch-Metadata controls. A separate cookieless origin requires a new research
and plan if Gate C cannot pass.

## Tickets

### T1 — Secure snapshot and durable registry

- Files: `app/artifacts.py` (new), `app/db.py`, `tests/test_artifacts.py` (new),
  `tests/test_db.py`, `tests/conftest.py`.
- Scope: configuration validation; HMAC domains; session-root descriptor walk; stable source read;
  private atomic copy; pending/active/revoked DB schema and CRUD; scoped expiry cleanup that remains
  operational with public links disabled. No public route or Telegram delivery.
- Test (specified, not yet frozen):
  `uv run pytest -x -q tests/test_artifacts.py tests/test_db.py -k 'test_t1_'`.
- Missing-behavior assertion to freeze RED: `assert published.content_sha256 == sha256(source_bytes)`
  after the source path has been retargeted, plus rejection matrix and DB invariant assertions from
  groups 2/3/4/11/12.
- AC: the named command is green; groups 2, source half of 3, persistence half of 4, 11, and DB/
  cleanup portion of 12 pass; a pending row is never readable and feature-off startup removes only
  registry-selected expired files/rows; DB/file contain no source path/capability;
  `git diff -- uv.lock` is empty.
- blocked-by: none

### T2 — Complete server-to-Telegram capability flow

- Files: `app/artifacts.py`, `app/routes/artifacts.py` (new), `app/auth.py`, `app/main.py`,
  `app/mcp_stdio.py`, `app/tg_bridge.py`, `.env.example`, `tests/test_artifacts.py`,
  `tests/test_auth.py`, `tests/test_mcp_stdio.py`, `tests/test_tg_bridge.py`,
  `tests/route_surface_snapshot.json`.
- Scope: in one vertical slice, add the conditional auth parser; publish/revoke/open/redeem/content
  routes; fixed bootstrap/wrapper; path-scoped grant; exact-buffer response and headers; MCP tool;
  server-bound publisher proof; preview-disabled TG delivery; safe error/revocation; explicit
  document fallback; flag-off rollback. The route snapshot changes once, with the complete surface.
- Test (specified, not yet frozen):
  `uv run pytest -x -q tests/test_artifacts.py tests/test_auth.py tests/test_mcp_stdio.py tests/test_tg_bridge.py tests/test_routes_surface.py -k 'test_t2_ or route_surface_snapshot'`.
- Missing-behavior assertions to freeze RED:
  1. with dashboard cookie but no artifact grant, `GET .../content` plus
     `Sec-Fetch-Dest: iframe` returns no bytes; with a grant but `Sec-Fetch-Dest: document` it also
     returns no bytes; only grant + exact `iframe` returns the registered immutable buffer;
  2. the captured TG call contains `#<capability>` with `LinkPreviewOptions.is_disabled is True`,
     while captured route/MCP response, DB, logs, cookie, and filename contain no capability;
  3. forged session ID/proof cannot select another session's roots;
  4. a Telegram exception and cancellation at deterministic barriers after dispatch both leave the
     row non-active, and open/redeem/content all fail generically; the same is true when activation
     raises after explicit Telegram success.
- AC: the named command is green; groups 1, stored-serve half of 3, remaining 4, unit half of 5,
  6, 7, server half of 10, origin emission in 11, and auth/fallback/surface portion of 12 pass;
  raw stays protected; key rotation rejects old fragment and cookie; no `FileResponse` occurs in
  the content path; `send_file` regression remains green; non-success revokes the new link and
  returns only a bearer-free explicit fallback instruction. No Telegram exception,
  `CancelledError`, activation failure, or crash-before-activation path can leave an active row;
  an abandoned pending row is denied and removed by disabled-mode expiry cleanup.
- blocked-by: T1

### T3 — Chromium confinement and corpus gate

- Files: `tests/test_artifacts_browser.py` (new), plus only the T2 production files if the frozen
  browser oracle exposes a defect.
- Scope: production-shaped local **HTTPS** server with ephemeral test certificate, isolated DB/store,
  enabled auth/config, and browser context configured to trust only that fixture; end-to-end
  fragment redeem, cookie, wrapper/child, navigation, CSP, cache/revoke, and repository HTML corpus
  in Chromium. Do not weaken the production HTTPS validator for tests.
- Test (specified, not yet frozen):
  `ARTIFACT_BROWSER=chromium uv run pytest -x -q tests/test_artifacts_browser.py`.
- Missing-behavior assertion to freeze RED: the malicious child executes inline JS but produces
  zero external collector requests, zero authenticated dashboard/API requests, cannot replace the
  top page, and direct content navigation has no body; the wrapper remains at its locator URL.
- AC: the named command exits 0 with zero skips; groups 5, 8, 9, and browser half of 10 pass; every
  current repository HTML reaches a DOM; feature default remains `0` after the test.
- blocked-by: T2

### T4 — Cross-engine and Telegram real-device enablement decision

- Files: `docs/tasks/294/browser-compatibility.md` (new); no production/config edit unless a new
  separately approved fix ticket is required.
- Test:
  `ARTIFACT_BROWSER=firefox uv run pytest -x -q tests/test_artifacts_browser.py && ARTIFACT_BROWSER=webkit uv run pytest -x -q tests/test_artifacts_browser.py`;
  delivery check: `browser-compatibility.md` contains non-placeholder rows for Telegram Desktop,
  Android in-app/external, and iOS in-app/external with every Gate C field and an explicit
  `ENABLE` or `KEEP DISABLED` verdict.
- AC: both commands exit 0 with zero skips **and** every real-device row passes before an operator
  may enable. Each engine/device row separately proves that controlled test-secret rotation rejects
  both its already issued grant and original fragment. Otherwise the accepted result is
  `KEEP DISABLED`, current document fallback works, and no security control is weakened. Enabling
  the live flag/restart is outside this ticket and always requires explicit operator authorization.
- blocked-by: T3

## Phase 3 oracle-entry gate

The task sender explicitly restricted this Phase 2 turn to `docs/tasks/294/`, and directory
ownership does not authorize `tests/`. Therefore this plan specifies exact test paths, names,
commands, and missing-behavior assertions but **does not pretend they are committed RED oracles**.
No ticket is delegable and Phase 3 must not touch runtime until a separately authorized oracle-only
change commits the named `test_t1_*` through `test_t3_*` checks and each command fails on the stated
missing behavior (not import/collection error). Those test/fixture/config files then become immutable
for executors under the full-cycle acceptance-test rule.

T4 includes real-device evidence that cannot be made a unit oracle; its automated engine command and
delivery matrix are the acceptance boundary. It must remain on the expensive/manual side.

## Independent plan review

The two-round adversarial record is preserved in [codex-review-plan.md](codex-review-plan.md).
Round 1 returned `CHANGES REQUIRED` for cancellation/exception-safe Telegram delivery,
real-client secret rotation, and cleanup while disabled. This revision adopted all three through
the inert pending-state protocol, per-client fragment-and-grant rotation checks, and flag-independent
registry cleanup. The final permitted prose round returned `APPROVED` with no blocking findings or
actionable suggestions. Its approval is specifically conditional on completing the separately
authorized RED oracle-entry commit before any runtime implementation.

## Full regression and deployment rehearsal

After each ticket's focused command, run its nearest unchanged regression. After T4:

```bash
uv run python -m pytest -x -q > /tmp/pytest-294.log 2>&1
```

Read the log once. Any modified `uv.lock` aborts; restore the dependency barrier rather than commit
resolution drift. Because shared auth/routes/DB/TG/MCP runtime changes, implementation Codex review
is mandatory even if the diff is small.

Before a real enablement, on an authorized restart window only:

1. back up SQLite with `sqlite3.Connection.backup`, not `cp`;
2. install a persistent 32-byte-or-stronger secret and exact public HTTPS origin;
3. restart Orchestra once so Python routes and DB schema load;
4. reconnect MCP sessions so the new tool appears;
5. run anonymous raw=`401`, fragment-not-in-request/log, no-store/CSP, revoke, and document-fallback
   smoke probes;
6. enable only if Gate C already says `ENABLE`.

No VPS pull/deploy/restart or live config mutation is authorized by this plan.

## Rollback

1. Set `ARTIFACT_PUBLIC_LINKS_ENABLED=0` and perform an explicitly authorized restart. Conditional
   public exemptions disappear; all artifact API paths fall through normal auth, while raw and
   document delivery keep current behavior.
2. If capability compromise is suspected, rotate `ARTIFACT_LINK_SECRET`; old fragment verifiers and
   old grants both fail. Keep the feature disabled until a new Gate C check if browser behavior was
   implicated.
3. Leave the additive table/private files inert. Old Orchestra code ignores both. The new startup
   cleanup deliberately remains registry-scoped and runnable with the public flag at `0`, so the
   first rollback restart and later restarts remove expired active/revoked/pending rows and their
   registered files without temporarily restoring the public origin, secret, or auth exemptions.
4. Do not drop the table, delete broad directories, alter nginx, or expose files from another route
   as a rollback shortcut.
