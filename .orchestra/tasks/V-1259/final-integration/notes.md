# V-1259 final integration follow-up

Authority: Orchestra-orchestrator's follow-up after reviewing imported
`6f7f5117de49a59dab6c5d108e3f3d42b5b1f1d4` (accepted source identity, not merged).
Only two test files may change; retain the five accepted recovery files and every
other source unchanged. No commit/import SHA can be generated in this no-.git copy.

Confirmed integration defects before editing:

1. The supplied tests/test_default_pipeline.py lacks the six V-1256 parametrized
   research-closure module-delivery cases committed in public main b9. Recover
   the entire exact b9 test file, with only specialist added to the expected roles.
2. The specialist pipeline test asserts Sol plus absence of the Argon string.
   The unchanged Phase B patch selects Argon, so this stage-specific assertion
   would reject the authorized next stage. Replace it with the exact two-model
   bounded contract while retaining admission, prompt, parent and leak guards.

Test both states serially/offline in default .venv with provisioned uv 0.11.28.
Phase B uses a task-local copy of the actual manifest/prompt tree, never the root
manifest. Verify the unchanged Phase B patch with fuzz=0, and restore the temporary
manifest plus process-local pipeline pointer exactly afterward. No live apply,
model/SSH/private DB calls, restarts, workers, review, merges, or publishing.

The earlier 625-pass log and missing-CLAUDE.md root-contract failure remain
historical evidence, unchanged. Root owns complete-host instruction validation.
Resource check: host free 12 GiB/available 73 GiB; cgroup ~15.1 of 49.1 GiB,
8 CPU quota, high host load. Run one bounded pytest process at a time, nice=10,
OOM score=1000; no browser or full 625 repeat.

Recovery script initially stopped before any source write: its replacement uniqueness assertion used a role-set suffix that occurs in other tests. Use the entire exact role-set assertion as the unique anchor; pinned b9 bytes were already downloaded successfully and are reused. No test run failed.

New concrete integration failure: unchanged Phase B manifest makes the existing static manifest contract reject model-routing.md:47 quoting hub-gemini-4-argon. First Phase B attempt exited 3 in task-plugin preflight before test collection; the canonical checker exited 1. Source file and checker must remain unchanged under this two-test-only authorization. Preserve this failure, then record the independent required checker result without aborting the affected tests. No guard/test assertion is waived. Root needs a separately authorized remedy.
