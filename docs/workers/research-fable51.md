# research-fable51

- Общий provider-counter нельзя регрессировать на локальную БД, пока не перечислены ВСЕ потребители счётчика. В #437 laptop Orchestra давала 14% расхода: пропуск VPS и interactive Claude Code завысил output coefficient примерно в 9× и скрыл cache-write effect.
- SQLite ISO-text: `ts` с `T` нельзя напрямую сравнивать с `datetime()` (пробел). Cutoff формировать в Python в том же ISO-формате либо нормализовать обе стороны; иначе same-date строки проходят независимо от часа.
- Перед необратимым модельным canary коммитить decision zones и fail-closed отключать superseded harness. В #437 это сохранило Fable spend ровно 0 после двух смен sensitivity.
