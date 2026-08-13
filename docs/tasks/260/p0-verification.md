# #260 P0 — корреляция результатов инструментов

## Контракт

- Вызов получает `data-tool-use-id` из `payload.tool_use_id`; `_codex_item_id`
  остаётся запасным источником для нативных Codex-событий.
- Результат ищет только карточку с тем же `tool_use_id`. Совпадения нет — видна
  отдельная строка `Результат без вызова`; приклеивания к соседнему вызову нет.
- `loadMoreLogs` передаёт полный payload, поэтому старые страницы истории работают
  по тому же контракту.
- Обычный режим — default. Переключатель явно подписан `Normal` / `Compact`.

## Браузерная проверка

Playwright подменяет `app.js` файлом из worktree и сначала ждёт новый runtime-символ
`typeof _toolForResult === 'function'`.

Фикстура моделирует настоящий параллельный блок: все три вызова A/B/C записаны до
любого результата, затем результаты приходят C/A/B. У каждого результата уникальный
маркер `RESULT-ONLY-C/A/B`; тест параметризован по normal и compact renderer.

Команда:

```bash
.venv/bin/python -m pytest -q \
  tests/test_frontend.py::test_parallel_tool_results_follow_tool_use_id_in_both_renderers \
  tests/test_frontend.py::test_unmatched_tool_result_is_visible_and_never_attaches_to_another_call \
  tests/test_frontend.py::test_load_more_keeps_tool_use_id_for_old_parallel_calls \
  tests/test_frontend.py::test_tool_view_mode_is_visible_without_desktop_header_overflow
```

Результат: `7 passed`. Полоса проверена на 1280, 1440, 1680 и 1920 px: body без
горизонтального overflow, кнопка режима видима и целиком находится во viewport.

## Мутация

Точный selector в `_toolForResult` заменён на прежнее поведение «последний вызов»
при сохранённых id на карточках. Один прогон дал ровно два красных случая:

```text
FAILED ...[normal] — RESULT-ONLY-A отсутствует у parallel-a
FAILED ...[compact] — RESULT-ONLY-A отсутствует у parallel-a
2 failed
```

После отката той же точечной замены: `2 passed`. Уникальный marker исходной строки
до мутации и после отката: `1`, `1`.
