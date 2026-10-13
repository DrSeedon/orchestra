# V-836 — Scion (Anthropic): что это на самом деле и что из этого брать в Orchestra

Исследование, ничего не менялось и не удалялось (временные клоны в /tmp созданы и убраны через trash). Первоисточник: https://www.anthropic.com/engineering/redesigning-source-control , Anthropic Engineering, опубликован 13.10.2026 (скачан целиком, текст в `evidence/article.txt`; цитаты ниже дословные). Замеры у нас: `evidence/measure.out`, `evidence/sparse_merge_test.out`, `evidence/worktree-status.txt`; БД `merge_operations` (read-only); отчёт V-825; запись V-821 (task_get).

## 1. Что Scion делает и почему

**Проблема по статье.** «In May 2026, Anthropic averaged around 2,500 code changes merged per day; as of September, we merged over 30,000 per day.» История main — «almost 100 GB», сжатая рабочая копия «over 25 GB», «on the order of 25 million code checkouts per day for CI», что при наивной выдаче давало бы «over 600 PB of git traffic per day». Обходы (shallow, sparse, promisor, внутренние зеркала, seeds) исчерпались: «at our peak, we operated several hundred internal git mirrors». Вывод авторов: «we were using git as a centralized system with one authoritative copy, but nearly all of our clients were agents and jobs that are online by definition».

**Решения (по статье):**
- Данные: единица — changeset в write-ahead log; хранит «a list of the files that changed relative to its first parent» и content-addressed указатели на блобы; создаётся на сервере. Refs — «a compare-and-swap on a single Spanner row», отдельно от создания changeset; «The development lifecycle in Scion discourages refs … except for the main ref or release branches». Блейм, история путей, skip lists — «derived data», считается одним обобщённым механизмом рекурсивно от родителей, eager или лениво.
- Хранение: «there is no fully materialized copy of the repo anywhere, even on the server. There is no equivalent of packfiles … so no repository maintenance is needed.» Storage — Spanner/облачное хранилище.
- Checkout: клиент `scn` не сообщает серверу, что у него есть; «operates exclusively on trees and blobs the client wants», рекурсивно запрашивает недостающие деревья, затем блобы; «no single multi-gigabyte packfile response». Sparse и virtualized (файл материализуется при чтении) checkouts — штатный режим. Три яруса одинаковых RPC: `scion-daemon` на узле (снимок), `scion-cache` в регионе (отдаёт из памяти), `scion-server` (авторитетный). «Each tier … cache hit rate of over 99%».
- Коммиты/слияния/rebase выполняются на сервере: «there's nothing to push».
- Запросы как API: diff, merge base, blame доступны по RPC, «in many cases jobs don't need a local repository at all».
- Очередь слияния: «A proper merge queue … doesn't make much sense at agent scale… We haven't been able to effectively replicate the industry standard of a global repository lock on the merge queue, so instead, we've invested in post-merge and pre-deploy automated testing. This does mean that concurrent changes can conflict, but Claude can typically fix these conflicts faster than humans can even identify them.»
- Ревью (Antique): код ревью «can express complex semantic constraints on approvals» (напр. «comment-only changes» против «sensitive logical changes»); люди «now examine the intent of the change as opposed to reading every line of code».
- Эксплуатация: «superfan»-агенты на каждый компонент (scion-daemon, scion-cache, merge queue) плюс обычные алерты.
- Команда и срок: «A team of seven people built both Scion and Antique … and fully migrated to them in five months».

**Заявленные результаты:** инфраструктура «200x smaller» по CPU/памяти, чем прежние git-зеркала; checkout CI/research «two orders of magnitude faster (in seconds rather than minutes)»; у CI «25% CPU capacity win»; переписанный Claude Mythos Preview ингест — «20x less memory and was 4x faster».

**Непроверяемое или без данных (так и помечаю):**
- Все числа — собственные заявления Anthropic; нет методики, распределений, повторов, внешней проверки. Графики статьи («Observed performance improvements on native Scion repos») в текстовой выгрузке недоступны.
- «600 PB/день» — расчётная оценка при «fetched naively», не измеренный трафик.
- «200x» и «two orders of magnitude» сравнивают с их же собственными зеркалами; база сравнения (какая версия, какая нагрузка) не описана. «минуты → секунды» в пересказе владельца соответствует тексту, но без цифр.
- «25%» — выигрыш по CPU-ёмкости CI «alone», не общая экономия.
- Зависимость от Spanner, внутренних Mythos Preview и Claude Tag — воспроизвести снаружи нельзя; сами авторы: «Scion is by no means a suitable replacement for git for general use… only make sense for truly enormous monorepos». «Fully migrated» и «seven people» проверить нечем.
- Пересказ владельца «Git заменён» — верно только для их монорепозитория; для остального они прямо предлагают забирать идеи в git-серверы («share our thinking, so that other developers can apply some of the most successful parts of Scion to git without departing from the overall model»).

Масштаб несравним: 30 000 слияний/день у них против **29.9 успешных слияний/день у нас** (987 за 33 дня с 10.09, пик 79/день 07.10; БД `merge_operations`).

## 2. Как это устроено у нас (код и факты)

**Worktree на воркера.** `app/workspace.py::create_worktree` (стр. ~620): `git worktree add` на ветку `task-<id>/<name>` под `repo_mutation_lock`; объекты общие (`.git` один), копируется только рабочее дерево. Исключения — `_WORKTREE_EXCLUDES` (`.claude/`, `.codex/`, …), sparse не используется (`rg sparse app` пусто). Сейчас 49 каталогов worktree (V-825): 75.3 ГБ, из них katya-work 58.8 ГБ (13 копий по 3.0–10.3 ГБ), seedon 11.0, orchestra 4.0.

**Из чего состоит копия (замер на отслеживаемом `HEAD`, `evidence/measure.out`):**
| Репо | отслеживаемое | из них `.orchestra/tasks` | `artifacts`/`resources` |
|---|---:|---:|---:|
| orchestra | 0.34 ГБ (4785 файлов) | 0.305 ГБ (90%) | — |
| seedon | 1.37 ГБ (5891 файлов) | 0.753 ГБ | 0.238 + 0.273 ГБ |
| katya-work | ≈3.0 ГБ на копию (V-821, замер 12.10; сам не мерил — зона не моя) | — | `artifacts/` + задачи, 3160 медиафайлов |
Прочий вес копии — неотслеживаемые результаты задачи (google-slaydy 10.3 ГБ при базе ≈3 ГБ) и `.venv`: в orchestra-копиях `.venv` 0.52 ГБ по `du`, но **эксклюзивно лишь 0.019 ГБ** — файлы жёсткие ссылки на кеш uv (`find -links`), то есть диск они почти не занимают (заодно объясняет, почему кеш uv не чистится).

**Squash-merge и гейты** (`workspace.py::merge_worktree_to_main`, `merge_operations.py`, `acceptance.py`, `diff_budget.py`): всё под межпроцессным `flock` репозитория (`repo_mutation_lock`, то есть слияния одного репо строго последовательны); перед слиянием `git merge-tree --write-tree --name-only` — детектор конфликтов без изменения дерева; потом `git merge --squash` в основной worktree; жёсткий потолок `MAX_DIFF_INSERTIONS = 2000`; приёмка (acceptance-oracle задачи) выполняется платформой **в worktree воркера** (`acceptance.evaluate_pinned_oracle(oracle, current["worktree_path"])`) — тесты запускаются на его копии.

**Фактические показатели слияний** (БД, `created_at ≥ 10.09`, `started→finished`):
- успешные 987: p50 2.5 с, p90 29.3 с, p99 134.5 с, макс 553 с. По репо: seedon p50 1.7 / p90 5.7 с (283 шт.), katya-work 2.0 / 8.8 с (221), comfy 2.5 / 7.3 с (109), dnd 1.9 / 5.3 с (53); **orchestra p50 17.4 / p90 69.6 / макс 553 с** (260) — это время тестового гейта, не git.
- неуспешные 366 из 1353 завершённых; коды: CONFLICT 69 (5.1% всех, 19% отказов), TEST_GATE_FAILED 20 (1.5%), DIFF_TOO_LARGE 19, NO_COMMITS_MERGED 70, SESSION_IDENTITY_CHANGED 10, WORKER_DIRTY 8, TEST_MUTATION_GATE_FAILED 3; LEGACY_UPSTREAM_ERROR 107 и WAITING 49 — служебные/ожидание, не конфликты.
- Занятость блокировки репо: orchestra 260 слияний × среднее < 1 мин за 33 дня ≈ 0.3% времени (оценка по p50/p90); у остальных репо ещё меньше. Лок — не узкое место при нашем потоке.
- Рефы: orchestra 1476 (из них 1045 веток), `git for-each-ref` 23 мс; seedon 523. Для нас «рефы дорого» не проявляется.

**Измеренная стоимость создания копии** (`git clone -s --no-checkout` + `git checkout`, на VPS под `nice 15`, один прогон, без повторов — шум не оценён):
| Репо | полный checkout | sparse (без `artifacts/`, `.orchestra/`) | место: полный → sparse |
|---|---:|---:|---:|
| orchestra | 2.76 с | 0.22 с | 0.354 → 0.031 ГБ |
| seedon | 10.08 с | 1.74 с | 1.385 → 0.380 ГБ |
(sparse там исключал и весь `.orchestra/`; реальному воркеру нужны `.orchestra/kb|workers|pipelines` и своя папка задачи, поэтому выигрыш по orchestra меньше: реально убирается около 0.30 ГБ из 0.34.) Время старта сессии модели я не мерил — оно не входит в эти секунды.

**Проверка sparse × merge/сложные места** (`evidence/sparse_merge_test.out`, один прогон на клоне orchestra, git 2.43):
- файл вне cone при `git add -A` отказывает («matched paths that exist outside of your sparse-checkout definition») — воркеру нужно `--sparse` или своя папка `.orchestra/tasks/<id>/` внутри cone;
- `git merge --squash` ветки, меняющей путь вне cone, в sparse-worktree отрабатывает и коммитится, путь попадает в дерево коммита и на диск не материализуется;
- два конфликтующих изменения вне cone дают конфликт `AA` (конфликт не теряется);
- не проверено: acceptance-тесты, которые читают исключённые каталоги; `switch_worker_branch` (смена задачи ⇒ пересчёт cone); поведение `git merge-tree` гейта (он работает на деревьях, должен не зависеть от cone — не мерил); большие репо вроде katya-work.

## 3. Идеи Scion → Orchestra

| Идея | Вердикт | Механизм переноса | Цена / риск | Что даёт в числах |
|---|---|---|---|---|
| Sparse/«ленивая» рабочая копия | **Брать, как опцию** (это же V-821) | `git sparse-checkout` в `create_worktree` через non-cone правила: всё, кроме `artifacts/`, `.orchestra/tasks/`; своя папка задачи и каталоги из `owned_dirs`/по запросу добавляются; cone-режим не подходит — нельзя исключить подкаталог внутри включённого `.orchestra/` | ~1 воркер-день на код + опрос оркестраторов (V-821); риски: тесты/acceptance, читающие исключённое; `switch_worker_branch`; `git add` вне cone | seedon: −1.0 ГБ и 10.1→1.7 с на копию (≈9 копий ≈ −9 ГБ); orchestra: −0.3 ГБ и 2.8→0.2 с на копию (≈2 ГБ на 7); katya-work: по V-821 ≈ −3 ГБ на копию (13 копий ≈ −39 ГБ, **не проверено мной**) |
| Слияние на сервере, нечего пушить | **Уже есть** | наш merge локальный и под локом, без push | — | — |
| Запросы к VCS как API (diff, merge base, blame без локальной копии) | **Частично есть**, расширять не нужно | `merge-tree`-предпроверка, `check_conflict`, `worker_wip`; для read-only воркеров (исследования, Haiku-сборщики) можно выдавать копию без checkout (`git show`/`git archive` из общего `.git`) | малая правка `create_worktree` + режим «read-only workspace»; риск — воркеры без рабочего каталога ломают привычные инструменты | экономит ту же копию; доля read-only воркеров по БД не считалась |
| Без глобальной очереди слияния; тесты после слияния | **Не брать** | — | у нас 30 слияний/день, лок занят ≈0.3% времени; CONFLICT всего 5.1%, тестовый гейт ловит 1.5% — гейт дешевле, чем чинить main постфактум | сэкономим: 0 (проблемы масштаба Anthropic у нас нет) |
| Refs не плодить | **Не брать** | — | 1045 веток, `for-each-ref` 23 мс | 0 |
| Нет packfile и обслуживания репо | **Не брать** | — | `git gc` даёт < 0.3 ГБ (V-825); katya-work: 1.63 ГБ мусорных `tmp_pack_*` — это дефект упаковки, не архитектуры | ≈1.6 ГБ разово у katya (зона её оркестратора) |
| Derived data (blame/path history/skip lists) | **Не брать** | — | у git есть `commit-graph`; нас не тормозит | 0 |
| Три яруса кеша (daemon/cache/server) | **Не брать** | — | у нас один хост, объекты уже общие в `.git`, сети между ними нет | 0 |
| Copy-on-write/виртуализированные файлы | **Не получится на этом диске** | требует reflink (btrfs/xfs) или FUSE/VFS; на ext4 (`findmnt`) недоступно | миграция ФС или FUSE-слой — несоразмерно | — |
| Семантические ограничения ревью (comment-only ≠ логика) | **Идея на потом** | автоклассификатор диффа: docs/комментарии без кода → облегчённый путь гейта | риск обойти защиту; нужен owner-решение, как с `MAX_DIFF_INSERTIONS` | доля «лёгких» диффов в БД не считалась |
| «Superfan»-агенты на компоненты | **Не брать сейчас** | у нас сторожа без модели (`runaway_guard`, сторож диска) | модель-мониторы тратят подписку, выгода неизмерима | — |
| Ревью по намерению, а не построчно | **Уже есть** (оркестратор принимает по отчёту/диффу) | — | — | — |
| Герметичные симуляции и fuzzing инфраструктуры | **Не брать сейчас** | — | у нас сотни регрессионных тестов, но симуляций гонок слияния нет; польза без инцидентов неизмерима | — |

## 4. Вывод для владельца (предложение, не мандат)

Новость почти ничего не меняет для нас: их проблемы (30 000 слияний/день, 100 ГБ истории, сотни зеркал) отсутствуют — у нас ≈30 слияний/день, общий `.git` без сети, merge-lock занят доли процента. Единственная идея из статьи, которая бьёт в нашу реальную боль (диск, 13.10 доходил до 95%), — «рабочая копия опциональна и sparse»; она уже записана как V-821, а теперь есть измерения: seedon ≈ −1.0 ГБ и 5.8× быстрее создание копии, orchestra ≈ −0.3 ГБ и 12× быстрее, katya-work по V-821 ≈ −39 ГБ из 58.8. Совместимость sparse с squash-слиянием и обнаружением конфликтов на одном образце подтверждена; не закрыты: acceptance-тесты, `switch_worker_branch`, опрос оркестраторов. Реализация — только по слову владельца.

## Ограничения исследования
Один образец на каждый замер checkout (без повторов, на загруженном хосте), поэтому «5.8×» и «12×» — порядок, не точная кратность. Sparse-тест на клоне orchestra, не на живом worktree воркера. katya-work не мерилась (опора на V-821). Содержимое графиков статьи недоступно. Время запуска сессии модели не оценивалось.
