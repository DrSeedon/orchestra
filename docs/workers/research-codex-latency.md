# research-codex-latency

- Копия state DB не изолирует provider history, если в ней остаются абсолютные пути: перед запуском на копии переписать путь на scratch и проверить строку в БД. В #240 Codex `threads.rollout_path` сохранил путь к исходному JSONL; один диагностический turn пришлось восстанавливать по заранее измеренной границе файла.
- Для historical Codex concurrency брать native rollout `task_started→task_complete`, а не DB status `codex turn=... started`: после restart последний replay-запаздывает на часы (max 13 507.561 с в #255) и создаёт невозможные интервалы короче собственного TTFT.
- Для historical Codex config change point брать `task_started.model_context_window` у каждого turn: текущий managed `config.toml` переписывается позже и его mtime/content ретроактивно не доказывает ceiling прошлого хода. В #312 native rows дали чистую границу 258 400→828 400 через рестарт.
