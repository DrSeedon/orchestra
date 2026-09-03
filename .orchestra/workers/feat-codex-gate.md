# feat-codex-gate — личная память

## Orchestra: состояние квот провайдера

- **Единственное решение «есть ли ёмкость» — `provider_readiness(envelope, provider, now=)`
  в `app/limit_wake.py:123`.** Докстринг прямо говорит «the single capacity decision used by
  planning and delivery». Потребители: `build_wake_plan` и `run_wake_job`. Заводить свою
  проверку `utilization >= 100` — значит делать третью копию (вторая уже есть:
  `_claude_subscription_limit_active`, `app/session.py:67`, anthropic-only, на сырых данных).
- `state: "unavailable"` означает **«не знаю»**, а не «занято». Полярность выбирает потребитель:
  `limit_wake` не действует, fail-open-гейт — действует.
- Модель → провайдер: `_provider_for_model` (`app/limit_wake.py:35`). У Codex ДВА независимых
  окна: `codex` (Sol/Terra/Luna) и `codex_spark`. Замер 07.08.2026: `codex` 100%, `spark` 1% —
  «гейт по рантайму codex» убил бы полностью рабочий Spark.
- Свежий поход к квотам Codex — ~1.0–1.25 с (поднимает `codex app-server` подпроцессом),
  чтение кеша — 9 мс, TTL кеша и период фонового снимка — по 300 с
  (`_USAGE_CACHE_TTL`, `SNAPSHOT_INTERVAL` в `app/routes/system.py`).

## Доставка сообщений: route — НЕ узкое место

`manager.send` (`app/manager.py:918`) зовут **11 мест**, HTTP-route среди них одно.
Мимо route идут: `tg_bridge.py:377` (юзер из Telegram), пять пробуждений `bg_jobs`,
два `notify`, `limit_wake`. Ставишь что-либо «на все доставки» — целься в `manager.send`,
проверив грепом, а не в `POST /api/sessions/{name}/send`.

## Прогнать код воркер-дерева против ЖИВЫХ данных

Скрипт в `/tmp` + `sys.path` на worktree тянет `app.db` из worktree, где `data/orchestra.db`
пустая → `OperationalError: no such table: sessions`, и это выглядит как баг твоего кода.
`DB_PATH` считается от файла модуля, а НЕ от cwd. Правильный вызов:

```bash
ORCHESTRA_DB_PATH=/home/kesha/orchestra/data/orchestra.db \
  python3 /tmp/scratch.py    # + load_dotenv('/home/kesha/orchestra/.env')
```

`current_provider_usage` тянет весь `_get_usage_data`, включая SELECT по `sessions` —
поэтому БД нужна даже там, где речь только о квотах.

## Как быстро воспроизвести отказ Codex по квоте

```bash
cd /tmp && timeout 90 codex exec --skip-git-repo-check --full-auto --json - <<< "say ok"
```
Вернёт `EXIT=1` и JSONL со строкой `You've hit your usage limit … try again at <дата>`.
Время в этой строке — **локальное, без пометки зоны**; то же самое значение лежит в
`account/rateLimits/read` как `resetsAt` (unix-секунды) — брать надо оттуда.
