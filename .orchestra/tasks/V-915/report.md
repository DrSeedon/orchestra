# V-915 — осиротевшие процессы run-заданий после рестарта

## Механизм (код + journalctl, только чтение)
- `orchestra.service`: `KillMode=process` (systemd шлёт сигнал только главному pid, дети живут по задумке #230).
- run-задание порождается `_spawn_bg_process`: `start_new_session=True`, отдельная группа процессов; убивает её только `BgJobManager.shutdown()` / `_kill_proc` из этого же процесса.
- Рестарт 09:20 (старый pid 2734821): в журнале после 09:20:50 нет ни «Shutting down», ни bg_jobs-строк, сразу `Started server process [3032058]` в 09:21:06 → старый процесс оборван, `shutdown()` не выполнялся (аналогично 09:35). Новый процесс в `restore_from_db` только пометил run-задания INTERRUPTED (`bg_job …: interrupted → notified …`), группу не трогал.
- Подтверждено живыми процессами (ppid=1, свой pgid=sid): см. ниже.

## Живые сироты на момент проверки (17.10, ничего не убивал)
| pid (лидер группы) | задание | цель | команда |
|---|---|---|---|
| 2995725 (+ потомок ssh 2995730) | bg-43cf817866, timeout 14400s | bench-evals-pilot | `/bin/sh -c ssh -o BatchMode=yes kesha@localhost '… nice -n 15 python3 …'` |
| 3025342 (+ потомок 3025345 wf_run.py) | bg-d19aba5e12, timeout 3600s | bench-reviewer | `env ORCHESTRA_TASK_ID=V-909 … python scripts/wf_run.py --spec …` |
Процессы заданий bg-3e1a147400 (3025149) и bg-ce39ee06f3 (3083620) уже завершились сами.

## Решение
Присоединиться к осиротевшему процессу невозможно (канал stdout к умершему родителю потерян, результат не собрать), поэтому «убить группу и честно написать INTERRUPTED». Запись `_process` (pid + start ticks) делается в `_run_exec`, остановка — `_reap_orphan_run` в `restore_from_db` (ветки interrupted и просроченных run). Причина самой оборванной остановки (зависший graceful shutdown) не исследовалась — отдельный вопрос.

## Проверка
`tests/test_bg_jobs.py::test_v915_restart_stops_orphaned_run_process_and_reports_honestly`: реальный `sleep 300 & wait`, «падение» старого менеджера без shutdown, новый менеджер `restore_from_db` → группа процессов мертва, задание failed, агент получил единственный INTERRUPTED с «остановлен». Без правки тест красный (процесс не записан, AssertionError).
