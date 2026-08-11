# Личная память — Orchestra-orchestrator

- `GET /api/usage` отдаёт `utilization` в ПРОЦЕНТАХ (0–100), не долей. `five_hour.utilization: 1.0` = 1%, а не «выжрано». 11.08 объявил юзеру «Claude 5h выжран в ноль» при реальных 1% и зря увёл задачу на Sol. Порог тревоги — от 80.
- Не тянуть `logs.content` из БД без `substr(content,1,200)`: один запрос на 6 строк вывалил в контекст три полных копии `session.py`. Для дат/фактов хватает `ts` + первых 200 знаков.
- Снимок живой `data/orchestra.db` — только `sqlite3.Connection.backup` (WAL), и это работает: `sqlite3.connect("file:data/orchestra.db?mode=ro",uri=True)` → `.backup(dst)`.
