# V-1259 — bounded source integration

Authority: task brief from Orchestra-orchestrator, 2026-11-03. Recover exactly
pipeline.yaml and four conflicting prompts against public main
`b9d893ec8babd4b2052ac1f497962e1966206bcb`; preserve producer app/tests/rules,
V-1256 style, privacy/quota/history/recovery guards, and all V-1257 artifacts.
V-1258/0716 must not be imported. Broker owns commits/import; this copy has no .git.

Initial evidence: pipeline SHA equals canonical pre-Phase-A baseline; all four
prompt SHAs differ from the pinned expected hashes. These are the five conflicts
explicitly authorized for recovery, not a reason to edit producer code.

Source completeness limitation found before checks: root CLAUDE.md is absent.
The actual root instruction-contract script must be run and its failure reported;
do not create/alter an extra production file to disguise the sparse-copy limit.

Resources before checks: host available 80 GiB/free 15 GiB; cgroup ~9.16 GiB
of ~49.13 GiB, quota 8 CPU. One serial pytest process expected well below 4 GiB;
nice=10, OOM score=1000, finite outer timeout. No browser/build/parallel suite.

No Phase B apply, real model/Hub calls, SSH, private DB, restart, deployment,
worker spawn/review or live state writes are authorized. Phase B is dry-run only.

Completed: 625 tests passed; static pipeline and Phase B dry-run passed. Actual root instruction contract failed at missing CLAUDE.md as expected. All 47 producer artifacts / 21 logs and 815 other initial files preserved. See report.md, five-file.patch and verification.json for returned-source evidence.
