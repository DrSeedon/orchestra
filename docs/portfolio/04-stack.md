# Стек и объём Orchestra

Срез выполнен 28.08.2026 на зафиксированном дереве:

```console
$ git rev-parse HEAD
fbed73a377cce04bf7bb03c46eba6252d71bdda0
```

Ниже числа относятся к репозиторию и рабочему контуру, а не к объёму кода, написанного Максимом вручную: задачи исполняют модели, а Git-коммиты обычно получают пользовательскую identity. Это видно, например, по прямо указанному Codex-исполнителю реализации durable Telegram delivery (`docs/tasks/333/report.md`, раздел `Review`) и по metadata автора в отчёте о коллизиях задач (`docs/tasks/406/report.md`, раздел `Review route`).

## Технологии

| Слой | Что используется | Якорь |
|---|---|---|
| Backend | Python `>=3.12`, FastAPI, Uvicorn, Jinja2, HTTPX | `pyproject.toml:1-14` |
| Агентные runtime | `claude-agent-sdk==0.2.114`; Codex CLI `app-server --stdio`; Grok CLI; собственный OpenRouter Harness | `pyproject.toml:6`; `app/runtime_registry.py:171-327`; `app/runtime_registry.py:330-388` |
| Контракт runtime | structural `BackendLike`: `connect`, `send`, поток `events`, `interrupt`, `disconnect`; отдельная матрица capabilities | `app/backend_protocol.py:8-16`; `app/runtime_registry.py:29-53` |
| Хранилища | SQLite для operational state/logs/очередей; Git-canonical JSON для задач и знаний; SQLite/FTS/vector как производные проекции | `app/db.py:45-141`; `app/ia/task_store.py:1`; `app/ia/task_store.py:308-351`; `app/ia/runtime.py:402-408` |
| UI и transport | server-rendered Jinja2, HTML/CSS/JavaScript, SSE; Telegram через aiogram | `pyproject.toml:9`; `pyproject.toml:15-19`; `app/routes/sessions.py:572-592` |
| Тестирование | pytest, pytest-asyncio, pytest-timeout, Playwright | `pyproject.toml:35-41` |
| Эксплуатация | systemd socket activation, Nginx template, Docker/Compose, GitHub Actions | `deploy/orchestra.service:1`; `deploy/orchestra.socket:1`; `deploy/nginx.conf.template:1`; `Dockerfile:1`; `.github/workflows/ci.yml:1` |

Проверка зависимостей:

```console
$ sed -n '1,41p' pyproject.toml | grep -E 'requires-python|claude-agent-sdk|fastapi|uvicorn|jinja2|mcp>|httpx|aiogram|pytest'
requires-python = ">=3.12"
    "claude-agent-sdk==0.2.114",
    "fastapi>=0.115,<1.0",
    "uvicorn[standard]>=0.34,<1.0",
    "jinja2>=3.1,<4.0",
    "mcp>=0.1,<2.0",
    "httpx>=0.27,<1.0",
    "aiogram>=3.28,<4.0",
    "pytest>=8.0,<10.0",
    "pytest-asyncio>=0.24,<2.0",
    "pytest-timeout>=2.3,<3.0",
    "pytest-playwright>=0.6,<1.0",
```

## Размер исходников

Команда считается по tracked-файлам зафиксированного выше Git-дерева. `app/*.py` — production Python; `tests/**` — тестовый слой целиком; frontend — tracked-файлы под `app/static/` и `app/templates/`.

```console
$ set -o pipefail
$ git ls-files | wc -l
16578
$ git ls-files -z | xargs -0 cat | wc -l
1208848
$ git ls-files 'docs/**' | wc -l
16203
$ git ls-files 'app/*.py' | wc -l
99
$ git ls-files 'app/*.py' | xargs cat | wc -l
67694
$ git ls-files 'tests/**' | wc -l
179
$ git ls-files 'tests/**' | xargs cat | wc -l
88202
$ git ls-files 'app/static/*' 'app/templates/*' | wc -l
22
$ git ls-files 'app/static/*' 'app/templates/*' | xargs cat | wc -l
15608
$ find docs/tasks -mindepth 1 -maxdepth 1 -type d | wc -l
423
```

Итого защищаемый срез: 67 694 строки production Python, 88 202 строки tracked-тестов и 15 608 строк frontend. Число 1 208 848 нельзя называть размером продукта: 16 203 из 16 578 tracked-файлов находятся в `docs/`, включая разложенные записи знаний и сырые task-артефакты. Якорь — вывод команды выше.

## Трекер задач: что именно считается

`docs/tasks/` — каталог доказательств, а не реестр завершений. Текущий project-scoped вызов трекера дал:

```text
task_list(project="orchestra")
returned_tasks=263
unique_pars=263
by_status={new: 100, in_progress: 14, done: 145, cancelled: 4}
```

Поэтому для резюме допустима формулировка «145 завершённых записей в трекере Orchestra на 28.08.2026», но не «423 выполненные задачи». Якорь — фактический вывод `task_list(project="orchestra")` этого среза; project-scoped контракт выдачи находится в `app/mcp_stdio.py:2839-2856`.

## История Git и чужой код

```console
$ git remote -v
enterprise  git@github.com:DrSeedon/orchestra-enterprise.git (fetch)
enterprise  git@github.com:DrSeedon/orchestra-enterprise.git (push)
origin      https://github.com/DrSeedon/orchestra.git (fetch)
origin      https://github.com/DrSeedon/orchestra.git (push)
vadim       https://github.com/mccalpink/orchestra.git (fetch)
vadim       https://github.com/mccalpink/orchestra.git (push)
$ git rev-list --count main
2546
$ git rev-list --count --merges main
255
$ git log main --format='%aN <%aE>' | sort | uniq -c | sort -nr
1842 Maxim <65215214+DrSeedon@users.noreply.github.com>
 684 DrSeedon <katyas16k.ks@gmail.com>
  20 vadimd <didenko.it.ai@gmail.com>
```

Все 2 546 достижимых из `main` коммита распределяются по этим трём author identities: 2 526 — `Maxim`/`DrSeedon`, 20 — `vadimd`. Последние 20 — явно чужой вклад из контура `vadim`; они затрагивали, среди прочего, `app/auth.py`, `app/manager.py`, `app/mcp_stdio.py`, `app/tg_bridge.py`, `app/workspace.py` и соответствующие тесты. Это не даёт права назвать 2 526 коммитов ручной работой Максима: Git author identity не различает его правки и squash-коммиты работавших под его управлением моделей. Якорь — вывод команды выше и `git log main --author='vadimd <didenko.it.ai@gmail.com>'` (20 строк).

## Наблюдаемый operational scale

Read-only запрос выполнен к живой `data/orchestra.db`, путь получен через Git common dir; WAL не копировался и данные не менялись.

```console
$ repo_root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
$ REPO_DB="$repo_root/data/orchestra.db" python3 - <<'PY'
import os, sqlite3
con = sqlite3.connect(f"file:{os.environ['REPO_DB']}?mode=ro", uri=True)
for table in ('sessions', 'logs', 'turn_usage', 'bg_jobs', 'message_deliveries'):
    print(f'{table}={con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]}')
print('scopes=' + repr(con.execute('SELECT count(distinct scope) FROM sessions').fetchall()))
print('session_statuses=' + repr(con.execute(
    'SELECT status,count(*) FROM sessions GROUP BY status ORDER BY status').fetchall()))
print('backend_types=' + repr(con.execute(
    'SELECT backend_type,count(*) FROM sessions GROUP BY backend_type ORDER BY backend_type').fetchall()))
print('log_span=' + repr(con.execute('SELECT min(ts),max(ts) FROM logs').fetchall()))
PY
sessions=556
logs=206555
turn_usage=5619
bg_jobs=58
message_deliveries=407
scopes=[(21,)]
session_statuses=[('archived', 450), ('idle', 103), ('running', 2), ('waiting', 1)]
backend_types=[('claude', 334), ('codex', 221), ('grok', 1)]
log_span=[('2026-07-27T17:59:27.218367+00:00', '2026-08-28T11:02:18.095226+00:00')]
```

Это масштаб накопленного контура, не concurrent load и не число пользователей. Реальная проверенная конкурентность вынесена в `03-measurements.md`: процессы и сохранённые sessions нельзя подменять числом одновременно работающих model turns (`docs/tasks/255/measurements.md`, раздел `Coverage and boundaries`).

## Что изменилось относительно цифр из постановки

- Тесты: 88 202 строки, а не 87 559 — тот же pathspec, текущий `HEAD`; вывод команды выше.
- Frontend: 15 608 строк, а не 15 606 — тот же pathspec; вывод команды выше.
- `docs/tasks`: 423 каталога, а не 427; это всё равно не метрика завершений.
- Git: 2 546 коммитов, а не 2 545; из них 20 имеют foreign author identity `vadimd`.
