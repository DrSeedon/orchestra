# #208 — KILL_SAFE аудит `bench201-x`

Проверено 17.08.2026 против принятого в `main` коммита #201 `a085d858`.

## Состояние ребёнка

- `worker_wip("bench201-x")`: `idle`, незакоммиченных файлов нет, один незамерженный коммит.
- `git -C .../bench201-x status --porcelain` → пусто.
- Единственный commit: `d11f1723ad1ac785c4f205fb3fb6156a6e0d3639` —
  `#201: price Codex cache writes and fail on unpriced Spark`.
- `git merge-base --is-ancestor a085d858 main` → exit `0`: принятый результат физически в main.

## Код и тесты

`git diff a085d858 task-201/bench201-x -- app/backend_codex.py tests/test_backend_codex.py`
показывает, что ветка ребёнка не содержит поведения, отсутствующего в принятой версии:

- обе версии задают cache-write ставки Sol/Terra/Luna `6.25/2.50/0.25`, вычитают writes из
  fresh input и отдельно тарифицируют их;
- обе регистрируют Spark как `None` и поднимают `ValueError` вместо молчаливого `$0`;
- принятая версия дополнительно протягивает `cache_write_input_tokens` через rollout context,
  rollout totals и `_usage_breakdown`, а в `AggregateUsage` записывает
  `cache_create_tokens=turn_cache_write`; в ветке ребёнка этой последней телеметрии нет;
- accepted report фиксирует `88 passed`, child report — `86 passed`; принятые тесты содержат
  отдельные проверки rollout totals, app-server breakdown и `cache_create_tokens`.

Поэтому переносить код или тесты из ребёнка назад означало бы ослабить уже принятую реализацию.

## 38 строк research

Три несущих утверждения `docs/tasks/201/research.md` ребёнка уже присутствуют с не меньшей
доказательностью в `main:docs/tasks/201/report.md`:

1. Cache-write ставки: accepted report дословно приводит центральную pricing-таблицу для всех
   трёх моделей и числа `$6.25/$2.50/$0.25` (строки 13–18). Child приводит модельные карточки и
   эквивалентное правило `1.25x`; нового вывода это не добавляет.
2. Spark: accepted report приводит строку `research preview` и примечание `credit rates ... are
   not final`, затем фиксирует `None` + `ValueError` (строки 20–36).
3. Long context: accepted report приводит цитату `Prompts with >272K ... for the full request`,
   явно отделяет request от thread/session/turn и объясняет, почему session-level surcharge не
   добавлен (строки 39–51). Это сильнее сокращённой формулировки ребёнка.

Итог: **уникального evidence, которое меняет или усиливает принятую #201, нет**. Содержимое
ветки полностью классифицировано; ребёнок `lifecycle=one-shot`, прислал финальный DONE, idle и
чист. После этого файла `kill_worker(force=True)` безопасен: единственный незамерженный commit
содержит только superseded code/tests и дублирующий research.
