# #243 — отчёт

## Итог

Консервативный флаг был неверен. Codex CLI 0.146.0 возобновил один Sol thread на Luna и
Spark, сохранил тот же thread id и дословно вспомнил UUID из старого user turn. Orchestra
теперь оставляет native thread при смене модели внутри runtime `codex`; межрантаймовые ветки
и их history import не менялись.

## Изменения

- `app/runtime_registry.py`: `codex.resume_across_models=True`.
- `tests/test_runtime_registry.py`: capability закреплена явно.
- `tests/test_session.py`: same-runtime смена сохраняет `session_id`, не строит handoff, не
  пишет id в history и создаёт следующий backend с новой моделью плюс старым native id.
- `docs/tasks/243/probe_cross_model_resume.py`: воспроизводимый изолированный canary.
- `docs/tasks/243/probe-results.json`: literal Sol→Sol / Sol→Luna / Sol→Spark результаты.
- `docs/tasks/243/probe-spark-overflow.json`: literal fail-loud Spark overflow.
- `docs/tasks/243/research.md`: метод, числа, контрдоказательства и границы.
- `docs/tasks/243/codex-review-impl.md`: два раунда зрячего ревью.

## Прямые измерения

Codex 0.146.0, один seed thread `019ff9b0-8c7e-7d72-b1b0-80c7c72494bd`, UUID находился
только в первом user turn:

| Ветка от Sol seed | returned id тот же | UUID вспомнился | input / cached | cache hit |
|---|---:|---:|---:|---:|
| Sol→Sol | да | да | 33 651 / 31 488 | 93.57% |
| Sol→Luna | да | да | 38 310 / 5 888 | 15.37% |
| Sol→Spark | да | да | 35 761 / 5 504 | 15.39% |

История переносится, но первый changed-model ход почти cold: Luna получила 32 422 fresh input
tokens против 2 163 у Sol control. При этом API-equivalent стоимость Luna была ниже:
$0.00669456 против $0.027489. Для Spark цена неизвестна и не выдумывалась.

Spark ниже своего runtime-reported effective окна `121 600` продолжил нить. Отдельный Sol
thread с `132 343` context tokens Spark принял по id, но первый ход завершил громко:
`model_error=context_window`, `input_tokens=0`; auto-compact не сработал.

## Проверки

- Focused regressions:
  `uv run --active pytest -q tests/test_runtime_registry.py tests/test_session.py::TestRuntimeCapabilities tests/test_backend_codex.py::test_resume_rejects_substituted_thread_before_turn`
  → `17 passed in 6.14s`.
- Production-seam subset после review-fix:
  `uv run --active pytest -q tests/test_runtime_registry.py tests/test_session.py -k 'builtin_runtime_capabilities_are_explicit or codex_model_switch_preserves_native_thread'`
  → `2 passed, 218 deselected in 5.17s`; ревьюер повторил →
  `2 passed, 218 deselected in 4.81s`.
- Мутация `codex.resume_across_models=True → False`: оба целевых теста покраснели
  (`2 failed`, `mutant_rc=1`); после восстановления → `2 passed`.
- JSON артефакты разобраны `python3 -m json.tool`; probe компилируется; secret-shape scan
  (`y0_`, `sk-or-v1-`, `ya29.`, GitHub, Google, Bearer) → 0.
- Полный сьют не запускался по прямому ограничению задачи.

## Codex review

Раунд 1: `APPROVED`, два suggestions — закрыть production reconnect seam тестом и исправить
ложную последовательность веток в исследовании. Оба приняты.

Раунд 2: `APPROVED — no blocking crash, context-loss, corruption, or unsafe-silent behavior
found.` Ревьюер подтвердил production seam; последнюю consistency-suggestion в прозе исправили
без третьего раунда.

## Pre-mortem

| Возможная регрессия следующего потребителя | Симптом | Проверка |
|---|---|---|
| Старый id потерялся в `change_model` | новый чистый thread / handoff | session oracle + мутация capability |
| Новая модель не доехала в backend | resume старой моделью | `build_backend` получает new model и old id |
| Cross-runtime reset случайно отключён | Claude↔Codex смешивает native ids | predicate не менялся; `TestRuntimeCapabilities` focused suite |
| Canary читает UUID из текущего prompt | ложный semantic pass | финальный UUID только в seed user turn; первый дефектный стенд исключён |
| Большая Sol-нити переключена в Spark | первый ход падает | literal visible `context_window`; ограничение документировано, silent fallback нет |

## Breaking / TODO

- Breaking API: нет.
- Поведенческое изменение намеренное: same-runtime Codex model switch сохраняет native id и
  больше не строит lossy handoff.
- Остаётся сознательное ограничение: Orchestra пока не блокирует заранее переход в Spark,
  когда текущий контекст больше окна Spark; провайдер отказывает громко на первом ходе.
