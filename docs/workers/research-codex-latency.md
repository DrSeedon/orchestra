# research-codex-latency

- Копия state DB не изолирует provider history, если в ней остаются абсолютные пути: перед запуском на копии переписать путь на scratch и проверить строку в БД. В #240 Codex `threads.rollout_path` сохранил путь к исходному JSONL; один диагностический turn пришлось восстанавливать по заранее измеренной границе файла.
- Для historical Codex concurrency брать native rollout `task_started→task_complete`, а не DB status `codex turn=... started`: после restart последний replay-запаздывает на часы (max 13 507.561 с в #255) и создаёт невозможные интервалы короче собственного TTFT.
