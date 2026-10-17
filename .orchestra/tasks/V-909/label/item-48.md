# item-48

Commit under review (in /home/kesha/orchestra, read-only): `0059e6757edf3badf7267c23def512d03a4aef06`
Subject / date:
V-621: разбить общий каталог проектов на файлы по scope
2026-10-13

The diff reviewed is `git -C /home/kesha/orchestra show 0059e6757edf3badf7267c23def512d03a4aef06 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Проверил diff между указанными коммитами. Нашёл блокирующую ошибку в конфигурации каталога.

## Findings

### blocking

`.orchestra/projects.yaml:5` добавляет `/home/kesha/orchestra` в `include_scopes`, хотя это и есть корень Orchestra, а значит `own_catalog_path()` для этого scope указывает на тот же `.orchestra/projects.yaml`. `catalog()` сначала загружает записи из домашнего файла, затем повторно читает его через `include_scopes` и передаёт дубли в `_aggregate()`. Повторяющиеся теги вызывают `CatalogError`; вызовы слитого каталога ломаются. Удалите этот self-include или предусмотрите отдельный файл для scope Orchestra.

## Verdict

NEEDS WORK — self-include приводит к ошибке при сборке каталога.
