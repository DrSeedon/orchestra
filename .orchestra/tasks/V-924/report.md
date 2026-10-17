# V-924 — агентские процессы первыми под global OOM

## Реализация

Локальный `run` job получает `agent_workload=True`, когда API вызван из non-orchestrator session (`X-Orchestra-Session-Id` разрешается через БД). Run с `host` автоматически этим правилом не помечается. `BgJobManager` передаёт маркер `ORCHESTRA_AGENT_WORKLOAD=1` вместе с путём cgroup; `pidfd_exec` сначала выставляет собственный `oom_score_adj=1000`, затем перемещает процесс в `agents`, до `exec`. Если cgroup необязательна и недоступна, OOM score всё равно выставляется; если cgroup помечена обязательной, запуск отказывает. Неагентские background jobs получают окружение без глобальных `ORCHESTRA_AGENT_*`, чтобы не попадать в `agents` из-за унаследованного process env.

`agent_process_options` применяет score 1000 к worker CLI и дочерним provider процессам даже на Linux-хосте без cgroup. Claude запускает non-orchestrator CLI через `agent_cli_exec`, который ставит score до cgroup join и `exec`. Codex, Grok и harness MCP передают признак orchestrator в общий helper; для orchestrator путь остаётся прежним и `oom_score_adj=800` не изменяется.

В Bash policy добавлен `ssh_agent_oom_priority`: `ssh` к `kesha@localhost` без `choom -n 1000 --` в начале remote command блокируется. Hook показывает точную исправленную команду, включая сохранённые SSH-опции; сложная удалённая shell-команда помещается внутрь `bash -lc` под `choom`. Правило `code-quality.md` приведено к той же форме.

## Уточнение V-921

Проверка исходного кода выявила неточность в атрибуции из V-921. `app.main.lifespan` записывает `ORCHESTRA_AGENT_CGROUP` в process-global окружение API; прежний `_spawn_managed_process` для `agent_workload=False` не передавал собственный `env`, поэтому `asyncio.create_subprocess_exec` наследовал эту переменную. Прежний `pidfd_exec` перемещал child в указанную cgroup каждый раз, когда переменная существовала. Значит, старый код **мог помещать и неотмеченные фоновые jobs в agents**, а отсутствие `agent_workload` в БД не доказывало `orchestra-api` cgroup. Эта предпосылка исправлена также в [отчёте V-921](../V-921/report.md).

Дамп V-921 показывает, что конкретные крупнейшие `ffmpeg` процессы использовали по 1.2–4.1 GiB swap каждый, то есть они не были в `agents` с лимитом 1 GiB; их историческую cgroup по журналу восстановить нельзя. V-924 теперь определяет принадлежность локального run явно по caller session и ставит OOM score 1000 до запуска команды. SSH job остаются вне этого cgroup-пути; их защита — правило `choom` в prompt и Bash hook.

## Тесты

До исправления committed regression tests воспроизвели дефект: `uv run --frozen python -m pytest tests/test_bg_agent_isolation.py tests/test_workflow_scheduler.py tests/test_shell_policy.py -q -k 'local_run_jobs_from_agents or provider_cli_preexec or agent_cli_oom_priority or claude_cli_wrapper_moves or pidfd_agent_run or localhost_ssh_requires'` — 6 failed, 2 passed, 75 deselected. Краснели флаг agent workload, установка score 1000 у provider CLI/PIDFD run и SSH PreToolUse. После исправления:

```text
uv run --frozen python -m pytest tests/test_bg_agent_isolation.py tests/test_workflow_scheduler.py tests/test_shell_policy.py -q
84 passed in 9.39s

uv run --frozen python -m pytest tests/test_backend_claude.py tests/test_backend_codex.py tests/test_backend_grok.py tests/test_harness_tools.py tests/test_layout_batch_v704.py tests/test_work_review_jobs.py tests/test_mcp_codex_review.py -q
307 passed in 12.92s

uv run --frozen python -m pytest tests/test_harness_production.py tests/test_model_text_control_flow.py tests/test_bash_completion.py -q
66 passed in 12.73s

uv run --frozen python -m pytest tests/test_bg_jobs.py -q
67 passed, 1 skipped in 8.37s

uv run --frozen python scripts/check_instruction_contract.py --root /home/kesha/orchestra
Instruction contract OK: AGENTS.md below 16 KiB, CLAUDE.md is a symlink to it
```

Итого: 524 passed, 1 skipped. Проверка instruction contract с корнем worktree сообщала девять отсутствующих ссылок на другие task artifacts, пропущенные sparse checkout; `git cat-file -e main:<path>` подтвердил наличие всех девяти в `main`, а полный checkout прошёл проверку. Импортированный `app`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/perf-audit/app/__init__.py`. Прогоны выполнялись последовательно, без xdist.

## Эксплуатация

Изменён Python в `app/` и системный Bash hook; после merge необходим рестарт Orchestra. Во время работы живые процессы, cgroup, unit и systemd limits не менялись. Изменение лимитов и SSH-запуски вне задачи.
