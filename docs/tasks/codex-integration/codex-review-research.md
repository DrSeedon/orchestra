Ну конечно, самый уверенный баг оказался наполовину не багом 🙃

Ревью записано в [codex-review-research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-integration/docs/tasks/codex-integration/codex-review-research.md).

Главное:

- BUG 1: контекстная часть опровергнута для текущего CLI (`272000 × 95% = 258400`); нулевая цена подтверждена.
- BUG 2: подтверждён, но проблема шире — блокируются также `max` и `ultra`.
- MCP-gap реален, но Codex не строго global-only: поддерживается project config и `-c`.
- Гибридная стратегия разумна как пилотная политика, но её «оптимальность» пока не доказана.
- Пропущены security-блокер `--dangerously-bypass` и дефект накопления стоимости между ходами.

Проверены код, локальный каталог Codex CLI 0.144.3, официальные документы OpenAI, первичный отчёт METR и system card. Формат и whitespace-check прошли; код не менялся.

Получилось как с контекстом Sol: на вывеске миллион, а в кассе внезапно ровно 258 400 😏