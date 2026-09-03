# fix-restart-reliable

- В restart-тестах имя spy `kill` не говорит, какой процесс сигналят: сначала прочитать точную
  цель monkeypatch. В #411 это был `app.routes.system.os.kill` (SIGINT супервизору самому себе),
  а сохранность agent CLI требовала отдельного наблюдателя за `session.stop()`/backend process.
- Merge-gate прогоняет тестовый файл из worker-ветки: удаление stale-теста в `main` не помогает
  уже ответвлённому воркеру, тот же тест надо явно синхронизировать в его ветке до merge.
