# #294 implementation security review

Preserved from the implementation worker's three-round Sol review session. The findings below are
kept in chronological order; the final round is the operative verdict.

## Round 1

The path authorization remains vulnerable to a parent-component symlink race. Publication failures
also leak persistent snapshots, and delivery precedes activation in a way that can produce
irrecoverably dead links.

### Findings

- **P1 — Open source paths without traversable symlink races.**
  `app/artifacts.py:182-189`: when a publisher can rename a checked parent directory and replace it
  with a symlink between `is_symlink()` and `os.open()`, `O_NOFOLLOW` protects only the final
  component. Traverse from an opened root directory using directory FDs plus `O_NOFOLLOW` on every
  component, or use an equivalent race-free primitive.
- **P1 — Remove snapshots when Telegram delivery fails.**
  `app/routes/artifacts.py:143-147`: a failed delivery returned `502` but left the pending row and
  copied file. Revoke/delete the pending artifact and private file on every pre-activation failure.
- **P2 — Avoid delivering the link before activation.**
  `app/routes/artifacts.py:137-148`: immediate recipient navigation could redeem while the row was
  still pending, lose the fragment, and leave a dead tab. Activate before exposing the URL with
  compensating revocation, or retain/retry the fragment while pending.

Codex usage accounting emitted `ValueError: Codex completed turn reported zero tokens`; the review
text itself completed and was retained.

## Round 2 — 2026-08-16T12:27:58Z

- **FIXED:** parent-component symlink race; every component below the opened allowed root and the
  final file are opened relative to directory FDs with `O_NOFOLLOW`.
- **FIXED:** failed-delivery snapshot retention; false delivery results, exceptions, cancellation,
  and activation failure call `discard_pending_artifact()`.
- **STILL BROKEN:** delivery-before-activation race remained despite a finite retry.
- **NEW BLOCKER:** nested source paths leaked `root_fd`; repeated publications could exhaust process
  descriptors.

Verdict: **CHANGES REQUIRED** — one prior blocker remained and one new descriptor leak was found.

Exact check:

```text
$ uv run pytest -q tests/test_artifacts.py tests/test_artifacts_browser.py
...............                                                          [100%]
15 passed, 2 warnings in 19.02s
```

## Round 3 — 2026-08-16T12:30:53Z

- **FIXED:** parent-component symlink race.
- **FIXED:** failed-delivery snapshot retention.
- **FIXED:** delivery-before-activation race; normal delivery now occurs only after activation,
  with compensating deletion and revocation on failure or cancellation.
- **FIXED:** root directory descriptor leak; `root_fd` is closed separately after descended
  traversal.
- New findings: none.

## Verdict

**APPROVED — no blocking crash, corruption, security, or race findings in the reviewed surface.**

Verbatim reviewed implementation line:

```python
if parent_fd != root_fd:
```

Exact final verification recorded by the reviewer:

```text
$ uv run pytest -q tests/test_artifacts.py tests/test_artifacts_browser.py tests/test_routes_surface.py tests/test_auth.py tests/test_mcp_stdio.py::test_t2_publish_artifact_sends_only_path_caption_and_ttl tests/test_mcp_stdio.py::test_t2_publish_failure_never_automatically_uses_document_fallback tests/test_tg_bridge.py::test_t2_artifact_text_disables_link_preview_at_the_bot_call tests/test_tg_bridge.py::test_t2_text_helper_threads_preview_disable_without_changing_document_fallback
...........................                                              [100%]
27 passed, 2 warnings in 20.34s
```

The mandatory Sol security review completed. A cross-family verdict was unavailable during the
implementation slice because the Claude weekly pool was unavailable; no cross-family approval is
claimed.
