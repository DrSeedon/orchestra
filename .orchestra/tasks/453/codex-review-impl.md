<!-- Значения провайдерских форматов из примеров ревьюера вырезаны собственным гейтом #453 при коммите: репозиторий публичный, а гейт не умеет и не должен отличать выдуманный ключ правильной формы от настоящего. Текст находок не тронут. -->
<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The gate is admirably strict until a credential arrives through JSON escaping, commit metadata, or Git configuration. 🔥 I found 8 actionable issues; no files were edited.

## Findings

- **blocking: `scripts/secret_scan.py:45-46` — Scan JSON-escaped PEM bodies.** The PEM rule accepts actual whitespace only, so this exact blob text passes: `-----BEGIN PRIVATE KEY-----[pem-private-key-значение вырезано гейтом #453]-----END PRIVATE KEY-----` where both `\n` sequences are literal backslash-plus-`n`. This is the common JSON representation of a Google service-account private key, and `scan_text()` returns no finding.

- **blocking: `scripts/secret_scan.py:59-65` — Do not suppress provider-shaped values containing placeholder words.** The exact valid-shape GitHub token `ghp_[github-значение вырезано гейтом #453]` has a 36-character base62 payload, but `_is_mention()` sees `test` and discards it, so the scanner returns `[]`.

- **blocking: `scripts/secret_scan.py:34-40` — Add GitHub fine-grained PATs.** The `github_pat_` format with an 82-character base62 payload is not covered. This exact-shaped value passes unscanned: `github_pat_[github-pat-значение вырезано гейтом #453]`.

- **blocking: `scripts/secret_scan.py:105-110` — Scan pushed commits, not only the net tree diff.** After a clean push, `git commit --allow-empty --no-verify -m 'ghp_[github-значение вырезано гейтом #453]'` followed by `git push origin HEAD:main` publishes the credential in the commit message: the two trees are identical, `_changed_names()` returns no paths, and nothing is scanned. The same hole allows a secret file to be added in one pushed commit and removed in the next.

- **blocking: `scripts/secret_scan.py:98-101` — Include rename and type-change entries.** `--diff-filter=ACM` excludes `T` and `R`. With a tracked file, `rm file; ln -s 'ghp_[github-значение вырезано гейтом #453]' file; git add -A; git commit` records the token as a symlink target with status `T`, but the hook scans no path. The pre-push path at line 107 has the same omission.

- **blocking: `scripts/install_git_hooks.py:37-45` — Honor `core.hooksPath`.** The installer always writes to the common `.git/hooks`, even when local or global `core.hooksPath` points elsewhere. With `git config core.hooksPath /tmp/other-hooks` and a usable hook there, `install_git_hooks.py` reports success while Git never invokes these hooks.

- **suggestion: `scripts/secret_scan.py:40,59-65` — Reduce false positives for documentation examples.** `Authorization: Bearer [bearer-значение вырезано гейтом #453]` is a plausible dummy example, but its 26-character high-entropy payload contains no listed placeholder and is flagged as a real bearer token.

- **suggestion: `scripts/secret_scan.py:81-84,91-94` — Handle non-UTF8 names and gitlinks explicitly.** A legal filename containing byte `\x80`, such as `bad\x80.txt`, is decoded as `bad�.txt`; `git show` then fails and blocks a safe commit. Staged submodules are also mode-160000 gitlinks, so `git show :submodule` fails with `bad object`, blocking every submodule add or update. Spaces and `core.quotepath` are fine because the command uses `-z` and argv passing.

## Verdict

❌ **Incorrect.** The client gate has multiple credential bypasses and several normal Git states that fail closed. Targeted probes confirmed the escaped PEM, fine-grained PAT, placeholder-token, false-positive, rename/type, submodule, and non-UTF8 behaviors.

A public-repo gate that ignores commit messages is a bouncer inspecting only the jacket after the wallet already left.
