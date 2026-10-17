# item-01

Commit under review (in /home/kesha/orchestra, read-only): `2739e0b8de4a329fb4ff8a3cd9137295eef4459d`
Subject / date:
#9: версия в URL статики + правила кеширования
2026-08-03

The diff reviewed is `git -C /home/kesha/orchestra show 2739e0b8de4a329fb4ff8a3cd9137295eef4459d -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Проверил полный diff между указанными коммитами и связанные с ним маршруты, шаблоны и настройки зависимостей. `static_url()` добавляет версию по `mtime_ns`; `VersionedStatic` выставляет `immutable` только для успешных ответов с параметром `v`, а HTML-страницы помечены `no-cache`.

## Findings

### blocking

Нет.

### suggestion

Нет.

### question

Нет.

## Verdict

APPROVED — в проверенном снимке не нашёл проблем, требующих правок. Тесты не запускал.
