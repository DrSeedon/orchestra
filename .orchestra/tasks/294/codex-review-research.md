# Codex review log — research #294

- Attempt 1: completed, exit 0; substantive verdict `CHANGES REQUIRED` (round spent).
- Attempt 2: completed, exit 0; prior security blockers closed, one textual test contradiction
  found (round spent; final prose-review round).

## Round 1

## Summary

The registry/private-copy boundary is sound, but the proposed contract still has three load-bearing security gaps. In particular, this exact claim is not yet supported:

> “Rotating `ARTIFACT_LINK_SECRET` is the emergency revoke-all action.”

Secret rotation does not invalidate the original capabilities, and same-origin top-level rendering plus verify-then-stream descriptor handling leave meaningful escape/race paths.

## Findings

blocking: Secret rotation does not revoke the underlying capabilities

The database stores `SHA-256(capability)` independently of `ARTIFACT_LINK_SECRET`. Rotating the secret invalidates existing signed grant cookies, but anyone retaining the fragment can immediately POST the unchanged capability and receive a new cookie signed with the new secret. This contradicts the rollback section’s “emergency revoke-all” guarantee.

Either bulk-revoke all registry rows as the revoke-all operation, include a rotatable generation/pepper in capability verification, or disable redemption until explicit reissuance. Add a test proving that an old fragment cannot redeem after revoke-all.

blocking: Hash verification followed by descriptor streaming is still a TOCTOU race

“Every artifact GET … verifies the copied file’s size/hash before returning bytes” does not guarantee that the returned bytes are those that were hashed. Another same-user process can modify the already-open regular file after verification or while it is streamed. `O_NOFOLLOW` protects pathname resolution, not subsequent in-place writes. This contradicts the claim that stored-file substitution “must fail closed.”

With the proposed 10 MiB cap, read the complete descriptor into an immutable byte buffer while hashing, compare that hash and length with the registry, then return that exact buffer. Alternatively, use storage with enforced immutability or a new immutable inode snapshot. The race test must mutate contents after verification has begun, not merely swap the pathname.

blocking: CSP sandbox does not provide the claimed isolation when the artifact is the top-level document

The design serves active artifact HTML directly after reloading `/api/artifacts/open/<locator>`. A sandboxed top-level document can still navigate its own browsing context; omitting `allow-top-navigation` primarily prevents navigation of other contexts. `connect-src 'none'`, `form-action 'none'`, and the opaque sandbox origin do not prevent `location = ...` navigation. Such navigation reaches Orchestra or external origins and, for same-site Orchestra URLs, may carry the existing dashboard cookie (`session` is currently `SameSite=Lax`, `Path=/`).

This falsifies condition 4 and the proposed browser test, which checks only whether the artifact can “navigate its parent.” Serve a fixed trusted top-level wrapper that embeds artifact bytes in a sandboxed child frame, or use a separate cookieless origin. Tests should cover self-navigation from both top-level and framed artifacts, including authenticated same-origin GETs and external URLs.

suggestion: The public exemption must be gated by feature state before authentication bypass

The rollback promises that setting `ARTIFACT_PUBLIC_LINKS_ENABLED=0` makes public open/redeem fail closed. If `requires_auth()` statically exempts the three method/path combinations, disabling or partially deploying the router can leave anonymous requests bypassing middleware and reaching fallback/404/error behavior outside authentication.

Make the exemption conditional on validated feature configuration, or register a narrowly scoped public sub-application only while enabled. Test feature-off with valid, invalid, and previously issued locators, not only issuance.

suggestion: The publisher identity and allowed-root authority are underspecified

The publication operation says roots come from “registered scope/session cwd and worktree,” while the planned MCP request necessarily supplies worker/scope context through a process holding the shared `INTERNAL_TOKEN`. Current `send_file` fields such as `scope` and `sender` are caller-provided rather than cryptographically bound to that token. Reusing that shape would let any internal-token holder claim another session and select its roots.

Specify whether the internal token intentionally grants publication across all sessions. If not, derive publisher and roots from server-side process/session registration rather than request JSON, and test forged scope/session identifiers.

suggestion: Error/log redaction needs an explicit boundary

“Never logs the request body or capability” is not guaranteed merely by using a JSON body. The current global exception handler logs exception text, and validation or HTTP middleware added later could include request details. Token secrecy is load-bearing enough to require a dedicated redeem parser/error boundary whose exceptions never contain the submitted value, plus access-log configuration documenting that bodies are not logged.

The proposed tests should inject malformed JSON, oversized tokens, type errors, database failures, and unexpected exceptions, then inspect both application and proxy output for the literal capability.

## Verdict

CHANGES REQUIRED. The private copy plus opaque registry is the right authority boundary, and keeping `/api/files/raw` authenticated is correct. However, implementation should not proceed with the current contract until revoke-all semantics, verify-to-serve atomicity, and top-level browser isolation are corrected.

## Round (2026-08-16T11:07:22Z)

## Round 2

The three prior blocking findings are substantively closed. Evidence includes the new measured result:

> `('/leak?case=child-same', None)`

One contradictory auth test remains and would break the iframe flow if followed literally.

## Prior Findings

- FIXED — revoke-all: capability verification now uses domain-separated `HMAC-SHA-256(ARTIFACT_LINK_SECRET, capability)`. Rotation invalidates both stored capability verification and signed grants; test 6 covers both old fragments and cookies.
- FIXED — verify/serve race: the content is read once into capped immutable `bytes`; that exact buffer is hashed and returned. Test 3 explicitly mutates verify-then-stream behavior.
- FIXED — top-level navigation: active HTML is confined to a sandboxed child beneath a trusted wrapper. Direct top-level `/content` access is Fetch Metadata-gated, Chromium evidence confirms same-origin child navigation omitted the dashboard cookie, and other engines are fail-closed release gates.

## New Findings

blocking: Auth test 1 contradicts the required public content endpoint

The contract conditionally exempts:

> `GET /api/artifacts/open/<locator>/content`

But test 1 says “only exact GET/HEAD open and POST redeem are public,” omitting `/content`. If implemented according to that test, the iframe request encounters normal dashboard authentication and returns `401`, breaking every artifact open.

Update test 1 to include exact conditional `GET /api/artifacts/open/<locator>/content`, requiring the artifact grant and `Sec-Fetch-Dest: iframe`, while rejecting HEAD and all other methods. Keep the explicit rule that dashboard cookies cannot authorize this endpoint.

## Verdict

CHANGES REQUIRED for the single auth-surface contradiction above. After that textual correction, the revised contract is coherent and the prior security blockers are closed.

## Author disposition after Round 2

- ACK: research test 1 now includes conditional `GET /api/artifacts/open/<locator>/content`,
  requires the artifact grant plus `Sec-Fetch-Dest: iframe`, and rejects dashboard-cookie, HEAD,
  and other-method authorization.
- No Round 3 was run: the codex-debate prose ceiling is two rounds. The Codex verdict above remains
  `CHANGES REQUIRED`; this note records the post-review correction and does not claim approval.
