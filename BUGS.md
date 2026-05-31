# Orchestra Bug Reports (from agents)

## Open

### ~~merge_worker fails with "unrelated histories" for separate repos~~ → Fixed
- **Reporter:** Parsing-orchestrator (2026-05-19)
- **Fix:** cherry-pick fallback — `git merge-base` detects unrelated histories before merge, uses `_cherry_pick_branch()` instead

### send_message к idle воркерам возвращает 500 после рестарта
- **Reporter:** Parsing-orchestrator (2026-05-26)
- После restart, send_message к существующим idle воркерам = 500. Свежие воркеры работают
- Фиксы в main.py (global exception handler, ensure_loaded в try/except) не помогли — ошибка до HTTP слоя
- **Workaround:** respawn воркера

## Fixed (v2.8.0)

- ~~Worktree .git → несуществующий путь seedon-site~~ — одноразовый баг после rename
- ~~Codex zombie 7-9 часов~~ — heartbeat + finally в codex_turn_loop (#11)
- ~~Compact running crash~~ — guard + disabled button (#12)
- ~~report_bug permission denied~~ — через API endpoint (#13)
- ~~TG иконка ⚡→☕️ не возвращалась~~ — turn ended лог (#14)
- ~~cost_usd overcounting x85~~ — CLI cumulative vs delta fix
- ~~TG сообщения обрезались молча~~ — _split_message chunking
- ~~TG flood теряет сообщения~~ — retry + priority system

## Fixed (v2.9.0)

- ~~task_update "Balance mismatch" crash~~ — `_sanity_check` now warns instead of crashing. Root cause: mass task deletion left orphaned allocations → computed vs stored divergence

## [2026-05-31 09:20 UTC] Worker sends DONE report to seedon-orchestrator instead of spawning agent
- **Reporter:** seedon-orchestrator
- **Scope:** /mnt/data/Projects/Python/seedon
Researcher worker was spawned by seedon-orchestrator (me, the PM orchestrator in main session). But it set parent_name=seedon-orchestrator and sent its DONE message to seedon-orchestrator instead of me. The spawning agent (me) never received the completion report.

Root cause: spawn_worker sets parent based on session context. Since I'm running as seedon-orchestrator, the worker correctly identifies parent. But the worker should send DONE to whoever gave it the task, not just to parent_name.

In this case the worker completed and hibernated without me knowing — I had to check logs manually to see results.
