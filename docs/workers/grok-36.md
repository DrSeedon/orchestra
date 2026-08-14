# grok-36

- `#36`: `validate_spawn` fail-open существовал только чтобы пропустить неизвестную роль. После фикса режимы на этом шве совпадают; `can_spawn: ['*']` = любая *известная* роль.
- Контракт дыры жил в `tests/test_pipeline.py` и `tests/test_default_pipeline.py` (`test_fail_open_unknown_*_passes`). Меняешь семантику — эти имена больше не истина, читай текущий `validate_spawn`.
