# Refresh findings

Orchestrator expanded public tracked app/ after initial partial-source report.
Confirmed app/__init__.py and backend modules available; 3 HTML and 14 JS inputs
for unchanged Tailwind globs. Both prompt edits and original CSS hashes preserved.
Baseline source snapshots: app-before.sha256 and tailwind-inputs.sha256.

Manifest CLI exits 0. Instruction CLI exits 1 because CLAUDE.md symlink is absent;
.git is also absent. These are broker-copy limitations explicitly left to root,
not reasons to alter guards or manufacture repository metadata. Exact2 baseline
with ordinary conftest is running; no --noconftest used after refresh.

Exact2 baseline completed with required runner and all fixtures: exit 1,
1 passed (manifest), 1 failed (CSS byte mismatch). Now CSS failure is reproduced
against the refreshed HTML/JS source set; initial prompt edits were retained.
Evidence: exact-before.log, exact-before.exit.

Offline full-source build exits 0; CSS is 21,129 bytes and adds only
.border-emerald-700 and .border-red-700, both referenced at app/static/js/app.js:5174.
Exact2 after build: exit 0, 2 passed with normal fixtures.

New red recorded immediately: full targeted run exit 1, 157 passed / 1 failed.
tests/test_prompting.py::TestCodexProjectDocPreflight::test_multibyte_overflow_reports_first_incomplete_line_and_bounded_fallback
asserts warning length <600; it is 665 because pytest's default temp directory
contains this long absolute workspace prefix, task notes TMPDIR, user name and test name.
No source/test change will be made for this unrelated path-length limitation.
Next diagnostic uses pytest --basetemp inside this task directory, removing the
extra pytest-of-<user>/pytest-N nesting while keeping the same test and assertions.
Original red and warning length remain reported; see targeted.log.

Completed: explicit task-local --basetemp run of the same six files exits 0,
158 passed / 0 skipped, unchanged assertions and all normal conftest fixtures.
Original long-path failure is retained in final report as an unresolved limitation.
Only CSS among 176 app-files changed; both original prompt edits preserved.
See ../report.md for complete final handoff and root metadata checks.
