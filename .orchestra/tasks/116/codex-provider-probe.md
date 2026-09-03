# #116 T2 — Codex same-thread developer-instruction probe

Дата пробы: 2026-08-01 16:27–16:28 +07:00.

## Verdict: FAIL

`thread/resume` с изменённым `developerInstructions` **не заменил** instruction,
уже загруженную в существующий Codex thread. Две независимые последовательности
сохранили исходный thread id, прошли ALPHA continuity control, получили BETA только
в `thread/resume`, но следующий turn снова дословно ответил ALPHA.

Следствие для #116: Codex-ветка same-thread authoritative refresh в T3 не
реализуется. Обычный reconnect/resume того же thread недостаточен. До создания
нового native thread/session Codex получает видимый `new_thread_required` stale
status; память и статические правила не подмешиваются user-tail как обходной путь.

## Предзаданный критерий

Для каждого из двух независимых thread:

1. `thread/start(developerInstructions=ALPHA_<nonce>)` + user `Reply now.` должен
   ответить exact ALPHA.
2. Disconnect, затем `thread/resume` того же id с тем же ALPHA; тот же user input
   должен снова ответить exact ALPHA. Это continuity control.
3. Disconnect, затем `thread/resume` того же id с `BETA_<nonce>`; тот же user input,
   не содержащий BETA, должен ответить exact BETA.

Только 2/2 полных последовательности дают PASS. Любой содержательный mismatch даёт
FAIL. Transport/quota failure не считается provider verdict и требует повторного
запуска; единственный setup-failure до model turn (`ModuleNotFoundError: app`) был
исправлен через `PYTHONPATH` и в выборку не входил.

## Среда и воспроизведение

- Orchestra commit перед пробой: `57ece1ac00ea491a526f44ed0bdbb7cbf4331330`.
- Codex CLI: `0.145.0`; model: `gpt-5.6-sol`; effort: `low`.
- Transport: реальный `codex app-server --stdio` через production
  `app.backend_codex.CodexBackend`; пустой temp cwd, без MCP servers.
- Probe source: `/tmp/codex-refresh-probe.iLuCjl/probe.py`, SHA-256
  `41a2fddc6c9c934a87968cfe773348fc142def7299e1b78b9db5e318a0d33fa1`.
- Completed background job: `bg-370725b9ce`.
- Команда:

```bash
PYTHONPATH=/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness \
UV_CACHE_DIR=/tmp/uv-cache \
uv --directory /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness \
run python /tmp/codex-refresh-probe.iLuCjl/probe.py \
  /tmp/codex-refresh-probe.iLuCjl/workspace
```

Probe subclass записывал только четыре selected request fields:
`method`, `thread_id`, `developer_instructions`, `user_input`. Для каждой
последовательности выполнялся один и тот же код:

```python
first = await one_turn(cwd, prompt_alpha, None, request_log)
control = await one_turn(cwd, prompt_alpha, first["thread_id"], request_log)
changed = await one_turn(cwd, prompt_beta, first["thread_id"], request_log)
passed = (
    first["thread_id"] == control["thread_id"] == changed["thread_id"]
    and first["answer"] == alpha
    and control["answer"] == alpha
    and changed["answer"] == beta
    and all(beta not in json.dumps(row.get("user_input")) for row in request_log)
)
```

Официальный Codex manual документирует, что `thread/resume` продолжает сохранённый
thread, возвращает shape `thread/start` и принимает те же configuration overrides,
но не обещает, что изменённый developer instruction заменяет уже загруженный
priority state. Поэтому request schema сама по себе не была доказательством; ответ
дал provider experiment. Источник: [Codex App Server manual](https://learn.chatgpt.com/docs/app-server.md).

## Raw selected results

| Sequence | Thread id | start | control resume | changed resume | Result |
|---|---|---|---|---|---|
| 1 | `019fbca6-9a1d-74a0-907d-584c900e5fc5` | exact `ALPHA_1_92ad…1388` | exact `ALPHA_1_92ad…1388` | exact `ALPHA_1_92ad…1388`, expected BETA | FAIL |
| 2 | `019fbca7-007b-76f1-9244-96e532f1d45c` | exact `ALPHA_2_b3c5…8620` | exact `ALPHA_2_b3c5…8620` | exact `ALPHA_2_b3c5…8620`, expected BETA | FAIL |

Во всех шести `turn/start` user input был ровно `Reply now.`. Recorder подтвердил,
что BETA находился только в соответствующем `thread/resume.developerInstructions`;
thread id до и после resume совпал. Rollout каждого thread содержит один initial
developer ALPHA и три assistant ALPHA; BETA в model-visible rollout не появился.

Selected rollout files:

- `/home/maxim/.codex/sessions/2026/08/01/rollout-2026-08-01T16-27-42-019fbca6-9a1d-74a0-907d-584c900e5fc5.jsonl`
- `/home/maxim/.codex/sessions/2026/08/01/rollout-2026-08-01T16-28-09-019fbca7-007b-76f1-9244-96e532f1d45c.jsonl`

## Token/cache price

| Sequence | Input | Cached input | Fresh input | Output |
|---|---:|---:|---:|---:|
| 1 | 55,593 | 40,192 | 15,401 | 87 |
| 2 | 55,581 | 47,360 | 8,221 | 81 |
| **Total** | **111,174** | **87,552** | **23,622** | **168** |

Aggregate cache share: 78.8%. При project pricing для `gpt-5.6-sol` это примерно
`$0.167` API-equivalent; реальная работа шла по подписке. Изменённый resume имел
97–98% cache hit, но высокий cache hit не означал обновление instructions — ответ
остался ALPHA.

## Решение по следующим тикетам

- T3 реализует authoritative hot refresh только для Claude.
- Codex detector остаётся общим и fail-visible; действие —
  `new_thread_required`, без автоматической потери/переноса native context.
- T4 skill-catalog для Codex может синхронизировать disk bytes, но применённым в
  model state считается только после создания нового thread; hash на same-thread
  resume не продвигается.
