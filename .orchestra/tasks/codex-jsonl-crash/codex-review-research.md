Ну да, fail-soft оказался fail-hard с неправильным типом исключения 😏

Ревью записано в [codex-review-research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-integration/docs/tasks/codex-jsonl-crash/codex-review-research.md).

Главное:

- Root cause 64 KiB подтверждён.
- `async for` наружу бросает `ValueError`, а не `LimitOverrunError`.
- Reader не умирает, но цикл нужно явно возобновлять через `while + readline()`.
- В текущем `backend_codex.py` параметра `limit` вообще ещё нет.
- 16 MiB разумны для MVP, но «99%» не доказано.
- Chunked-read без собственного cap может закончиться OOM.
- Официальный beta SDK и Sol 1.05M/272K подтверждены по [Codex SDK docs](https://learn.chatgpt.com/docs/codex-sdk#python-library) и [Sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol).

Проверил CPython-семантику экспериментом, структуру документа и whitespace. Код не менял.

Получилась прекрасная страховка: лимит выбрали, исключение назвали — осталось только вставить всё это в настоящий backend 🫠