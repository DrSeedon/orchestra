# Arch Audit — task report

**Deliverable:** `docs/reviews/arch-audit.md` (full architectural audit, 27 files, ~12k lines).
**Codex review:** `docs/reviews/codex-review-arch-audit.md` (corrections folded back into the report; see its Appendix B).

## Summary
- 5 parts: dependency map (3 real cycles), per-module scores, Top-10 костыли (verified), ECS-flavored target architecture, ordered incremental refactoring plan (P0–P4).
- 4 core files carry 43% of lines and all the debt: session.py, manager.py, main.py, tg_bridge.py (scores 1–2). Leaves are clean (4–5).
- 2 sub-reader findings rejected as false (Appendix A): workspace "event-loop blocker" (it's sync+to_thread), db "INSERT OR REPLACE bug" (already fixed).
- Codex caught: 1 overstatement (codex-loop), 2 misses (routes/tm.py async blocker, open_file safety bypass), 3 over-engineering risks (all corrected).

No code was touched — research + report only, per task constraint.
