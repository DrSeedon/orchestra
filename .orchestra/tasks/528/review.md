<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, даже удаление одной папки потребовало полноценного расследования 🧹

## Summary

Проверен полный diff `99f4e9f...7790f547` → `7790f547`, включая `app/manager.py`, тесты и `.orchestra/tasks/528/*`.

Блокирующих проблем не найдено. Реализация удаляет только `root / session_id`, проверяет archived-состояние в БД и отсутствие runtime-сессии; ошибки housekeeping не прерывают `remove`.

Проверка:

```text
/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_manager.py -k 'TestRemoveCliHome'
9 passed, 165 deselected
```

Дополнительно подтверждено: mutation-тест ломается без cleanup-hook, а два падения расширенного набора воспроизводятся на исходном `HEAD` и не относятся к этому изменению. Codex/Luna reviewer в текущей сессии недоступен.

## Findings

Нет blocking, suggestion или question findings.

Литеральная строка из reviewed source:

```python
shutil.rmtree(_CODEX_HOME_ROOT / session_id)
```

## Verdict

**Correct** — реализация соответствует заявленной области и проверенным lifecycle-инвариантам. Остаточный риск: полный suite не был зелёным из-за двух pre-existing failures.

Уборка прошла без пылесоса по всему дому — редкий случай, когда здравый смысл победил.
