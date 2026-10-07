# V-742 — детерминированность дневной аналитики usage

| Пункт | Исход | Доказательство |
|---|---|---|
| Падение `test_daily_usage_applies_provider_cache_ttl` | Исправлено в тесте; production-код не менялся | События теперь стоят в `00:05`, `00:36` и `01:37` одного UTC-дня. Тест параметризован для SQLite-часов `00:30` и `12:00`; оба варианта проходят. |
| Аналогичные `now - timedelta(hours=...)` в `test_usage_*` | Найдены, но не требуют изменения | Поиск охватил все 7 `tests/test_usage_*.py`. Другой совпавший сценарий — `test_analytics_snapshot_has_one_consistent_provider_breakdown` — использует окно в 7 дней и суммирует дневные строки, поэтому переход через полночь не меняет его результат. Сценарии в `test_usage_history_resolution.py` проверяют временную сетку истории, а не дневную группировку. |

Причина была в фикстуре теста: при запуске около полуночи события, созданные за 3 часа до запуска, оказывались во вчерашнем дне. `daily_usage(days=1)` отбирает строки с сегодняшней UTC-датой, после чего агрегирует их по дню. Такая граница корректна; менять production-код означало бы изменить контракт «последний календарный день» ради тестовой фикстуры.

Часы SQLite в регрессионном тесте фиксируются через `date('now', ...)` для двух требуемых значений времени. Сами три seed-события находятся в одном дне и сохраняют интервалы, нужные для проверки TTL, cold starts и разбивки провайдеров.

Проверки:

- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_usage_analytics.py -k daily_usage_applies_provider_cache_ttl -q` — 2 passed; проверены значения 00:30 и 12:00 UTC.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_usage_analytics.py tests/test_usage_analytics_frontend.py tests/test_usage_contract.py tests/test_usage_history_frontend.py tests/test_usage_history_resolution.py tests/test_usage_readiness.py tests/test_usage_snapshot.py -q` — 88 passed.
- Импортированный модуль: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/usage_analytics.py`.
