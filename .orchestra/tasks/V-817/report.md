# V-817 — Keep chat file links working after a worker worktree is removed

`GET /api/files/raw` now checks its existing allowed-root/security filter first. If the requested file is missing, it searches archived session records and falls back only when the record's worktree is gone, the requested path was inside that worktree, the worktree's repo-slug directory matches the session scope's canonical repository path, and the same relative file exists in that checkout and passes `_is_safe_path` too. A still-existing worktree is never shadowed by a same-named file in the main checkout. Cross-repository worktrees are excluded by the slug-to-scope check. Missing `download=1` targets now return a human-readable HTML 404; normal preview requests retain the JSON 404.

Regression coverage is in `tests/test_frontend.py`: recovery from a removed archived worktree, no fallback while the worktree remains, no cross-repository fallback, continued denial outside allowed roots, and a readable missing-download page. `tests/test_artifacts.py::test_t2_content_head_and_raw_file_route_remain_authenticated` confirms the existing route authentication contract remains in place.

Checks:

- `uv run --frozen python -m pytest tests/test_frontend.py -k 'test_raw_' -q` — 10 passed, 110 deselected.
- `uv run --frozen python -m pytest tests/test_artifacts.py::test_t2_content_head_and_raw_file_route_remain_authenticated -q` — 1 passed.
- The real V-222 path was verified with a read-only lookup: one archived session row has scope `/home/kesha/projects/seedon` and worktree `/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/zapros-prolider`; the worktree is absent and the checkout DOCX exists. Calling `/api/files/raw?path=<reported worktree path>&download=1` returned HTTP 200 with 11,747 bytes matching the checkout file. The isolated task worktree has its own nested `WORKTREE_ROOT`, so this production-shaped route probe set the root to `/home/kesha/orchestra/worktrees`, the root used by the main checkout after merge. Raw probe output is in `real-path-check.log`.
- `git diff --check` passed.

No restart was performed. Since `app/routes/system.py` is Python, the Orchestra service needs an owner-initiated restart after this change is merged for the live process to use it.
