# #395 — почему `/api/tm/tasks` зависает: корневая причина найдена

Дата: 25.08.2026. Инцидент воспроизведён вживую на боевом процессе (`MainPID=2136553`)
собственным `task_create` оркестратора, а не по чужому пересказу.

## Что наблюдалось

| Проба | Результат |
|---|--:|
| `GET /api/usage` во время зависания | 200, **0.049 c** |
| `GET /api/tm/tasks?project=…` во время зависания | **000 (timeout 25 c)** |
| `POST` task_create (MCP-тул) | `transport_timeout: ReadTimeout` |
| Задача, созданная этим «упавшим» POST | **#396 существует** |
| `GET /api/tm/tasks` через ~4 минуты | 200, **0.45 c** |

То есть: маршрут TM не «падает», он СЕРИАЛИЗУЕТСЯ за длинной операцией, а POST
доводит работу до конца уже после того, как клиент отвалился по таймауту. Ровно та же
картина, что описал seedon-orchestrator (задача заведена, ответ не получен).

## Стек боевого процесса в момент зависания

`py-spy dump --pid 2136553` (через `ssh kesha@localhost` + `sudo -n`, из-под юнита ptrace
запрещён). Из 20 потоков:

```
Thread …_11:                       Thread …_1 (и ещё 4 таких же):
  replace_current  (app/ia/projections.py:175)     task_list (app/ia/runtime.py:126)
  _refresh_current_projection (app/ia/runtime.py:657)   api_list_tasks (app/tm.py:1741)
  _record_task_head (app/ia/runtime.py:440)             _do (app/routes/tm.py:158)
  _changed (app/ia/runtime.py:98)
  task_create (app/ia/runtime.py:106)
  api_create_task (app/tm.py:1560)
  _do (app/routes/tm.py:129)
```

`task_list` стоит на `with self._lock` (`app/ia/runtime.py:125`). Лок держит поток
`task_create`, находящийся внутри `replace_current`.

## Что делает `replace_current`

`app/ia/projections.py:173-186` — на КАЖДУЮ запись задачи:

```
DELETE FROM current_fts
DELETE FROM current_records
    затем построчный INSERT всех записей + INSERT в FTS
```

Это полная перестройка проекции, а не инкремент. Размер проекции сейчас:

| Величина | Значение |
|---|--:|
| `~/.local/state/orchestra/knowledge-v1/current.db` | **171 745 280 Б (164 МиБ)** |
| строк в `current_records` | **3 252** |
| строк в `current_fts` | 3 252 |
| средний payload на запись | ≈53 КБ |

Полная перезапись 3 252 записей с FTS-индексом под глобальным локом и есть те самые
«>30 секунд», в течение которых любой `task_list` в любом проекте стоит в очереди.

## Что из этого следует для починки

1. Узкое место — не SQLite и не executor, а **полная перестройка проекции на каждую
   мутацию** плюс **один глобальный лок на чтение и запись**. Увеличивать таймауты
   клиента бессмысленно: очередь от этого только удлиняется (проверено 21.08 на
   дашборде, `_API_TIMEOUT_MS` 2→4 c сделал хуже).
2. Инкрементальное обновление проекции (upsert затронутых `record_key` вместо
   `DELETE *`) убирает зависимость времени мутации от размера базы.
3. Чтения (`task_list`, `task_get`) не обязаны стоять за писателем: им достаточно
   снимка проекции.
4. Отдельно и независимо: `task_create` обязан быть идемпотентным по ключу запроса,
   иначе клиент после таймаута не может отличить «не создалось» от «создалось молча» и
   рискует дублем. Именно этот риск заставил seedon-оркестратора не повторять вызов.

## Как воспроизвести

```bash
# в одном шелле
curl -s -m 55 -H "Authorization: Bearer $INTERNAL_TOKEN" \
  "http://127.0.0.1:8888/api/tm/tasks?project=/home/kesha/orchestra" &
# сразу во втором, пока висит
ssh kesha@localhost 'sudo -n py-spy dump --pid $(systemctl show orchestra -p MainPID --value)'
```

## Дополнение Phase 1 (26.08.2026)

Полный разбор второго O(N)-контура (`task-current.db`), всех callers, shadow/debt-инвариантов,
идемпотентности и backup-only baseline вынесен в `research.md`. На фиксированном клоне
175 276 032 Б / 3 258 строк неизменный код дал две серии: при loadavg-1m 4.632–5.210 median
`task_create` 32.661 с / concurrent `task_list` 32.353 с (3/3 выше 30 с), при loadavg-1m
1.129–1.377 — 21.738/21.519 с (0/3 выше 30 с). Значит сам serialized stall подтверждён, а
пересечение клиентского дедлайна зависит от нагрузки. Инструментация: один `current.db` rebuild
13.239–16.098 с и один task-projection rebuild 0.095–0.241 с на create. Сырой вывод:
`benchmark-3d72fe961b42-high-load.raw.jsonl` и `benchmark-3d72fe961b42.raw.jsonl`.

## Current-main recheck (27.08.2026)

`main` уже содержит частичную #405: immutable resource payloads не переписываются, но resource/FTS
verification и все mutable rows по-прежнему обрабатываются синхронно под тем же RLock. На свежем
`Connection.backup`-снимке 887 365 632 Б / 16 730 строк preserved-receipt median составил:
startup 8.616 с, create 9.524 с, concurrent list 9.355 с. При `POSIX_FADV_DONTNEED` только для
клонированного `current.db` и очищенных receipt fields: startup 213.691 с
(`_refresh_current_projection` 205.054 с), create 108.216 с, concurrent list 107.953 с; на 30-й
секунде create ещё шёл, а legacy task row уже существовал. Full `replace_current()` не вызывался.

Production journal независимо дал 179.711 и 299.018 с до readiness, затем 22.425 с на следующем
старте. Значит #405 снял обычный полный rewrite, но не устранил O(N) cold-cache stall, reader
serialization и outcome-unknown contract. Артефакты и границы вывода — `research.md` §2a.
