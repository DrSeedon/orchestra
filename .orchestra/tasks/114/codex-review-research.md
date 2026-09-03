## Summary

Ну да, `absolute` внезапно не означает `вне Git` 🙃

Идея вынести inbox из worktree правильная, и clean-target guard менять действительно не нужно. Но рекомендуемый XDG boundary пока не гарантирует изоляцию от Git, работоспособность systemd-развёртывания и crash durability. При заявленном single-process uvicorn конкурентные HTTP-вызовы не создают отдельной проблемы: синхронный append не отдаёт управление event loop.

## Findings

### blocking: Сделать путь доказуемо внешним относительно Git

[research.md:82](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:82) бездоказательно утверждает, что `$XDG_STATE_HOME/orchestra/BUGS.md` находится вне каждого worktree. XDG требует лишь абсолютный путь: переменная может указывать внутрь репозитория, а любой компонент fallback-пути может быть symlink туда. Тогда append создаст tracked/untracked изменение и снова заблокирует `_clean_worktree_error()`. Нужен выделенный provisioned state directory и проверка разрешённого пути через `resolve()` с отказом, если ближайший существующий ancestor принадлежит Git worktree; соответствующие XDG-in-repo и symlink-сценарии должны войти в тесты.

### blocking: Не считать named service user гарантией writable state

[research.md:73](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:73) выводит переносимость из наличия `User=orchestra`, но [service template:7](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/deploy/orchestra.service.template:7) не создаёт writable home/state directory и не задаёт `XDG_STATE_HOME`. У system account home может быть `/nonexistent`, root-owned каталог или даже `/opt/orchestra`; первые варианты теряют каждый report через HTTP 500, последний возвращает merge blockage. Деплой должен явно provision-ить каталог, например через systemd `StateDirectory=orchestra`, и приложение должно использовать предоставленный им путь.

### blocking: Добавить безопасную последовательность миграции pointer-файла

[research.md:147](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:147) признаёт, что старый процесс продолжит писать tracked `BUGS.md`, однако [recommended design:159](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:159) одновременно включает изменение этого файла в тот же merge. Report между очисткой target и merge снова сделает target dirty, а изменение pointer в worker branch добавляет конфликт по тому же файлу. Нужна явная rollout-последовательность: остановить приём reports, вручную сохранить текущий archive, merge code и pointer без auto-commit, затем запустить новую версию — либо вынести pointer во вторую фазу после активации нового endpoint.

### blocking: Синхронизировать directory entry для первой записи

[research.md:141](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:141) считает `flush` плюс `fsync(file)` достаточной гарантией durability. Для впервые созданных каталога и файла это не гарантирует сохранение directory entries после power loss: endpoint может вернуть успех, а `BUGS.md` исчезнет после перезагрузки. Нужно либо provision-ить файл до приёма запросов, либо после его создания синхронизировать родительский каталог; это отдельно от host backup policy.

### suggestion: Не использовать текущий dashboard как доказательство полной видимости

[research.md:86](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:86) утверждает, что dashboard показывает полный title и expandable description. Однако [app.js:4054](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/static/js/app.js:4054) после успеха заменяет title на generic `✅ Bug reported` и не отображает возвращённый canonical path, а [app.js:3439](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/static/js/app.js:3439) добавляет expand только при более чем пяти строках, хотя длинные 1–5 строк также обрезаются `max-height:90px`. Либо frontend нужно включить в affected files и тестировать длинный однострочный report, либо исследование должно честно считать tracked pointer единственным механизмом aggregate discoverability.

### suggestion: Зафиксировать приватные права inbox

[recommended design:155](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:155) не определяет permissions. При обычном `umask 022` каталог и Markdown-файл будут доступны другим пользователям хоста, хотя reports содержат verbatim errors, environment и traces. Создавайте каталог с `0700`, файл с `0600` либо задайте соответствующий `UMask` в service template.

## Verdict

Рекомендация пока не готова к реализации: сам принцип «runtime inbox вне Git» верный, но произвольный XDG path ещё не является storage boundary. Clean-target guard и отказ от auto-commit обоснованы; перед implementation нужны исправления четырёх blocking-пунктов выше.

Пока это почтовый ящик «вне Git», адрес которого всё ещё может оказаться внутри Git.

## Round (2026-08-01T10:43:02Z)

## Re-review status — Round 2

Ну да, Git честно ответил `false` — просто не на тот вопрос 🙃 `git diff` пуст, поскольку [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:1) остаётся untracked; проверен его текущий полный текст.

- **STILL BROKEN — Git/XDG isolation.** Обычные worktree, missing descendants и symlink cases закрыты, но probe имеет false accepts — см. new finding.
- **FIXED — writable system-service state.** `StateDirectory=orchestra`, `0700` и fail-loud fallback закрывают проблему.
- **STILL BROKEN — rollout.** Pointer conflict устранён, но [строки 189–193](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:189) всё ещё оставляют старый POST активным между merge и restart. Report в этом окне снова загрязнит target и может заблокировать следующий merge. Нужен явный maintenance rollout: quiesce/stop старый endpoint → clean check/merge → start новой версии.
- **FIXED — first-create durability.** File и directory-entry fsync теперь входят в контракт.
- **STILL BROKEN — human discoverability.** GET делает aggregate технически доступным, но dashboard не показывает возвращённый route/path, tracked pointer удалён, frontend change исключён. Нужна хотя бы постоянная ссылка на authenticated GET в dashboard; иначе endpoint известен агенту и автору research, но не обязательно человеку.
- **FIXED — permissions.** `0700`/`0600` зафиксированы.

## New findings

### blocking (NEW BUG): Git probe принимает некоторые Git-пути

[Строки 92–94](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:92) проверяют только `--is-inside-work-tree`. Экспериментально команда из `<repo>/.git` вернула `false`, а с унаследованным `GIT_DIR=<other-repo>` она вернула `false` даже из настоящего worktree. Следовательно, Git metadata/bare repositories и обычные worktree при влияющем `GIT_*` environment могут пройти проверку. Probe должен очищать repository-selection variables, проверять также git-dir/bare state и fail closed при неожиданных ошибках.

## Verdict

**NOT APPROVED FOR PLAN.** Остались два blocking gap: false-accept в path probe и незакрытое rollout-окно старого writer. GET также требует минимального постоянного human-facing entry point.

Пока новый почтовый ящик уже вынесли из комнаты, но ключ и адрес оставили только курьеру.

## Round (2026-08-01T10:48:23Z)

## Re-review status

Ну наконец-то Git-проверка перестала верить загрязнённому окружению на слово 🙃 Обычный `git diff` пуст, потому что файл untracked; проверен через `git diff --no-index`.

- **FIXED — Git/XDG isolation.** Sanitized environment, `--absolute-git-dir`, exact non-repository outcome и fail-closed semantics закрывают worktree, metadata, bare-repo и contaminated-env cases ([research.md:105](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:105)).
- **FIXED — writable system state.** `StateDirectory`, ownership и `0700` определены.
- **FIXED — rollout.** Явная stop/quiesce → manual merge → start/smoke последовательность закрывает old-writer race ([research.md:230](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/research.md:230)).
- **FIXED — first-create durability.** File и directory-entry `fsync` включены.
- **FIXED — human visibility.** Authenticated GET/OpenAPI плюс route/path в tool response удовлетворяют заданной backend-границе. Dashboard link остаётся необязательным улучшением.
- **FIXED — permissions.** `0700` directory и `0600` inbox зафиксированы.
- **FIXED — Round 2 probe false accepts.** Проверка больше не принимает `.git`, bare repo или подменённый `GIT_DIR`.

## New findings

Новых blocking или suggestion-level проблем нет.

## Verdict

**APPROVED FOR PLAN.** Оба оставшихся blocking gap закрыты; clean-target guard, отсутствие auto-commit и заданные границы задачи сохранены.

На третьем круге ящик наконец вынесли из Git, а не просто переклеили на нём адрес.
