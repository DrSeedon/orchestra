# fix-ci-green — личная память

- **Рабочий каталог Bash СОХРАНЯЕТСЯ между вызовами.** Один `cd .orchestra/tasks/... && ...`
  увёл меня в подкаталог, и следующие три вызова падали `No such file or directory`, читаясь как
  «файла нет». Всегда либо абсолютный путь, либо `cd <worktree> && ...` в той же команде.
- **`pgrep -af pytest` ловит МОЙ СОБСТВЕННЫЙ процесс claude** — слово `pytest` есть в системном
  промпте, а он целиком лежит в `argv`. Вывод — 200+ КБ мусора в контекст. Проверять процесс по
  pid (`ps -p <pid>`) или по `/proc/<pid>/cmdline` с `cut`.
- **Прошлая сессия может оставить ЖИВОЙ процесс.** 05.09 нашёл висящий 2 ч 07 м `pytest` шарда и
  осиротевший `uvicorn --port 33915` из своего worktree. Первое действие при подхвате чужой/своей
  прерванной работы — `ps -o pid,etime,cmd`, а не чтение логов. Любой мой длинный прогон теперь
  обязан идти под `timeout --kill-after=60 900`.
- **Локальный зелёный про CI не значит ничего** (#515: 57 падений на CI против 33 локально при
  одной раскладке). Приёмка — только живой прогон; `gh run view <id> --log --job <job-id>` даёт
  полный лог джоба, `gh run view <id> --json jobs` — их id.
- **Правило формата фактов в `.orchestra/kb/` берётся из `scripts/check_kb_contract.py`, а не из
  промпта.** В промпте написано `искать:` и `·`, валидатор требует
  `` - `fact:key` — claim · search: `якорь` · evidence: … ``. Прогонять
  `git diff -- .orchestra/kb/<файл> > /tmp/p.patch && uv run python scripts/check_kb_contract.py
  --root .orchestra/kb --diff /tmp/p.patch` ДО коммита.
- **`codex_review` может прийти как `[Background job FAILED] … execution never happened` при
  ПОЛНОМ артефакте на диске.** 05.09 так пришло настоящее ревью с двумя верными blocking. Сперва
  `ls -l` и `grep -c "blocking:"` по `output`-файлу, и только потом верить статусу. Раунд при
  этом ПОТРАЧЕН — перезапускать нельзя.
- **`tests/test_grok_usage_frontend.py` пишет PNG в трекнутый `.orchestra/tasks/356/`** — после
  каждого прогона дерево грязное. Перед коммитом `git checkout -- .orchestra/tasks/356/`.
