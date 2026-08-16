# Research #294 — secure external links for generated HTML artifacts

Date: 2026-08-16

## Question

**Context.** Orchestra is a single-user FastAPI application exposed through nginx. The
existing `GET /api/files/raw?path=...` route is protected by dashboard-cookie or internal-token
authentication. That is correct for the dashboard, but a Telegram/external browser has neither
credential and receives `401`.

**Change under test.** Add a one-click way to open a deliberately published generated HTML
artifact from Telegram without granting public access to arbitrary filesystem paths.

**Baseline.** Keep `/api/files/raw` authenticated and send the HTML as a Telegram document.

**Decision outcome.** A viable contract must meet all of these conditions:

1. no anonymous request can select or infer a source filesystem path;
2. a leaked link cannot read anything except the copied artifact and has bounded lifetime;
3. path traversal, symlinks, and check/use races cannot redirect publication or serving;
4. generated HTML never executes as a top-level Orchestra document and cannot use Orchestra's
   authenticated origin, credentials, API, or top-level browsing context;
5. tokens do not enter nginx/application request logs or referrers;
6. revocation, expiry, Telegram previews, repeat clicks, and a non-JavaScript fallback have
   explicit behavior;
7. the feature is additive and can be disabled without weakening `/api/files/raw`.

## Hypotheses considered

### H1 — stateless signed raw-path URLs are sufficient

Hypothesis: an HMAC over `path + expiry` makes `/api/files/raw` safe to expose without a cookie.

Falsifier: the design still exposes path authority to an anonymous endpoint, cannot revoke one
link, can be redirected by a source-path race, or puts a replayable bearer into HTTP logs.

**REFUTED.** All four falsifiers hold for the straightforward query-string design. Signing proves
who issued a string; it does not make a mutable path immutable, prevent replay before expiry, or
remove the bearer from the HTTP request. AWS likewise defines presigned URLs as bearer tokens
usable by anyone who possesses them until expiry [9].

### H2 — a one-time opaque ID is the best capability

Hypothesis: consuming an opaque ID on first GET minimizes replay without harming one-click use.

Falsifier: a preview crawler, HEAD request, retry, Telegram in-app-browser handoff, or second
device consumes or races the only use.

**REFUTED for one-time semantics; CONFIRMED for opaque identifiers.** The identifier should be
opaque and random, but the capability should be multi-use until a short absolute expiry. Telegram
can disable link previews explicitly [16], and fragment transport prevents a preview HTTP client
from possessing the secret, but retries and browser handoff still make one-time consumption
fragile. Revocation and expiry give a predictable security boundary without a burn-after-read
race.

### H3 — a private immutable artifact store plus registry is the correct authority boundary

Hypothesis: an authenticated publication operation can copy one approved HTML file into a private
store, while an anonymous route can serve only a registry ID and never a caller-supplied path.

Falsifier: an anonymous input still reaches a filesystem path, source symlinks/races can change
the copied bytes, stored-file substitution can escape the store, or revocation cannot invalidate
already redeemed links.

**CONFIRMED as the recommended basis, conditional on descriptor-based I/O and a registry check on
every serve.** It removes the filesystem namespace from the public contract, supports per-link
expiry/revocation, and follows OWASP's recommended ID-to-file application mapping, generated
names, allowlisted types, size limits, and storage outside the webroot [13]. The condition matters:
a copy implemented as `resolve()` followed later by `open(path)` would retain a CWE-367 check/use
race [10].

### H4 — Telegram document delivery alone solves the problem

Hypothesis: keeping the present `send_file` attachment path is sufficient and avoids public
hosting entirely.

Falsifier: the user must download/find/open a local file rather than tap one interactive page.

**CONFIRMED as fallback, REFUTED as the primary UX.** It is the smallest and safest rollback path,
and it already exists, but it does not meet the requested one-click browser outcome.

## Current-system findings

### 1. Authentication is working as designed

**CONFIRMED — direct measurement (tier 1) plus current code (tier 2).** A request through the local
TLS nginx vhost without a cookie returned `401`:

```text
anonymous_raw_http=401
```

`AuthMiddleware` accepts the internal bearer or a valid dashboard cookie and otherwise returns
`401` for `/api/*` ([app/main.py:417](../../../app/main.py),
[app/auth.py:69](../../../app/auth.py)). `requires_auth` exempts only login/logout, static files,
webhooks, and applies auth to uploads; all other `/api/*` routes require authentication
([app/auth.py:78](../../../app/auth.py)). Therefore the current failure is not an auth bug, and
making `/api/files/raw` anonymous would remove a security boundary that is presently effective.

### 2. The protected raw route remains too broad to become a public capability target

**CONFIRMED — current code (tier 2).** `_is_safe_path` resolves a caller-supplied path, then accepts
it under any existing `/mnt/data`, `/opt`, `/tmp`, the entire home directory, uploads, or configured
extra roots. It adds denylisted names and extensions, which is useful defense-in-depth for an
authenticated file browser but not a narrow public-publication contract
([app/routes/system.py:163](../../../app/routes/system.py)). The raw route then passes the original
path—not the resolved object—to `FileResponse` ([app/routes/system.py:221](../../../app/routes/system.py)).

The installed Starlette `FileResponse` first `stat()`s `self.path`, then later reopens or path-sends
the same pathname (`starlette/responses.py:341-397`, measured locally). A symlink/path component can
therefore change between authorization and use; this is the check/use race described by CWE-367
[10]. The archived security audit independently records the original arbitrary-file-read impact
and says browser contracts should use project-scoped file IDs rather than raw absolute paths
([docs/archive/security-audit/SECURITY_AUDIT.md:63](../../archive/security-audit/SECURITY_AUDIT.md)).

This does **not** mean the authenticated dashboard route must be redesigned in #294. It means no
public route may call it or reuse its broad root policy.

### 3. Current HTML sandboxing fixed an earlier same-origin escalation, but headers are incomplete

**CONFIRMED — current code, response measurement, and recorded regression (tiers 1–2).** The
dashboard iframe has only `sandbox="allow-scripts"` and HTML responses add a CSP sandbox without
`allow-same-origin` ([app/static/js/app.js:1315](../../../app/static/js/app.js),
[app/routes/system.py:229](../../../app/routes/system.py)). Commit `65e7e3cf` added this after prior
research found that `allow-scripts allow-same-origin` could remove the sandbox
([docs/tasks/html-effectiveness/research.md:142](../html-effectiveness/research.md)). W3C CSP defines
the response `sandbox` directive and `allow-scripts` relaxation [12].

The live authenticated HTML response had:

```text
content-security-policy: sandbox allow-scripts; default-src 'unsafe-inline' 'unsafe-eval' data: blob:; connect-src 'none'
content-type: text/html; charset=utf-8
etag: ...
last-modified: ...
```

It had no `Cache-Control`, `Referrer-Policy`, or `X-Content-Type-Options`. `no-store` instructs HTTP
caches not to store a response [11], `no-referrer` omits the `Referer` header [15], and `nosniff`
makes browsers honor the declared MIME type [14]. Public artifact responses need all three.

### 4. Existing generated artifacts fit a stricter offline policy

**LIKELY — repository-wide direct measurement (tier 1), not a browser-render test.** The current
`docs/` corpus contains 52 `.html`/`.htm` files totaling 1,784,215 bytes; the largest is 251,783
bytes. Zero contain `eval(` or `new Function(`. Two contain an external HTTP(S) script source;
one is an actual task artifact and one is an extracted upstream sample. Those external scripts
are already blocked by the current `connect-src 'none'`/default policy. These measurements support
removing `'unsafe-eval'` and setting a 10 MiB publication cap with ample observed headroom, but do
not prove every future visualization renders under the proposed CSP.

### 5. Telegram delivery presently allows link previews

**CONFIRMED — current code and Telegram's primary API reference (tier 2).** `_tg_send_safe` calls
`bot.send_message` without `link_preview_options` ([app/tg_bridge.py:1975](../../../app/tg_bridge.py)).
Telegram's Bot API exposes `LinkPreviewOptions.is_disabled` and accepts `link_preview_options` on
`sendMessage` [16]. Artifact-link messages should disable previews; generic messages need not
change.

### 6. Orchestra already has a safer descriptor pattern to reuse

**CONFIRMED — current code (tier 2).** The bug-inbox storage opens directories and regular files
with `dir_fd` and `O_NOFOLLOW`, verifies directory inode/device identity, enforces private modes,
and reads already-open file descriptors ([app/routes/system.py:1284](../../../app/routes/system.py)).
The artifact store can reuse the pattern rather than inventing another `resolve()`-then-open flow.

### 7. A CSP-sandboxed top-level artifact can still navigate with the dashboard cookie

**CONFIRMED — direct Chromium measurement (tier 1), then independently identified by Codex.** A
top-level response with the proposed `sandbox allow-scripts`, `connect-src 'none'`, and
`form-action 'none'` still executed `location='/leak'`; the resulting same-origin top-level GET
carried the host's `SameSite=Lax` `session` cookie:

```text
('/top', 'session=secret')
('/leak', 'session=secret')
```

Therefore the public route must never render artifact code as its top-level document. A second
Chromium probe put the artifact in `<iframe sandbox="allow-scripts">` under a trusted parent's
`frame-src 'self'`: same-origin self-navigation stayed in the child and carried no session cookie,
while external child navigation was blocked by the parent CSP. This supports the wrapper design
below, but Firefox, WebKit, and Telegram WebViews remain release-gate tests rather than assumed
equivalent behavior.

```text
(18765, '/child?dest=same', 'session=secret')
(18765, '/leak?case=child-same', None)
external child navigation requests observed: 0
```

## Threat model and required controls

| Threat | Required contract/control | Residual risk |
|---|---|---|
| Anonymous path traversal/arbitrary read | Anonymous routes accept only a fixed-format registry ID; no `path` parameter, no source path in redirect/response | Authenticated publishers can deliberately publish data they can read; that is the authorized action |
| Source symlink or TOCTOU | Walk from a pre-opened approved root with `openat`/`dir_fd` + `O_NOFOLLOW`; require a regular file; copy from that fd; verify source `(dev, ino, size, mtime_ns, ctime_ns)` is stable through copy | A same-user malicious process can still race content writes; stability verification makes the attempt fail rather than silently publish another path |
| Stored-file substitution | Private `0700` directory; random server filename; `0600`, `O_EXCL`, atomic rename; read at most 10 MiB once from an `O_NOFOLLOW` fd into an immutable `bytes`, hash that exact buffer, then return that same buffer | Same Unix user can mutate state; only bytes matching the registered hash are returned, otherwise fail closed and alert |
| Token in nginx/app logs or referrer | Put the 256-bit capability after `#`; redeem it from fixed bootstrap JS via POST body; never log body/token; `Referrer-Policy: no-referrer` | Telegram/chat provider and the user's browser necessarily see the shared URL; crash/session sync may capture the initial fragment before JS removes it |
| Replay | Multi-use only until absolute expiry; registry revocation checked on every serve; short-lived scoped grant cookie after redemption | A stolen token remains replayable until expiry/revocation; this is inherent in bearer links [9] |
| Link preview/scanner consumes secret | Fragment is not part of the HTTP dereference under RFC 3986 [7]; Telegram preview disabled [16]; GET/HEAD never redeem | Telegram client fragment preservation still requires real-device validation |
| Artifact script calls dashboard/API or replaces the page | A fixed trusted top-level wrapper embeds content in `<iframe sandbox="allow-scripts">`; parent `frame-src 'self'` confines child navigation; child has an opaque origin and `connect-src 'none'`; content route requires `Sec-Fetch-Dest: iframe` | Browser differences remain possible; unsupported/missing Fetch Metadata fails closed to the document fallback, and a separate cookieless origin is stronger defense-in-depth |
| MIME confusion/active non-HTML | Publication allowlists `.html`/`.htm`, validates UTF-8, response MIME is fixed, `nosniff` [14] | HTML is intentionally active under the sandbox |
| Stale caches after revoke | `Cache-Control: no-store, private, max-age=0`; registry check before every body; no ETag/Last-Modified/Range on public response | RFC 9111 notes `no-store` is not a complete defense against malicious/noncompliant caches [11] |
| CSRF/host-header poisoning | Build links only from configured HTTPS `PUBLIC_BASE_URL`; redeem accepts JSON plus exact expected `Origin`; cookie is `Secure; HttpOnly; SameSite=Strict` and artifact-path-scoped | A bearer holder can redeem intentionally; CSRF does not grant access without the capability |

OWASP warns that URL-carried session identifiers leak through links, logs, browser history,
bookmarks, referrers, and search engines, recommends at least 128 bits from a CSPRNG, and recommends
keeping identifier meaning server-side [8]. The fragment/redeem split follows those controls while
preserving a clickable URL. RFC 3986 specifies that a fragment is separated before dereference and
processed solely by the user agent, so it does not enter the HTTP request [7].

## Options compared

| Option | Path boundary | Leakage/replay | Expiry/revocation | Telegram/browser behavior | Verdict |
|---|---|---|---|---|---|
| Stateless HMAC URL over source path + expiry | **Bad:** public authority still names a mutable source path | Query bearer reaches request/access logs; replayable until expiry | Expiry yes; per-link revocation requires extra state, defeating statelessness | Simple click, but previews/scanners possess query token | **Reject** |
| One-time opaque artifact ID | Good if it maps only to a copied object | If ID is in path/query it is logged; one-time narrows replay | Registry supports both | First preview/retry/handoff can burn the link | **Reject one-time behavior**; retain opaque random token |
| Private immutable copy + registry + short-lived opaque capability | **Best:** public ID maps only to copied bytes | Fragment avoids HTTP logs/referrer; replay bounded by expiry/revocation | Both, including already-redeemed grant checks | Requires tiny JS bootstrap/cookie; repeat clicks work; preview cannot redeem | **Recommend** |
| Telegram document only | No public web boundary | No Orchestra URL bearer | Telegram controls retention | Reliable fallback, but not one-click interactive HTML | **Keep as fallback/rollback** |

A signed URL over an immutable registry ID could be made acceptably narrow, but it still exposes a
bearer in the request unless it also uses the fragment/redeem flow. Once a registry is required for
revocation and copied-byte identity, a random 256-bit capability with a server-side verifier is
simpler than a stateless signed URL and supports explicit deletion.

## Recommended contract

### Publication (authenticated/internal only)

1. Add an explicit `publish_artifact` operation; do not make every `send_file` or every HTML file
   public automatically. Inputs are source path, caption/display name, and requested TTL.
2. Require feature enablement, `PUBLIC_BASE_URL` with an exact `https` origin (no userinfo, query,
   or fragment), and a persistent random `ARTIFACT_LINK_SECRET`. Fail closed if any is absent;
   never derive the external origin from `Host` or reuse the loopback `ORCHESTRA_URL`.
3. Treat the existing `INTERNAL_TOKEN` honestly as a server-wide privileged credential: a holder
   can already call protected file routes, so #294 cannot claim worker-level isolation. Resolve
   allowed roots from the server's registered session cwd/worktree records, not caller-supplied
   `sender` or `scope`; those fields are audit labels only and cannot expand authority. Do not
   reuse `_get_allowed_roots()` because it admits broad home, `/tmp`, `/opt`, and `/mnt/data` roots.
   Open each relative component from the approved root with `O_NOFOLLOW`, require a regular UTF-8
   `.html`/`.htm` file, and cap copied bytes at **10 MiB**. Per-worker credentials would be a future
   least-privilege project, not a hidden property of this contract.
4. Copy from the already-open fd to a private state directory such as
   `$STATE_DIRECTORY/artifacts` or `$XDG_STATE_HOME/orchestra/artifacts`. Use a random ID for the
   stored name, `0700` directory, `0600` file, exclusive temporary creation, content hash, fsync,
   and atomic rename. Recheck source fd metadata after copying and discard the copy if it changed.
5. Generate independent values: a 128-bit-or-larger random non-secret locator ID and a 256-bit
   capability (`secrets.token_urlsafe(32)`). Store only a domain-separated
   `HMAC-SHA-256(ARTIFACT_LINK_SECRET, capability)` verifier and compare in constant time. Never
   return/store/log the absolute source path; retain only sanitized display name, publisher/scope,
   copied size and SHA-256, timestamps, and state. Rotating the secret then invalidates both old
   capability verifiers and signed grant cookies, making it a real revoke-all operation.
6. Start with a **24-hour default expiry and 7-day hard maximum**. These are product starting
   values, not measured Telegram behavior; long-lived use should send a document instead. Expose
   authenticated revoke and delete actions. Lazy cleanup on access plus a startup/daily expiry
   sweep is sufficient for this single-user service.

### Public open and redeem

The issued URL is:

```text
https://<PUBLIC_BASE_URL>/api/artifacts/open/<locator>#<capability>
```

Only these exact method/path pairs bypass normal dashboard auth, and only while a validated feature
configuration is enabled:

- `GET|HEAD /api/artifacts/open/<locator>`
- `POST /api/artifacts/open/<locator>/redeem`
- `GET /api/artifacts/open/<locator>/content`

Publish/list/revoke/delete stay under normal cookie/internal-token auth. Avoid a broad
`/artifacts/*` exemption and retain anonymous `401` for `/api/files/raw`. When the feature is off
or configuration is incomplete, middleware applies normal `/api` authentication before routing;
old, valid, invalid, and unknown locators all fail closed rather than reaching an anonymous handler.

On a GET without a valid artifact grant cookie, return a fixed bootstrap page containing no
artifact bytes and no locator interpolation. A hash-pinned inline script reads `location.hash`,
POSTs the capability as JSON to the current URL's exact `/redeem` sibling, calls
`history.replaceState` to remove the fragment, and reloads. The redeem endpoint:

- accepts only JSON and the configured public origin;
- rejects non-string or oversized input before a domain-separated HMAC and constant-time verifier
  comparison, then checks expiry/revocation;
- sets a short HMAC-signed grant containing locator and expiry, not the raw capability;
- uses a dedicated `ARTIFACT_LINK_SECRET` with domain separation;
- sets `Secure; HttpOnly; SameSite=Strict; Path=/api/artifacts/open/<locator>`;
- parses and handles errors inside a dedicated boundary whose exceptions never include submitted
  values; application/proxy logs never record the request body or capability.

After redemption, reload returns a **fixed trusted top-level wrapper**, never the active artifact.
The wrapper embeds `/api/artifacts/open/<locator>/content` in
`<iframe sandbox="allow-scripts">`. The content endpoint requires a valid artifact grant plus
browser Fetch Metadata consistent with a same-origin iframe (`Sec-Fetch-Dest: iframe`); a direct
top-level navigation and a client omitting that header fail closed. It rechecks registry
expiry/revocation, opens the copied file with `O_NOFOLLOW`, reads no more than the configured cap
into one immutable `bytes` buffer, verifies that buffer's length and SHA-256, closes the fd, and
returns that exact buffer. There is no verify-then-stream window. Therefore revocation invalidates
an already-redeemed cookie, and in-place mutation can only produce a hash failure rather than
different served bytes.

GET and HEAD never consume the capability. Invalid locator, token, expired state, missing file,
unexpected Fetch Metadata, or hash mismatch returns a generic no-content error without source
metadata. The content response must not fall back to dashboard-cookie authentication.

### Wrapper and artifact responses

The trusted top-level wrapper has fixed markup, no artifact interpolation, and a hash-pinned script
only for the bootstrap/reload flow. The script derives the nested `content` URL from the current
validated pathname, so the server does not interpolate locator or artifact text into executable
markup. Its CSP permits the same-origin child frame and otherwise denies content and embedding:

```text
Content-Security-Policy: default-src 'none'; script-src '<fixed-sha256>'; connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
Referrer-Policy: no-referrer
Cache-Control: no-store, private, max-age=0
X-Content-Type-Options: nosniff
```

The nested content response returns the already-verified immutable buffer, not
`FileResponse(path)`, and sets at least:

```text
Content-Type: text/html; charset=utf-8
Content-Security-Policy: sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'self'
Referrer-Policy: no-referrer
Cache-Control: no-store, private, max-age=0
X-Content-Type-Options: nosniff
```

Do not add `allow-same-origin`, `allow-forms`, `allow-popups`, `allow-downloads`, or
`'unsafe-eval'`. The parent `frame-src 'self'` prevents the sandboxed child from navigating its own
frame to an external origin in the measured Chromium behavior; the child's opaque sandbox origin
caused a same-origin navigation to omit the Lax dashboard cookie. Cross-engine tests must preserve
both properties or fail closed to document delivery. A separate cookieless preview origin remains
the required fallback architecture if any supported Telegram/browser engine violates them.

### Telegram and fallback

Send the link with `LinkPreviewOptions(is_disabled=True)`. Keep the current Telegram document
delivery as an explicit companion/fallback for expired links, disabled cookies/JavaScript,
unsupported WebViews, or files intended to persist. Do not silently replace the fallback with a
public upload URL.

## Data and deployment migration

Add an idempotent SQLite table (names illustrative):

```text
artifacts(
  id TEXT PRIMARY KEY,
  capability_verifier BLOB NOT NULL,
  stored_name TEXT UNIQUE NOT NULL,
  content_sha256 BLOB NOT NULL,
  display_name TEXT NOT NULL,
  publisher TEXT NOT NULL,
  scope TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  revoked_at INTEGER,
  last_opened_at INTEGER,
  open_count INTEGER NOT NULL DEFAULT 0
)
```

No existing file or link is migrated. Initialize the private state directory and table before
enabling issuance. Configure `PUBLIC_BASE_URL`, a generated `ARTIFACT_LINK_SECRET`, expiry/size
limits, and `ARTIFACT_PUBLIC_LINKS_ENABLED=1`; absent configuration must leave the feature off.
No nginx route or cache is required because the current vhost proxies the application and fragments
never reach nginx. The current nginx configuration uses the default access log, reinforcing the
choice not to put capabilities in a path or query.

Python routes require an authorized Orchestra restart. The MCP process is long-lived per backend
connection, so a new `publish_artifact` tool also requires agent reconnection; deploy route, DB,
MCP contract, and TG link formatting in one coordinated restart rather than a mixed-version window.

## Affected files for a later implementation

- `app/artifacts.py` (new): registry, capability hashing/signing, descriptor-based private store,
  copy/serve/cleanup primitives.
- `app/routes/artifacts.py` (new): authenticated publish/revoke and exact public
  open/redeem/nested-content routes.
- `app/db.py`: additive table/index initialization and registry queries.
- `app/auth.py`: exact, method-aware, feature-state-gated public exemptions; no general
  `/api/artifacts` bypass.
- `app/main.py`: router registration and artifact error handling without token/body logging.
- `app/mcp_stdio.py`: explicit `publish_artifact` tool; keep `send_file` document behavior.
- `app/tg_bridge.py`: artifact-link delivery with Telegram link previews disabled.
- `app/static/js/app.js`: optional authenticated dashboard “Publish link” action; existing raw
  preview stays cookie-protected.
- `.env.example` / operator documentation: public origin, persistent signing secret, feature flag,
  TTL and size limits.
- `tests/test_artifacts.py`, `tests/test_auth.py`, `tests/test_mcp_stdio.py`,
  `tests/test_tg_bridge.py`, `tests/test_frontend.py`, and the route-surface snapshot.

## Tests required before enabling

1. **Auth surface:** anonymous `/api/files/raw` remains `401`; publish/list/revoke/delete require
   dashboard/internal auth; only exact GET/HEAD open, POST redeem, and GET nested-content are
   conditionally public. Nested-content additionally requires the artifact grant and
   `Sec-Fetch-Dest: iframe`; dashboard cookies, HEAD, and all other methods cannot authorize it.
   Adjacent verbs, prefixes, and unrelated `/api` routes stay protected; feature-off is fail-closed.
2. **Source path boundary:** allowed regular HTML succeeds; `..`, absolute outside-root paths,
   sibling-prefix paths, a symlink in every component position, final symlink, FIFO/device,
   dot-directory, wrong extension, invalid UTF-8, and >10 MiB fail without a row/file.
3. **Race mutation:** swap/retarget source paths during publication and stored paths during serve;
   also modify an already-open stored file after hashing would have begun. The response must be the
   exact immutable buffer that was hashed or fail, never a later/different stream. Mutate the secure
   open to a pathname reopen and the buffered response to verify-then-stream; require both tests to
   fail.
4. **Secret handling:** capability has 256 bits; database contains only its domain-separated HMAC
   verifier; published JSON, logs, errors, cookie, and stored filename contain neither token nor
   absolute source path. Inject malformed JSON, oversized/non-string tokens, DB failures, and
   unexpected exceptions, then assert the literal capability is absent from application and proxy
   logs.
5. **Fragment flow:** an HTTP request capture proves the fragment is absent from ASGI/nginx
   request targets; bootstrap contains no artifact bytes; valid redeem sets exact cookie flags and
   clears the fragment; wrong/expired/revoked token gives a generic failure.
6. **Replay/revocation:** the same link opens repeatedly and in a second browser until expiry;
   revoke immediately blocks both raw token redemption and an existing grant cookie; expiry uses
   injected server time, not client time. Rotate `ARTIFACT_LINK_SECRET` and prove both an old
   fragment and old grant cookie fail.
7. **Preview behavior:** Telegram artifact messages disable previews; GET/HEAD without the
   fragment cannot redeem or change state. Exercise Telegram Desktop plus real Android/iOS in-app
   browser and external-browser handoff before release.
8. **Browser confinement:** exact wrapper, iframe, and content headers are asserted. Direct
   top-level navigation to `/content` fails. A malicious fixture must fail to fetch `/api/usage`
   or an external collector, read dashboard cookies/storage, submit a form, open a popup/frame,
   replace/navigate the trusted parent, or navigate its own child frame to an external origin.
   Its same-origin self-navigation must stay in the child and arrive without the dashboard cookie.
   Run this in Chromium, Firefox, WebKit, Telegram Desktop, Android, and iOS; any engine that cannot
   enforce it uses document fallback or requires a separate cookieless origin.
9. **Rendering:** smoke-render all 52 current local HTML artifacts under the new header policy;
   identify expected failures for the two external-script files rather than weakening CSP.
10. **Cache/MIME:** after revocation, nginx/browser requests receive no cached/304 artifact body;
    responses remain `text/html; charset=utf-8`, `nosniff`, `no-referrer`, and `no-store`.
11. **Origin construction:** reject HTTP, userinfo, query, fragment, malformed origins, and hostile
    `Host`/forwarded headers; emitted URLs use the configured HTTPS origin exactly.
12. **Fallback and surface snapshot:** document delivery remains green when public links are off
    or unavailable; feature-off with old/valid/invalid locators falls through normal API auth;
    route-surface tests record only the intended conditional anonymous endpoints. Forged
    caller-supplied `sender`/`scope` cannot expand the server-derived root set.

## Rollback

Set `ARTIFACT_PUBLIC_LINKS_ENABLED=0` and restart. This stops issuance and makes public open/redeem
fail closed while leaving authenticated `/api/files/raw` and Telegram document delivery unchanged.
The additive table and private copied files can remain inert; after the maximum TTL, an authenticated
cleanup command can delete them. Rotating `ARTIFACT_LINK_SECRET` is the emergency revoke-all action.
No nginx rollback and no destructive DB migration are required.

## Counter-evidence, limitations, and open validation

- **Telegram WebView compatibility is UNCERTAIN.** RFC 3986 proves fragments are client-side, and
  Telegram provides a preview-disable control, but this session did not run an Android/iOS/Desktop
  click-through. Fragment preservation, first-party cookies, `history.replaceState`, and external
  browser handoff are release-gate measurements.
- **The 24-hour default, 7-day maximum, and 10 MiB cap are UNCERTAIN product defaults.** The size
  cap has large measured headroom over today's 252 KiB maximum; no click-latency or future embedded
  media distribution was available. Keep them configurable without permitting unlimited values.
- **The wrapper contract is browser-dependent defense-in-depth, not separate-origin isolation.**
  Chromium measurements caught the top-level-cookie flaw and then showed the wrapper confining
  external navigation and stripping the Lax cookie from sandbox-child navigation. Firefox,
  WebKit, and Telegram engines were not measured in this session. A separate cookieless origin is
  mandatory if those release-gate tests diverge, or if public hosting expands/multi-tenancy appears.
- **A bearer link cannot be made non-shareable.** Fragment transport removes the token from the
  HTTP request path, logs, and referrer, but not from the Telegram message, clipboard, browser UI,
  screenshots, or compromised endpoint. Expiry and revocation bound rather than eliminate replay.
- **`no-store` is not secure deletion.** RFC 9111 explicitly cautions that malicious or compromised
  caches are outside the directive's guarantee [11]. The contract assumes normal compliant browser
  and reverse-proxy caches.
- **Document fallback has different retention.** Telegram receives and stores the file; this avoids
  Orchestra link exposure but is not necessarily a stronger confidentiality boundary against the
  messaging provider.

## Independent review outcome

Codex adversarial review round 1 returned **CHANGES REQUIRED** with three blocking findings and
three suggestions ([codex-review-research.md](codex-review-research.md)). All were verified and
accepted. The revision:

- replaced raw SHA-256 token storage with a secret-keyed, domain-separated verifier so key
  rotation really invalidates both fragments and grants;
- made the served response the exact immutable buffer that was hashed;
- replaced top-level active HTML with a trusted wrapper and sandboxed nested content after a
  Chromium probe confirmed the top-level navigation/cookie leak;
- gated anonymous auth exemptions on valid feature state, made the shared internal-token authority
  explicit, and added a dedicated non-reflecting redeem/logging boundary.

Round 2 confirmed all three security blockers fixed, then found one contradictory auth-test line:
it omitted the public nested-content GET and would have forced the iframe through dashboard auth.
That line is corrected in test 1 above. The two-round prose ceiling forbids another review, so the
last Codex verdict remains `CHANGES REQUIRED` rather than an approval; its sole stated blocker is
resolved in the final artifact, with the author disposition recorded beside the review.

## Verdict

Use a **server-side registry plus an immutable private copy**, addressed by a non-secret locator and
a **256-bit, multi-use, short-lived opaque capability carried in the URL fragment**. Redeem the
fragment into an artifact-path-scoped HttpOnly cookie. A fixed trusted top-level wrapper must render
the artifact only in a sandboxed child; the child endpoint must return the exact immutable byte
buffer whose length/hash it verified. Recheck expiry/revocation on every wrapper/content request.
Keep `/api/files/raw` fully authenticated and keep Telegram document delivery as the fallback. Do
not use a stateless signed raw-path URL, do not render active artifact HTML top-level, and do not
make the opaque token one-time.

This is proportionate to the stated single-user system: it closes arbitrary-path and routine bearer
leakage without introducing a permanent public-hosting subsystem or multi-tenant ACL model.

## Sources

Evidence tiers follow the task research method: tier 1 direct measurement; tier 2 primary source,
specification, official documentation, or current source code; tier 3 two agreeing independent
secondary sources; tier 4 one secondary source.

1. Orchestra current source: [app/routes/system.py](../../../app/routes/system.py),
   [app/auth.py](../../../app/auth.py), [app/main.py](../../../app/main.py) — tier 2.
2. Orchestra current link/delivery source: [app/static/js/app.js](../../../app/static/js/app.js),
   [app/tg_bridge.py](../../../app/tg_bridge.py), [app/mcp_stdio.py](../../../app/mcp_stdio.py),
   [app/routes/tg.py](../../../app/routes/tg.py) — tier 2.
3. Installed Starlette 1.1.0 `starlette/responses.py:297-437`, inspected at
   `/home/kesha/orchestra/.venv/lib/python3.12/site-packages/starlette/responses.py` — tier 2.
4. Orchestra archived [Security Audit](../../archive/security-audit/SECURITY_AUDIT.md) — tier 2
   for recorded local findings, stale where the current source differs.
5. Orchestra [HTML effectiveness research](../html-effectiveness/research.md) and current commit
   `65e7e3cf` — tier 2 for the recorded sandbox regression and implemented fix.
6. Direct measurements in this session: local nginx-vhost HTTP status and response headers; nginx
   rendered configuration; systemd unit properties; 52-file HTML corpus scan — tier 1.
7. IETF, [RFC 3986: Uniform Resource Identifier (URI): Generic Syntax](https://www.rfc-editor.org/rfc/rfc3986) — tier 2.
8. OWASP, [Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) — tier 2.
9. AWS, [Download and upload objects with presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html) — tier 2 for presigned-URL bearer semantics.
10. MITRE, [CWE-367: Time-of-check Time-of-use Race Condition](https://cwe.mitre.org/data/definitions/367.html) — tier 2.
11. IETF, [RFC 9111: HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111.html) — tier 2.
12. W3C, [Content Security Policy Level 2](https://www.w3.org/TR/CSP2/) — tier 2.
13. OWASP, [File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) — tier 2.
14. MDN, [X-Content-Type-Options](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Content-Type-Options) — tier 4.
15. MDN, [Referrer-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy) — tier 4.
16. Telegram, [Bot API — LinkPreviewOptions and sendMessage](https://core.telegram.org/bots/api) — tier 2.
