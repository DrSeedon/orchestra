## Summary

Ну да, два успешных resume уже почти заменяют проверку всего process tree 😏

Узкий вывод подтверждён: `reconnect=False` относится к heartbeat-recovery, `resume_across_models=False` — к смене модели; обычный same-model wake создаёт новый backend с сохранённым `session_id`. Но общий вывод о безопасном включении hibernation пока преждевременен: есть три блокирующих пробела — MCP-потомки, конкурентная cold-load операция и отсутствие fail-closed проверки thread id.

## Findings

1. **blocking:** GO-критерий не доказывает завершение MCP-потомков — [research.md:48–61](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:48), [research.md:207–211](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:207)

   Эксперимент проверяет только исходный app-server PID, а исследование само признаёт, что реальный MCP child не попал в controlled teardown. Текущий `disconnect()` завершает только непосредственно запущенный процесс, без process-group ownership или обхода потомков ([backend_codex.py:238](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/backend_codex.py:238), [backend_codex.py:454](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/backend_codex.py:454)). Если MCP-потомок переживает закрытие stdio, каждый wake создаст ещё один, и утечка останется или усилится. Проверка полного дерева реального worker с запущенным MCP должна быть условием GO до включения capability, а не post-implementation smoke.

2. **blocking:** `ensure_loaded()` не обеспечивает идемпотентность manual hibernate — [research.md:179–183](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:179)

   Предложенный маршрут может одновременно с `send` загрузить DB-only worker дважды: `ensure_loaded()` не сериализован, `_load_from_db()` делает `await` до регистрации объекта, а каждый экземпляр получает собственный `_lifecycle_lock` ([manager.py:931](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/manager.py:931), [manager.py:981](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/manager.py:981), [manager.py:1061](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/manager.py:1061)). В результате manual request может вернуть success на одном объекте, пока другой создаёт backend и затем вытесняется из registry, оставляя неуправляемый процесс. Для detached-сессии маршрут должен сразу отвечать “already process-free”, не вызывая `ensure_loaded()`; иначе cold-load нужно закрывать общим manager-level lock во всех entry points.

3. **blocking:** wake не проверяет, что `thread/resume` вернул запрошенный id — [research.md:13–15](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:13), [research.md:202–205](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:202)

   `CodexBackend.connect()` отвергает пустой id, но любой другой непустой id принимает и записывает в `_thread_id` ([backend_codex.py:266](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/backend_codex.py:266)). При повреждённом rollout, изменении поведения CLI или серверном fallback это может незаметно запустить новый thread, хотя исследование считает смену id фальсификатором и требует fail-loud. План должен явно требовать сравнения ответа с requested id и отказа до отправки сообщения; два успешных trial покрыли только нормальный ответ протокола.

4. **suggestion:** pending-message predicate имеет окно после dequeue — [research.md:179–183](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:179), [research.md:241–246](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:241)

   `_flush_pending()` очищает `_pending_messages` до захвата `_lifecycle_lock` ([session.py:1002](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/session.py:1002)). В этом окне manual hibernate увидит пустую очередь, отключит backend и вернёт success; затем flush возьмёт lock и немедленно разбудит session. Более того, flush не сбрасывает `_hibernated`, поэтому возможен `RUNNING` с признаком hibernation. Нужен явный flush-in-progress guard либо dequeue под lock и отдельный deterministic race test.

5. **suggestion:** automatic predicate пока не исключает compact — [research.md:159–170](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:159)

   F5 утверждает, что существующий lifecycle уже содержит нужные проверки, но timer не проверяет `_compacting` ([session_hibernate.py:59](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/session_hibernate.py:59)), тогда как Codex compact выставляет флаг до захвата того же lock ([session.py:1095](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/session.py:1095)). Timer может первым отключить backend, после чего compact тут же создаст его заново. Активный compact lock защищает, поэтому это не блокер, но общий manual/automatic helper должен проверять `_compacting`.

6. **question:** должна ли эмпирическая часть покрывать существующий длинный или compacted thread? — [research.md:117–140](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:117)

   Оба trial — новые одноходовые thread, возобновлённые сразу, с теми же cwd/model и без работающего MCP. Они подтверждают базовый контракт, но не весь production population, для которого предлагается capability flip. Либо формулировку “exact transition” следует сузить, либо добавить один controlled resume длинного/compacted thread и явно отделить доказанное экспериментом от доверия протоколу.

## Verdict

**NO-GO в текущем виде. Confidence: 0.94.**

Same-model cold resume действительно работает, а флаги `reconnect` и `resume_across_models` скрытого запрета не несут. Но до включения автоматической hibernation нужны доказательство полного teardown дерева, безопасный путь для DB-only session и fail-closed проверка thread id. Иначе это как проверить эвакуацию по двум людям, пока остальные сидят в MCP-подвале.

## Round (2026-08-01T07:32:16Z)

## Summary

Serena официально переживает выключение хозяина — почти отдельный runtime 🪳

Все шесть замечаний первого раунда учтены. Исследование теперь подтверждает только узкий resume-примитив, правильно блокирует capability flip до исправления process-tree cleanup и задаёт нужные pending/compact/thread-id guards. Для планирования материала достаточно, но в teardown-контракте остался один блокирующий failure path.

## Findings

- **blocking:** сохранить владельца backend при ошибке teardown — [research.md:225–234](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:225), [research.md:281–283](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:281)

  Текущий `_disconnect_backend()` обнуляет `session._backend` до `await backend.disconnect()`. Если новый descendant cleanup упадёт на enumeration, signal или timeout, hibernation не поставит `_hibernated`, но ссылка на ещё живой process tree уже потеряна. Следующая manual operation увидит `_backend=None` и может вернуть idempotent success, а следующий send создаст второй backend. План должен требовать атомарный контракт: `disconnect()` либо подтверждает отсутствие root и descendants, либо оставляет retryable owner и сообщает ошибку. Нужны failure-injection тесты, не только successful signalling.

- **suggestion:** проверять process identity и итоговое дерево, а не только исходные PID — [research.md:63–71](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:63), [research.md:225–228](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:225)

  Candidate сначала убивает descendants, затем root и проверяет только захваченные PID. Между этими действиями живой app-server может породить replacement с новым PID, а завершившийся PID теоретически может быть переиспользован чужим процессом. Для простой Linux-реализации достаточно фиксировать PID вместе с `/proc/<pid>/stat` starttime, сначала прекратить возможность root создавать детей, затем завершить подтверждённых survivors и проверить конечный postcondition. Тест должен включать child respawn или хотя бы нового потомка после первоначального snapshot.

- **suggestion:** сделать capability flip последним из всех prerequisites — [research.md:278–288](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:278)

  Сейчас bullet для registry упоминает только teardown и resume guards, хотя pending dequeue, `_hibernated` reset и `_compacting` predicate также обязательны до включения автоматического timer path. Стоит перечислить их явно, чтобы частичная реализация не активировала hibernation раньше lifecycle-фиксов.

## Verdict

**GO для implementation planning; NO-GO для capability flip до выполнения prerequisites. Confidence: 0.94.**

Предыдущие замечания закрыты корректно, а новые evidence действительно поддерживают план. Осталось сделать teardown fail-closed не только при успехе, но и при ошибке — иначе Serena снова окажется бессмертной по ошибке обработки ошибки.

## Round (2026-08-01T07:36:04Z)

## Summary

Теперь teardown-контракт знает о PID reuse больше, чем некоторые process managers 😏

Предыдущий ownership-блокер закрыт: backend остаётся владельцем root/descendants до подтверждённого teardown, частичная ошибка запрещает новый spawn, а `AgentSession` больше не теряет retryable owner. PID identity, late-child, failure-injection и порядок capability flip также сформулированы достаточно точно.

## Findings

- **suggestion:** сохранить graceful interrupt до заморозки root — [research.md:232–239](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:232), [research.md:311–314](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/research.md:311)

  `CodexBackend.disconnect()` используется не только idle hibernation: при активном turn он сначала отправляет `turn/interrupt`. Если implementation заморозит root до этого handshake, interrupt гарантированно уйдёт в timeout и каждый active disconnect станет принудительным. В плане достаточно зафиксировать порядок: при активном turn сначала bounded interrupt, затем freeze-to-fixed-point, teardown и identity verification. Это не блокирует планирование.

Новых blocking findings нет.

## Verdict

**GO для плана. Confidence: 0.97.**

Research теперь задаёт fail-closed контракт, который закрывает session duplication, PID reuse и потерю ownership. Capability flip правильно остаётся NO-GO до реализации, failure-injection тестов и real-worker smoke. Serena больше не бессмертна — просто требует нотариально заверенный teardown.
