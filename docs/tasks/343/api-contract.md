# #343 — контракт данных правила допуска по квоте

Владелец бэкенда: `impl-quota-rule` (ветка `task-343/impl-quota-rule`).
Потребитель: `feat-quota-front` (#344), рисует то же правило на дашборде.
`app/static/` бэкендом не трогается вовсе.

## Правило (единственное)

Для пула считаются две величины в процентах:

- **норма** = `progress * 100`, где `progress` — доля окна, прошедшая по времени
  (0.0 в начале окна → 1.0 в момент сброса);
- **допуск** = линейно `10` п.п. при `progress=0` → `1` п.п. при `progress=1`,
  то есть `tolerance = 10 + (1 - 10) * progress`.

Порог гейтящейся полосы: `limit = min(99, progress * 100 + tolerance)`.

Лейны:

| lane | gated | блокируется когда |
|---|---|---|
| `claude` | да | `utilization >= 99` **или** `utilization > limit` |
| `sol` | да | `utilization >= 99` **или** `utilization > limit` |
| `luna` | нет | `utilization >= 99` |
| `spark` | нет | `utilization >= 99` |

Оркестраторы и суб-оркестраторы гейт не проходят вовсе — ни диагональю, ни на 99%.
В данных они не представлены: это свойство вызывающего, а не пула.

Правило смотрит только на текущую точку и истории не помнит.

## Пулы и окна

| bucket | окно | `progress` считается как |
|---|---|---|
| `anthropic` | `seven_day`, `window_minutes=10080` | `1 - (resets_at - now) / (7 сут)` |
| `codex` | `primary` (скользящее) | `1 - (resets_at - now) / window_minutes` |
| `codex_spark` | `primary`, СВОЙ счётчик | то же, что у `codex` |

`codex_spark` считается по собственному счётчику, а не по общему Codex: сегодня
Codex 100%, Spark 39%.

Пул воркера выбирается по рантайму его модели; Grok вне политики (`lane: null`).

## Эндпоинт

`GET /api/usage/quota-map` — единственный источник для панели. Owner-only
(как и `/api/usage`); не owner → `{"data_available": false, "error": "owner_mode_only"}`.

Пороги считает бэкенд. **Арифметику правила в JS не повторять** — `limit_pct`,
`tolerance_pp`, `progress` и вердикты приходят уже посчитанными; иначе панель
разойдётся с гейтом.

```jsonc
{
  "generated_at": "2026-08-19T12:00:00+00:00",
  "observation_max_age_seconds": 300.0,
  // Константы правила — чтобы панель рисовала ту же линию, а не свою копию чисел.
  "rule": {
    "hard_stop_pct": 99.0,
    "tolerance_start_pp": 10.0,
    "tolerance_end_pp": 1.0
  },
  "buckets": [
    {
      "bucket": "anthropic",            // "anthropic" | "codex" | "codex_spark"
      "label": "Claude",
      "observed_at": 1755600000.0,      // unix seconds; null — телеметрии нет
      "fresh": true,                    // наблюдению меньше observation_max_age_seconds
      "data_available": true,           // есть окно И числовой utilization
      "window": {                       // null, если решающего окна нет
        "id": "seven_day",
        "label": "7d",
        "window_minutes": 10080,
        "utilization": 72.0,
        "resets_at": "2026-08-25T07:00:00+00:00",
        "reset_in_seconds": 402000.0,
        "starts_at": "2026-08-18T07:00:00+00:00",  // resets_at − window_minutes
        "progress": 0.4048                          // null, если resets_at неразбираем
      },
      "reference_windows": [ /* тот же вид; 5h Claude и secondary Codex — справочно */ ],
      // Текущая точка правила. null — когда progress посчитать нечем.
      "tolerance_pp": 6.36,
      "limit_pct": 46.84,
      "lanes": [
        {
          "lane": "claude",             // "claude" | "sol" | "luna" | "spark"
          "label": "Claude-воркеры",
          "gated": true,                // false → диагональ не применяется, только 99%
          "blocked": true,
          "reason": "weekly utilization 72% is above the line limit 46.84%",
          "models": ["claude-opus-5[1m]", "claude-sonnet-5[1m]"]
        }
      ],
      "models": [
        {
          "model": "claude-opus-5[1m]",
          "label": "Claude Opus 5",
          "bucket": "anthropic",
          "lane": "claude",
          "gated": true,
          "state": "blocked",           // "available" | "blocked" | "unknown" | "not_applicable"
          "allowed": false,
          "utilization": 72.0,
          "limit_pct": 46.84,           // null у негейтящихся полос и когда progress неизвестен
          "hard_limit_pct": 99.0,
          "reason": "…"
        }
      ]
    }
  ],
  // Модели вне политики (Grok): lane=null, state="not_applicable".
  "outside_policy": [ /* тот же вид, что элементы models */ ]
}
```

### Состояния, которые панель обязана различать

- `state="unknown"` — телеметрии нет или она протухла. Это **не** «всё хорошо»:
  на неизвестной квоте гейт пропускает (fail-open), и панель должна говорить
  «данных нет», а не «работает».
- `progress=null` при `data_available=true` — `utilization` известен, а `resets_at`
  нет. Диагональ не считается, действуют только жёсткие 99%; `limit_pct=null`.
- `fresh=false` — наблюдение старше 300 с.

### Оркестратор

Отдельного поля нет: оркестраторы не блокируются никогда и ни одним значением.
Панели достаточно нарисовать это как константу (линия «предела нет»), как в
образце `docs/tasks/314/quota-line-controller.html`.

## Что удалено и на что больше нельзя ссылаться

`/api/usage` больше **не** отдаёт `quota_headroom`. Удалены целиком:
`/api/usage/quota-controller`, `/api/usage/quota-controller/policy` (GET/PUT/POST
rollback), `/api/usage/quota-controller/reserve` (POST/DELETE),
`/api/usage/routing-policy` (GET/PUT), `/api/usage/routing-policy/explain`.
В `/api/usage/analytics` больше нет ключа `quota_controller` (и блока `runway`
внутри него); ключ `quota_map` там остаётся и повторяет `/api/usage/quota-map`.

`/api/usage/readiness?model=…` остаётся: тот же вердикт, что и в момент допуска.
