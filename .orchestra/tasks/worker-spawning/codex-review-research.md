Ну вот, несколько «CONFIRMED» всё-таки оказались CONFIDENTLY WRONG 😏

Ревью записано в [codex-review-research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-worker-spawning/docs/tasks/worker-spawning/codex-review-research.md).

Главное:

- F1.3 подтверждён кодом и реальными `local_agent` запусками worker-а в SQLite.
- Kill-cascade действительно отсутствует; live orphan cleanup не удалит.
- F7 про nested subagents и depth=5 противоречит текущей официальной документации.
- Worktree детей обычно sibling, но абсолютное «nesting невозможно» неверно; также возможны slug/path collisions.
- R4 — реальный баг, но target не hardcoded: это неудачный default. Merge в `main` переносит совокупную работу родителя и ребёнка.
- Исторические dangling orphan-ы не доказывают отсутствие cascade: обычный kill архивирует parent row, а не удаляет его.
- Утверждение «любого воркера» верно только внутри текущего scope.
- Экономия built-in Agent пока гипотеза без A/B-измерения.

Проверял код, установленный Claude CLI `2.1.197`, актуальные официальные docs и read-only snapshot Orchestra DB. Архитектура устояла, но несколько несущих табличек были прикручены к воздуху. 🔩