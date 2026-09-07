<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Обнаружен blocking-риск ложного снятия тестов с merge-гейта. Выражение `-m` и CI-шарды настроены корректно; проверка пустого исходного набора также реализована через `ValueError`.

## Findings

- blocking: `tests/conftest.py:326-333` — фикстура `page` слишком общее имя. Любой небраузерный тест, объявивший локальную фикстуру `page` с другим смыслом, попадёт в `browser` через `fixturenames` и будет исключён из блокирующего набора. Та же проблема применима к `browser_context` и `dashboard_browser` при совпадении имён. Автоматическая классификация должна опираться на однозначные имена/маркер владельца, иначе это может снять реальные проверки.

## Verdict

NEEDS CHANGES.

## Round (2026-09-07T13:22:18Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Round 2

## Summary

Предыдущее замечание FIXED. В новом diff изменён только `tests/conftest.py`: `page` и `browser_context` удалены; остальные файлы поверхности не изменились.

## Findings

Нет blocking/suggestion/question. В разрешённой поверхности нет конкретного небраузерного использования `browser` или `dashboard_browser`; набор теперь ограничен однозначными именами.

## Verdict

APPROVED

Дословная строка из изменённого файла:

```python
item.add_marker("browser")
```
