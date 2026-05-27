# Orchestra Bug Reports (from agents)

## Open

### merge_worker fails with "unrelated histories" for separate repos
- **Reporter:** Parsing-orchestrator (2026-05-19)
- Worktree created from parent project's git, but worker pushes to separate repo → fatal
- **Workaround:** push to master directly, skip merge_worker

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
