😏 Гонку почти поймали, но таймаут умудрился от неё отстать.

## Summary

Направление верное: указанные функции существуют, ownership-check расположен в правильной точке перед `_convert_notification()`, а Codex-only scope сохраняет Claude/Grok без изменений. Однако протокол drain недостаточно определён: после completion future он может зависнуть навсегда.

## Findings

- **blocking:** Ограничьте `_drain_compact_lifecycle()` общим дедлайном compaction. Сейчас 120-секундный timeout охватывает только ожидание `_compact_future` в [backend_codex.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/backend_codex.py:403), тогда как план запускает drain уже после его разрешения в [plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/plan.md:53). Если `turn/completed` потерян или конкретная версия app-server его не выдаёт, `compact_context()` навсегда удержит session lifecycle lock. План должен требовать единый deadline для completion и drain, плюс тест отсутствующего terminal event.

- **suggestion:** Зафиксируйте happens-before: временная очередь должна подключаться до отправки `thread/compact/start`, а не после RPC-ответа. Иначе мгновенный `turn/started` попадёт в обычную очередь ещё до включения маршрутизации, сохранив исходную гонку. Это стоит явно прописать рядом с [описанием temporary queue](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/plan.md:51) и проверить тестом.

- **suggestion:** Разделите mutation verification для двух защитных слоёв. При исправном drain отключение ownership-helper не должно ломать интегрированный сценарий: compact lifecycle уже потреблён до запуска listener. Поэтому утверждение в [T1](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/plan.md:107) может относиться только к listener-only тесту, а интегрированный тест из [T2](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/plan.md:119) должен отдельно падать при отключении routing/drain. Иначе одна защита маскирует мутацию другой.

## Verdict

**Request changes.** После добавления bounded drain и точного порядка подключения очереди план будет готов к реализации. Тесты не запускались: реализации ещё нет, review был ограничен указанными файлами.

Пока это как закрыть дверь от сквозняка, забыв проверить, что ключ не остался снаружи.

## Round (2026-07-28T10:43:07Z)

😏 На этот раз таймаут действительно дождался всей компании.

## Re-review status

- **FIXED** — один абсолютный deadline охватывает RPC, completion и terminal drain; добавлен missing-terminal test с проверкой detach.
- **FIXED** — временная очередь подключается до `thread/compact/start`; предусмотрен synchronous-start test.
- **FIXED** — mutation verification разделена между listener ownership и routing/drain, поэтому слои больше не маскируют друг друга.

## New findings

Нет.

## Verdict

**APPROVED.** Тесты не запускались по указанию. Все три дыры закрыты — редкий случай, когда очередь действительно знает, где её место.
