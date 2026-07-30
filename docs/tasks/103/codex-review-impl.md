## Summary

🧨 Ну конечно, самый опасный путь спрятался именно в «нейтрализованных» merge-драйверах. Обычные сценарии покрыты хорошо, но остаются два способа получить ложный `content_merged=True` и потерять worker-only изменения.

## Findings

**blocking: Neutralize the built-in `union` merge driver** — `app/workspace.py:1037-1046`

`merge.default=text` не переопределяет явный атрибут вроде `file merge=union` из `.gitattributes`. Если base изменяет строку, а worker удаляет её, встроенный `union` может чисто оставить версию base; `merge-tree` вернёт дерево base, проверка разрешит переключение, а `reset --hard` уничтожит удаление worker. Для этой проверки `union` должен принудительно конфликтовать либо приводить к fail-closed.

**blocking: Не передавай произвольные config keys через `-c key=value`** — `app/workspace.py:1042-1043`

Имя subsection в Git config легально может содержать `=`. Ключ `merge.keep=ours.driver` превращается в `-c merge.keep=ours.driver=false`, но Git разделяет аргумент по первому `=`, поэтому исходный driver остаётся активным. Ours-подобная команда `driver=true` может оставить blob из base, вернуть успех и снова дать ложный content-noop. Небезопасные ключи нужно отклонять либо передавать через точные `GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n`.

## Verdict

Проверка fail-closed на ошибках, разбор `rev-list`, обработка `merge-tree`, сравнение деревьев и явный `force` выглядят корректно. Но два действующих merge-driver обхода ломают именно гарантию от тихой потери committed content — ремень безопасности хорош, кроме двух мест, где он не пристёгнут. 🙃

VERDICT: NEEDS WORK

## Round (2026-07-30T09:52:11Z)

## Summary

🛡️ Ну вот, guard наконец перестал доверять merge-драйверам на честном слове. Оба прежних блокера закрыты; новых путей к тихой потере committed content в обновлённом diff не найдено.

## Findings

- **FIXED — built-in `union`:** `merge.union.driver=false` теперь передаётся через command-scope environment и превращает опасное чистое разрешение в конфликт. Переключение блокируется до `reset --hard`.

- **FIXED — ключи с `=`:** NUL-разбор сохраняет точное имя, а `GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n` убирают неоднозначность `-c key=value`. Overrides добавляются после унаследованных записей, поэтому исходный driver не выполняется.

- **Новых blocking findings:** нет. Разбор результатов, сравнение деревьев, fail-closed обработка ошибок и явный `force` остаются корректными.

## Verdict

Теперь предохранитель действительно разрывает цепь, а не просто убедительно нарисован на корпусе. 🔒

VERDICT: APPROVED
