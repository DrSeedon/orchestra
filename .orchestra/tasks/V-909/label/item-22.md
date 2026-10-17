# item-22

Commit under review (in /home/kesha/orchestra, read-only): `180f78bd491e2f7bb605ca9df6778ee84182f1e8`
Subject / date:
#54: #54: sessions.id не может быть пустым — схема, триггер, гард в коде, громкий ноль строк, 400 в bg_create
2026-08-04

The diff reviewed is `git -C /home/kesha/orchestra show 180f78bd491e2f7bb605ca9df6778ee84182f1e8 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Проверил полный diff между указанными коммитами и вызывающий код. Гард в `save_session`, триггеры для существующих БД и ответ 400 в `bg_create` соответствуют заявленным сценариям. Блокирующих проблем не нашёл.

## Findings

### suggestion

Триггер считает пустыми только `NULL`, пустую строку и строки из обычных пробелов: SQLite `TRIM()` без второго аргумента не удаляет табуляции и переводы строк. Поэтому прямой `INSERT` с `id='\t'` пройдёт триггер, хотя гард в `save_session` такой ID отвергнет через Python `.strip()`. Если база должна гарантировать тот же инвариант для прямых записей, стоит явно проверять нужные пробельные символы.

## Verdict

APPROVED — замечание не блокирует заявленный сценарий с `NULL` и пустой строкой.
