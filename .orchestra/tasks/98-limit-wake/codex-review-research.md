## Summary

Ну да, `false` в одном поле уже почти официальный SLA провайдера. 🙃

Исследование убедительно разделяет факты и эксперимент:

- реальный инцидент — три monthly-stop и ни одного timed-кандидата;
- mixed-cohort дефект воспроизведён только синтетически и не объявлен причиной инцидента;
- удалять Anthropic-exclusion и будить по 5h reset небезопасно;
- пустой POST действительно визуально не подтверждается: фронтенд заменяет payload эквивалентным состоянием.

Но рекомендация Option B пока не следует из доказательств. Она опирается на непроверенный clear-сигнал, недостающую повторную monthly-проверку перед каждой отправкой и несуществующую в рассмотренном коде polling-механику.

## Findings

### blocking — Сначала сравните watcher с безопасным recheck-on-click

[research.md:317](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:317)

Данные доказывают необходимость свежей проверки и явной обратной связи, но не необходимость фонового watcher’а. Более простой контракт для одного оператора: пока monthly закрыт — явный no-op; после повышения лимита повторный клик делает fresh-read, сразу будит при двух открытых gates либо создаёт существующий one-shot timer для оставшегося timed reset. Это устраняет polling, expiry и restart-state. Чтобы Option B стала обоснованной рекомендацией, нужен явный продуктовый аргумент, почему второй клик неприемлем.

### blocking — Не используйте `spend_limit_reached == false` как доказанный clear-сигнал

[research.md:319](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:319)

Исследование наблюдало только `true` и само признаёт, что переход в `false` не измерен ([research.md:90](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:90)). При этом рекомендация уже фиксирует `== false` как достаточное условие готовности, хотя payload содержит и связанные `is_enabled`/`disabled_reason`. До наблюдения clear-state это лишь гипотеза; безопасный контракт должен считать семантику неподтверждённой или требовать проверенного набора полей.

### blocking — Monthly gate нужно перепроверять перед каждой отправкой

[research.md:334](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:334)

Фраза о повторном использовании существующей per-agent quota check не обеспечивает заявленное «никогда не отправлять при закрытом monthly». `run_wake_job()` перед каждым агентом вызывает fresh-read, но затем проверяет только нормализованные timed windows ([limit_wake.py:353](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:353)); `_provider_usage_snapshot()` полностью отбрасывает `extra_usage` ([system.py:576](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/routes/system.py:576)). Monthly может снова закрыться между начальным срабатыванием watcher’а и следующей staggered-отправкой. Оба gates должны проверяться одним fresh readiness helper непосредственно перед каждым `session.send()`.

### blocking — Timed readiness тоже должна fail closed на неполном snapshot

[research.md:282](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:282)

Fail-closed явно сформулирован только для monthly-поля. Текущая нормализация пропускает отсутствующее или некорректное окно ([system.py:583](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/routes/system.py:583)), а `provider_is_available()` считает провайдера доступным, если хотя бы одно оставшееся окно ниже 100% ([limit_wake.py:297](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:297)). Поэтому fresh payload только с открытым 5h и отсутствующим 7d может дать ложный clear. Контракт должен перечислить обязательные Anthropic windows и требовать их присутствия в том же свежем ответе.

### blocking — «Существующая cadence» не является механизмом polling

[research.md:334](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:334)

В рассмотренных функциях есть cache TTL, но нет активного пятиминутного poller’а: `_get_usage_data()` обновляется только при вызове ([system.py:754](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/routes/system.py:754)). Текущий wake-job при закрытом provider завершает trigger вместо повторного планирования ([limit_wake.py:355](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:355)). Следовательно, recurring checks, backoff, persisted `next_check_at` и восстановление после рестарта остаются нерешёнными; expiry — далеко не единственный открытый параметр.

### blocking — Фиксированные 24 часа могут истечь раньше timed reset

[research.md:372](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:372)

Anthropic-модель содержит 7d window ([system.py:584](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/routes/system.py:584)), а существующий planner выбирает самый поздний reset исчерпанных окон ([limit_wake.py:146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:146)). Если 7d reset дальше чем через сутки, watcher гарантированно истечёт до выполнения своего двух-gate контракта. Expiry должен учитывать последний relevant reset плюс запас либо UI должен честно говорить, что one-click completion не гарантируется.

### suggestion — Исправьте утверждение о неперсистентных именах

[research.md:263](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:263)

В persisted job config уже передаётся полный список `agents` с именами ([limit_wake.py:264](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:264)). Только `wake_status()` проецирует его в `agent_count` ([limit_wake.py:239](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:239)). Это frontend/status-contract gap, а не storage gap; неверная формулировка может привести к лишнему изменению схемы.

## Verdict

Реальные выводы об инциденте, latent mixed-дефекте и невидимом no-op подтверждены в доступном scope. Product recommendation **Option B пока не готова к планированию**: сначала нужно либо выбрать простой fresh recheck-on-click, либо доказать clear-предикат и спроектировать fail-closed recurring job с per-send проверкой и expiry, учитывающим timed reset.

Иначе watcher получится как будильник с батарейкой на сутки перед событием через неделю — формально заведён, практически декоративен.

## Round (2026-07-28T12:30:31Z)

## Re-review status — Round 2

Ну вот, одна дополнительная кнопка всё-таки победила маленькую диспетчерскую службу. 🙃 `git diff` пуст, поскольку `research.md` остаётся untracked; проверен весь текущий файл.

| Prior finding | Status | Result |
|---|---|---|
| Watcher не обоснован, проще fresh recheck | **FIXED** | Option A теперь рекомендует явный no-op и один повторный aggregate-click. |
| `spend_limit_reached == false` не доказан | **FIXED** | Clear-предикат прямо объявлен неизмеренным; реализация отправки заблокирована до измерения комбинации полей. |
| Monthly не проверялся перед каждой отправкой | **FIXED** | Требуется единый complete readiness check непосредственно перед каждым `session.send()`. |
| Partial timed snapshot мог fail open | **FIXED** | Оба окна, `five_hour` и `seven_day`, обязательны и должны иметь числовую utilization. |
| Cadence ошибочно считалась watcher-механизмом | **FIXED** | Активный пятиминутный loop подтверждён, но документ верно отделяет cadence от wake evaluation и recurring state. |
| 24h expiry мог предшествовать 7d reset | **FIXED** | Рекомендация удалена; для будущего watcher указан latest reset плюс grace. |
| Имена якобы не сохранялись | **FIXED** | Теперь правильно сказано: имена есть в job config, теряются только при проекции `wake_status()`. |

## New findings

### suggestion — Уточнить, что monthly теряется именно из history snapshot

[research.md:355](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:355)

Фраза «loop persists only normalized timed windows» слишком широкая: `_collect_usage_snapshot()` также кладёт полный raw Anthropic payload в `_usage_cache` и вызывает `_save_usage_cache()` ([system.py:903](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/routes/system.py:903)). Нормализацию применяет именно persisted history contract через `usage_save_snapshot`. Это не влияет на Option A, но формулировку стоит сузить, чтобы будущий план watcher’а не предположил отсутствующую raw-персистентность без проверки.

## Verdict

**APPROVED.** Все load-bearing выводы поддержаны измерениями и кодом; clear-предикат честно оставлен обязательным исследованием до реализации. Новый комментарий неблокирующий и не меняет продуктовую рекомендацию.

Теперь recovery-кнопка требует второго клика, а не собственного ночного сторожа с журналом обходов — для MVP редкий приступ здравого смысла.

## Round (2026-07-28T12:39:13Z)

## Re-review status — Round 3

Ну да, «strict combination is treated as confirmed» — почти то же самое, что реально её подтвердить. 🙃 `git diff` показывает изменения только в `research.md`; проверен весь текущий файл.

| Prior finding | Status | Result |
|---|---|---|
| Watcher был необоснован | **FIXED** | Рекомендован один provider-capacity one-shot, recurring watcher отвергнут. |
| Extra clear-state не измерен | **STILL BROKEN** | Неопределённый strict combination всё ещё может разрешить extra-ветку. |
| Проверка перед каждым send | **FIXED** | Один fresh readiness helper требуется перед каждым `session.send()`. |
| Partial base snapshot fail-open | **FIXED** | Обязательны numeric `five_hour` и `seven_day`, оба ниже 100%. |
| Cadence ошибочно считалась watcher’ом | **FIXED** | Raw cache, SQLite history и wake evaluation теперь разделены корректно. |
| Некорректный 24h expiry | **FIXED** | Watcher и expiry исключены из текущего решения. |
| Имена якобы не сохранялись | **FIXED** | Верно указано, что их теряет только status/UI projection. |
| Raw monthly якобы нигде не сохранялся | **FIXED** | Документ различает полный raw cache и нормализованную SQLite history. |

## New findings

### blocking — Полностью отключите extra-ветку до измерения clear-state

[research.md:341](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/98-limit-wake/research.md:341)

Новые данные доказывают, что открытые base windows достаточны независимо от заблокированного extra usage. Но они ничего не доказывают о состоянии, в котором extra usage самостоятельно разрешает отправку при исчерпанной base capacity. Формулировка «strict response combination is treated as confirmed» позволяет реализации угадать комбинацию полей. Для Phase 1 контракт должен явно задавать `extra_available = false`; эту OR-ветку можно включить только после измеренного clear-state. Планирование monthly-когорты на будущий base reset безопасно, потому что timer всё равно выполняет fresh pre-send check.

## Verdict

**NOT APPROVED.** Base-capacity one-shot, обязательные два окна и scheduling monthly-кандидатов по известному reset подтверждены измерениями. Единственный blocker — недоказанная extra-ветка; после её явного отключения Phase 1 будет поддержан фактами.

Иначе получится fail-closed система с маленькой дверцей «ну это выглядит достаточно strict» — лимиты такие двери обожают.

## Author resolution after Round 3

The remaining blocker was accepted. `research.md` now fixes
`extra_available = false` for this task: no combination of unmeasured
extra-usage fields can authorize a wake. The only enabled path is complete,
fresh base-window availability; exhausted base capacity with a future reset may
still create a one-shot whose pre-send check fails closed.

No Round 4 was requested because the debate skill caps one topic at three
rounds. The Phase-2 plan review must explicitly verify that implementation does
not infer an extra clear-state.
