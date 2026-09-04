# #478: результаты MCP-тулов доезжают до чата питоновским repr, а не JSON

Не чинил — по указанию оркестратора только локализовано и измерено.

## Точка сериализации

`app/backend_claude.py:463-478`, `_extract_tool_result`:

```python
try:
    parsed = _json.loads(text)
    if isinstance(parsed, dict) and 'result' in parsed:
        return str(parsed['result'])      # <-- Python repr, не JSON
except (ValueError, TypeError):
    pass
return text
```

MCP отдаёт корректный JSON: `mcp_tool_result` (`app/mcp_stdio.py:160-185`) кладёт
`json.dumps(result)` в текст и `{"result": ..., "error": ...}` в `structuredContent`.
Бэкенд этот JSON разбирает, достаёт `parsed['result']` — питоновский объект — и зовёт на нём
`str()`. Для dict/list это даёт `{'a': 'b', 'c': None}`: одинарные кавычки и `None`.

## Это ОБЩЕЕ поведение, а не дефект одного тула

Следствие на фронте: `JSON.parse` в `app/static/js/chat.js:3817` падает, готовая сетка
`_renderJsonGrid` (`chat.js:901`) не включается, и ответ уходит в текстовый путь `📎 ` + preview —
то самое полотно из жалобы.

Замер по боевой базе (read-only):

```
sqlite3 -readonly data/orchestra.db "
SELECT CASE WHEN content LIKE '{''%' THEN 'python_repr'
            WHEN content LIKE '{\"%' THEN 'json' ELSE 'other' END AS shape, COUNT(*)
FROM logs WHERE type='tool_result' AND content LIKE '{%' GROUP BY shape ORDER BY 2 DESC;"
```

| форма | строк |
|---|---|
| json | 14 241 |
| python_repr | **1 397** |
| other | 893 |

Распределение python_repr по первому ключу — не менее 15 разных полезных нагрузок:

```
{'type':          714     {'admission':      25     {'AdGroups':      11
{'acceptance':    152     {'id':             18     {'BidModifiers':  10
{'commit_point':  137     {'Keywords':       18     {'Ads':           10
{'Campaigns':      55     {'receipt_id':     11     {'name':           7
{'UpdateResults':  26     {'kind':           11     {'ok':             6
```

`record_review_outcome` — 11 строк из 1 397, то есть **0.8%**. Тулы, у которых `result` строка
(например `send_message`), не задеты: `str('...')` возвращает ту же строку.

## Вывод для развилки

Чинить это двадцатью рендерерами нельзя — их пришлось бы писать под каждый тул. Одна точка:
либо `_extract_tool_result` отдаёт `json.dumps(parsed['result'], ensure_ascii=False)` вместо
`str(...)`, либо фронт учится разбирать repr. Первое дешевле и включает уже готовый
`_renderJsonGrid` сразу всему парку.

Риск правки в первой точке: у неё есть потребители, ожидающие текущую форму (строковые
результаты не меняются, но dict-результаты изменят вид во всех логах и во всех местах, где по
ним грепают). Проверять надо отдельной задачей — здесь только локализация.
