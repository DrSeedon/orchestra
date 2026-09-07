# #523 — зачем размножается CODEX_HOME и что можно убрать

Исследование 06.09.2026; реализация, удаление каталогов и рестарт не выполнялись. Код проверен на `5c49d229882f40cac410df964f05a9c7a9b342fe` — уже с исправлением #520. `app/backend_codex.py` не изменён.

## Вопрос и критерии

Контекст: приватный home каждого Orchestra-воркера, CLI **0.153.4**, общий симлинк `sessions/`. Сравниваем нынешний посев полной базы с запуском без посева. Измеряем подключение, реальный ответ модели, MCP, shell, resume с сохранением содержания, размер собственной базы и причину накопления каталогов.

Гипотезы и заранее выбранные фальсификаторы:

1. **Посев необходим для самой работы нового треда.** Опровергается реальным ответом, MCP/shell и resume в изначально пустой базе.
2. **Убрать только посев достаточно для экономии диска.** Опровергается повторным ростом базы от общего `sessions/` средствами самого CLI.
3. **Уборка существует, но пропускает архивированных.** Опровергается цепочкой kill → manager → disconnect/archive без операции удаления home и отсутствием другого владельца managed-пути.

Граница проверки до запуска: один короткий ход Luna и одно продолжение; максимум 43 секунды на плечо, затем штатный disconnect. Таймаут ограничивает исследование, **не является требованием продукта** и не доказывает, что процесс никогда бы не запустился. Исследовательские homes находятся только в игнорируемом `data/523/` этого worktree. Нет копии производственной SQLite, полного прогона парка или изменений в живой БД Orchestra.

## 1. Зачем сеем и что наблюдается без посева

### Результат: новый воркер работает без чужой истории; нынешний общий sessions меняет исход

Запуск: `nice -n 15 /home/kesha/orchestra/.venv/bin/python .orchestra/tasks/523/probe.py private > .orchestra/tasks/523/private.log 2>&1`, затем отдельное плечо с аргументом `shared` и журналом `shared.log`.

Стенд использует настоящий `CodexBackend.connect()` и установленный CLI; в памяти исследовательского процесса заменён только `_managed_codex_state_needs_seed` на `False`, корень homes перенесён в `data/523/homes`. В private-плече заранее создан собственный непустой `sessions/`, который текущий `_prepare_codex_home` сохраняет. В shared-плече работает штатный симлинк на `~/.codex/sessions`. Auth остаётся штатным симлинком; конфиг собирается штатным кодом. MCP — настоящий stdio-протокол с одним безвредным тестовым инструментом, не подключение к живому менеджеру Orchestra. Рабочий каталог одинаковый и изолированный; модель `gpt-5.6-luna`, effort `low`.

| Плечо | Наблюдение | Размер state_5.sqlite + WAL |
|---|---|---:|
| Без посева, личный `sessions/` | Подключение **1.860923758 с**; `HOME523_MCP_OK`; `HOME523_SHELL_OK`; после disconnect/connect тот же thread-id и ответ **HOME523_MEMORY_731** | **2 826 328 Б** после двух ходов |
| Без посева, штатный общий `sessions/` | Через **43.129165740 с** подключение ещё не закончено; остановлено лимитом стенда; backfill=`running`, `last_success_at=NULL`, **389 тредов** | **229 442 528 Б**, из них основная БД **225 058 816 Б** |

**CONFIRMED, tier 1:** чужие сотни тредов не нужны для показанной работы нового воркера. **REFUTED, tier 1:** одно лишь отключение посева при нынешнем общем `sessions/` устраняет рост диска. CLI самостоятельно восстановил почти тот же объём ещё до подключения. Ошибки модели в shared-плече не было: до модели выполнение не дошло. Долгосрочная работоспособность shared-плеча после окончания backfill не измерялась. Полные выводы: [private.log](private.log), [shared.log](shared.log), [shared-intermediate.json](shared-intermediate.json).

Предыстория отвечает, зачем операция появилась: #305 вводила WAL-safe посев здорового завершённого индекса и восстановление состояния `running/NULL` на CLI **0.146.0**, вместе с устранением конкурентной загрузки одной сессии. Это защита холодного backfill/его восстановления, а не требование модели иметь историю других работников. В текущем коде `_managed_codex_state_needs_seed` проверяет `backfill_state`, `_select_managed_codex_state_source` выбирает `complete` с `last_success_at`, `_backup_codex_state` копирует **всю** БД. Current `connect()` прямо считает посев optional и разрешает запуск при отсутствии пригодного источника. **CONFIRMED, tier 2:** `app/backend_codex.py:574–599,609–642,1032–1078`; коммит `b604ef44`, [.orchestra/tasks/305/report.md](../305/report.md), целиком прочитанный [#520](../520/research.md). Исторический инцидент 0.146.0 не выдаётся за воспроизведение ошибки на 0.153.4.

### Что именно занимает 219 МБ

Свежий read-only срез базового `~/.codex/state_5.sqlite`: **232 497 152 Б = 232.50 MB = 221.73 MiB**, **794 треда**, 123 свободные страницы из 56 762. Отличие от размера в постановке — другой момент измерения; ниже единицы указаны явно. `dbstat` отнёс **230 621 184 Б** таблице `threads` (0.666 с на запрос). Суммы `length(cast(column AS blob))`:

| Поле threads | Байт |
|---|---:|
| `title` | 76 499 063 |
| `first_user_message` | 76 499 063 |
| `preview` | 76 499 063 |

Вместе **229 497 189 Б**, то есть **98.71%** файла. Это раздутая метаинформация тредов в трёх полях, а не 219 МБ обязательного контекста нового агента. Равенство суммарных длин само по себе не доказывает побайтное равенство значений каждой строки. **CONFIRMED, tier 1:** [base-state-summary.json](base-state-summary.json), [db-layout.json](db-layout.json), [thread-column-bytes.json](thread-column-bytes.json). Запросы: `SELECT name,sum(pgsize) FROM dbstat GROUP BY name` и `SELECT sum(length(cast(title AS blob))),sum(length(cast(first_user_message AS blob))),sum(length(cast(preview AS blob))) FROM threads`; `mode=ro`, таймбюджет 8 с, второй запрос занял 0.122 с.

### Что действительно теряется при пустом home

* **Буквально пустой home без auth** принимает `initialize` и `thread/start`, но `account/read` возвращает `account=null, requiresOpenaiAuth=true`. Это не готовый подписочный воркер. В положительной пробе auth/config сохранены, отсутствовали именно база и чужие rollouts. **CONFIRMED, tier 1:** [config-probe.log](config-probe.log). Оплачиваемый запрос без auth не отправлялся.
* **Resume чужого треда из другого пустого личного home** возвращает `-32600: no rollout found for thread id 01a07770-f335-7eb1-81dc-8c3f2ef19b34`. Собственный resume в исходном home проходит. **CONFIRMED, tier 1:** [resume-config-probe.log](resume-config-probe.log), [private.log](private.log).
* **Общая SQLite — отдельный рабочий примитив:** тому же другому home задан `sqlite_home` первого тестового home; `thread/resume` принят. Это проверка доступности истории через общую базу, без второго модельного хода и без проверки конкурентной нагрузки. **CONFIRMED в этой границе, tier 1:** `shared-index` в [resume-config-probe.log](resume-config-probe.log).
* В новом треде CLI выставил **`history_mode=paginated`** и создал `thread_history_1.sqlite` с `thread_turns`, `thread_items`, `thread_history_projection_state`, `thread_realtime_items`. **CONFIRMED, tier 1:** [private-history-layout.json](private-history-layout.json). Поэтому утверждение «весь home — удаляемый кеш, вся ценная история гарантированно в общем sessions» не доказано. Полноту восстановления paginated-данных из JSONL после удаления SQLite здесь не проверяли.

## 2. Реальные переключатели и места чтения

### Orchestra

| Имя / источник | Где читается и что делает |
|---|---|
| `CODEX_HOME` окружения родителя; иначе `~/.codex` | `_base_codex_home`, `app/backend_codex.py:402–403`: источник auth, sessions, базового конфига и базы-кандидата. `_build_env:2874–2878` переписывает **дочерний** `CODEX_HOME` на home воркера. |
| `ORCHESTRA_SESSION_ID` в env MCP `orchestra` | `_managed_codex_home_path:2757–2770`: ключ постоянного home. Корень `_CODEX_HOME_ROOT:311` жёстко задан как `~/.orchestra/codex-home`; отдельной настройки корня здесь нет. |
| Версия CLI и `_CODEX_STATE_MIGRATIONS_BY_CLI` | `connect:1041–1061`, `_managed_state_cli_version`, таблица `:313–375`: разрешают посев только известных схем. Отсутствующая БД → кандидат на посев; неизвестная версия/ошибка проверки → optional skip. Это кодовая таблица, не параметр пользователя. |
| Три скаляра базового `config.toml` | `_CARRIED_BASE_KEYS:377–381`, `_carried_base_scalars:745–760`: только `project_doc_max_bytes`, `model_context_window`, `model_auto_compact_token_limit`. `sqlite_home`, `[history]`, `[plugins]` из базового конфига **не переносятся**. |
| `CODEX_SQLITE_HOME` в окружении | Собственного чтения в Orchestra нет; `_build_env` наследует окружение и дополняет `_mcp_env`. CLI может прочитать переменную. Однако наш посев всё равно пишет `<managed-home>/state_5.sqlite` (`:654`): одна эта переменная **не отключает лишнюю копию**. |

**CONFIRMED, tier 2:** перечисленные функции и [home-references.txt](home-references.txt), полученный `rg -n 'codex-home|_CODEX_HOME_ROOT|_managed_codex_home_path|_codex_home' app scripts`. Отдельного env/config-переключателя `seed=false`, TTL homes или максимума размера базы на этом пути нет.

### Сам CLI 0.153.4

| Настройка / API | Наблюдение и владелец |
|---|---|
| `CODEX_HOME`; `$CODEX_HOME/config.toml`; `-c key=value` | CLI help описывает config override; фактический пустой home получает собственную базу. Reader: `core/src/config/mod.rs` в установленном бинарнике; CLI `config/read` показывает принятую конфигурацию. |
| `sqlite_home` | Директория SQLite; с `--strict-config -c sqlite_home="…/configured-db"` база создана в `configured-db/`, не в home. При одновременно заданном `CODEX_SQLITE_HOME` **конфиг победил env** в нашем контроле. |
| `CODEX_SQLITE_HOME` | При отсутствии `sqlite_home` база создана в `env-db/`. `config/read` при этом показывает `sqlite_home=null`: API-конфигурация не отражает env-derived путь. Reader обозначен в binary как `core/src/config/mod.rs`; принудительное требование — `core/src/config/requirements.rs:157`. |
| `history.persistence="save-all" / "none"`, `history.max_bytes` | Приняты `--strict-config`, видны в `config/read`; исходные значения `save-all` и `null`. Документированный лимит относится к **history.jsonl**, не размеру `state_5.sqlite` и не сумме managed homes. С `none` SQLite всё равно создана в нашем контроле. |
| `codex exec --ephemeral`; `thread/start.ephemeral` | CLI help и сгенерированная установленным бинарником JSON Schema подтверждают наличие. Это отказ от сохранения сессии, а не TTL существующих homes. Нынешний `CodexBackend` параметр не передаёт (`:1171–1205`). |
| `thread/start.historyMode = legacy / paginated` | Экспериментальное поле схемы; положительная проба без override получила `paginated`. Это выбор формата, не ограничение размера. |
| `codex archive`, `codex delete`, `codex unarchive` | Реальные команды над **сохранённой сессией**; `delete` описана как permanent delete. Они не означают удаления каталога Orchestra. Не вызывались. |

Источники: **tier 1** [config_probe.py](config_probe.py), [config-probe.log](config-probe.log), [resume-config-probe.log](resume-config-probe.log); **tier 2** [CLI exec help](cli-exec-help.txt), [CLI delete help](cli-delete-help.txt), [CLI archive help](cli-archive-help.txt), [schema-excerpt.json](schema-excerpt.json), [installed-settings.txt](installed-settings.txt), [binary-state-evidence.txt](binary-state-evidence.txt), [официальный config reference](https://learn.chatgpt.com/docs/config-file/config-reference). Отладочные строки бинарника подтверждают имена Rust-владельцев, **не заменяют прочтение их исходного текста**; точные строки чтения env восстановить из бинарника нельзя. Поведение путей проверено непосредственно.

**UNCERTAIN за пределами документированного интерфейса:** в открытом config reference, CLI help и проверенных настройках не найден общий TTL/byte-cap `state_5.sqlite` или автосборщик чужих `CODEX_HOME`. Это не утверждение, что в бинарнике вообще нет никакой внутренней уборки: там есть диагностика удаления stale remote plugin cache и pruning memory outputs. Эти механизмы не являются управлением сроком жизни каталога Orchestra.

## 3. Почему kill/archive оставляет home

Проверенная цепочка: `app/mcp_stdio.py:1927` (`kill_worker`) → HTTP `DELETE /api/sessions/{name}` → `app/routes/sessions.py:1694` → `SessionManager.remove`, `app/manager.py:1290–1321`.

`remove` отменяет фоновые задания, disconnect'ит загруженный backend, удаляет **worktree**, снимает FD ownership, вызывает `archive_session`, убирает объект из registry. `archive_session`, `app/db.py:2059–2073`, меняет статус строки на `archived`, сохраняет `finished_at` и снимает task binding. `CodexBackend.disconnect/_finalize_disconnect`, `:1661–1716`, закрывает процессы/каналы/ожидания; домашний каталог не удаляет. Фоновая уборка `app/manager.py:2543` вызывает только `cleanup_stale_worktrees`. Единственный `rmtree` в найденном соседнем session-пути удаляет **handoff staging**, `app/session.py:3724–3730`, с проверкой своего корня. **CONFIRMED, tier 2:** удаления managed Codex home в проверенном lifecycle-пути нет, отсутствует вызов CLI `delete/archive` от Orchestra.

**Что мешало:** найденного кодового запрета на уборку именно после окончательной архивации нет; операция просто не реализована. Удалять в обычном `disconnect` нельзя: один и тот же метод обслуживает reconnect, а наша положительная проба использует после него сохранённый тред. Кроме того, `_prepare_codex_home` изначально проектировался с общими rollouts ради resume (`:2793–2801`, история #224), а в 0.153.4 есть и локальная paginated history. Это конкретные границы будущей уборки, **не доказательство исторической причины, почему автор не написал её**. В #224 удалённая опасная подметалка относилась к конфигам Claude; переносить то решение на Codex без основания нельзя.

Снимок владельца содержит **294** элемента, **35** keep, **259** orphan, **68 462 303 203 Б** orphan (=63.76 GiB), **9 260 578 611 Б** keep. Среди **14** unknown есть `.locks` — служебный каталог, не 14 неизвестных работников. Число 37 после чистки — другой срез из постановки; не подменяем им 35 в snapshot. Несколько unknown (`550e8400-default`, `session-aaa`, `session-roundtrip`, `sess-codexcfg`) буквально совпадают с id тестов (`tests/test_mcp_config_isolation.py:148–161,259,316`; `tests/test_backend_codex.py:280–291`), которые вызывают `_prepare_codex_home` без переноса `_CODEX_HOME_ROOT`. Это достижимый источник каталогов вне БД; конкретный исторический запуск каждого unknown не установлен. **CONFIRMED совпадения/путь, LIKELY происхождение, tiers 1/2:** [snapshot-summary.json](snapshot-summary.json), исходный `.orchestra/tasks/523/codex-home-snapshot.json` в основном checkout, перечисленные тесты. Тесты с этим побочным эффектом здесь не запускались.

## Плагины: почему отдельно у каждого

Orchestra **не копирует** `plugins/cache` и `cache/remote_plugin_catalog`: `_prepare_codex_home` создаёт конфиг, auth/session symlinks, а `_backup_codex_state` копирует только SQLite. В новом private-плече этих каталогов не было, после работы CLI появились **28 137 128 Б plugins** и **1 257 551 Б cache**. Установленный бинарник содержит владельцев `core-plugins/src/remote/remote_installed_plugin_sync.rs` и `core-plugins/src/remote/catalog_cache.rs`, пути `plugins/cache` и `cache/remote_plugin_catalog`, диагностику загрузки remote bundles и сохранения каталога. **CONFIRMED, tiers 1/2:** [final-probe-sizes.json](final-probe-sizes.json), [installed-settings.txt](installed-settings.txt), [binary-state-evidence.txt](binary-state-evidence.txt), `app/backend_codex.py:2772–2837`.

Общий cache root Orchestra не задаёт, симлинков на него нет; CLI наполняет домашние каталоги независимо. Зачем вендор выбрал такую архитектуру, из бинарника не установлено. **Контрсвидетельство универсальной одинаковости:** свежие два live home дали разные tree SHA256, 200 против 212 файлов plugins, **13 695 650** против **17 242 449 Б** catalog. Снимок владельца этим не опровергается — кеши могут быть одинаковыми на одном срезе, но не являются неизменяемой общей константой. Хешировали относительные имена и SHA256 содержимого, не timestamps: [plugin-layout.json](plugin-layout.json). Дедупликация требует проверки обновлений/конкурентной записи, а не только одной сверки хешей.

## Варианты на решение владельца

MB ниже десятичные, MiB двоичные. Экономия state считается относительно **232 497 152 Б** нынешней базы; это размер начальной копии, не прогноз всей жизни агента. Полный private home после двух коротких ходов — **34 421 565 Б**, и каталог плагинов ещё не достиг размеров live-среза: нельзя обещать каждому воркеру постоянные 34 МБ.

| Вариант | Цена / что меняется или теряется | Экономия на spawn | Доказательство / остаточная проверка |
|---|---|---|---|
| **A. Не сеять вовсе, оставить нынешний общий `sessions/`** | Повторный backfill общего парка на каждом пустом home; быстрый старт теряется. Полного функционального отказа после окончания backfill не доказано. | **Устойчивой экономии нет:** за 43 с уже 229.44 MB state+WAL. | **Отвергнут как решение роста диска замером shared.** |
| **B. Не сеять вовсе; новым воркерам личные state и `sessions/`** | Свой тред, MCP, shell и reconnect работают. Произвольный старый/чужой thread-id в пустом home не находится; существующим воркерам нужны сохранённые homes либо адресный перенос истории. После kill личная история требует явного сохранения, если нужна позже. | В короткой пробе **229.67 MB ≈219.03 MiB** state; кеши плагинов остаются. | **Подтверждён минимальный рабочий сценарий.** Не проверены handoff/import, context% на всех переходах и полный срок жизни. |
| **C. Приватный config/auth, единый `sqlite_home`, без локального посева; общий `sessions/` сохранить** | Не теряем доступ к общему индексу в измеренном resume. Риск общего повреждения/блокировок; общий путь относится ко всем SQLite-backed подсистемам, не только state_5. Нужно проверить параллельные процессы, восстановление и совместимость полного набора БД. | Устраняет отдельную копию **232.50 MB ≈221.73 MiB** на новый home; записи самого нового треда останутся в общей БД. Это расчёт по отсутствующей копии, не массовый замер. | Путь `sqlite_home` и cross-home resume **измерены**. При текущем коде одна env-переменная недостаточна: посев продолжит писать лишний локальный файл. |
| **D. Сохранить посев, добавить уборку окончательно архивированных homes** | Новые и живые воркеры сохраняют текущую стоимость; нужны подтверждённое завершение всех владельцев, работа с symlinks без удаления целей и политика сохранения native history. Unknown из тестов не покрываются одним kill-hook. | **0 MB на spawn**; ориентир возвращаемого после archive места — текущие ~273 MB/home из постановки, фактически по inventory. | Код доказывает отсутствующий hook; безопасное удаление/восстановление не реализовывалось и не тестировалось. |

Плагины можно рассматривать отдельной добавкой к B/C/D: потенциально ещё порядка **42–45 MB логического содержимого на дубликат** по текущим двум samples, но общий writable cache не проверен. Это не главный выигрыш.

**Предложение:** выбирать между **B** (изоляция истории новых воркеров с явным переносом старых) и **C** (сохранение общего доступа через штатный `sqlite_home`). B уже подтвердил реальную работу модели, C подтвердил конфигурационный механизм и resume; C ещё нуждается в проверке общей конкурентной записи. A не достигает цели; D ограничивает сироты, но не размер живого парка. Реализацию ни одного варианта не начинаю — решение за владельцем.

## Ограничения, проверка и сохранённые материалы

* Базовые измерения не сравнивают seeded/unseeded TTFT статистически: seeded live baseline взят из #520, разные модель и момент. Вывод о росте shared опирается на прямые размеры, не сравнение времени двух моделей.
* В стенде нет systemd user bus, поэтому штатный backend выбрал прямой запуск без hibernation. Проверены connect/turn/disconnect/resume, не переживание рестарта Orchestra и не боевой MCP routing. Импорт: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/codex-home-audit/app/backend_codex.py`.
* Исследовательские файлы в `data/523/` сохранены, не удалялись; SQLite и auth не добавляются в git. `/proc`-проверка по точному префиксу исследовательских `CODEX_HOME` после проб дала `[]`: [process-check.json](process-check.json).
* Для review-gate прочитан `codex-debate`: изменены только исследовательские артефакты и KB, consumers — владелец и будущие агенты; author — текущий GPT-6/Codex worker; AC — три вопроса, оба эмпирических плеча, варианты/цена и KB. Названные команды и результаты выше. **Review: none — Sol not authorized**; выводы затрагивают сохранность runtime state, независимого strong oracle на весь выбор архитектуры нет. Модельный review не выдаётся за выполненный; решение остаётся у владельца.
* Pytest не запускался: production-код не менялся; вместо него выполнены реальные ограниченные пробы. Проверка синтаксиса probe-скриптов, KB-контракта, `git diff --check`, secret-shape scan и неизменности backend записана в `validation.txt`.

## Источники

1. **Tier 1:** [probe.py](probe.py), [probe_mcp.py](probe_mcp.py), журналы private/shared и JSON измерений рядом с отчётом; реальные CLI 0.153.4 и два модельных хода Luna.
2. **Tier 1:** [config_probe.py](config_probe.py), журналы config/resume-config; шесть сценариев initialize/config/account/thread без модельных вызовов.
3. **Tier 2:** текущие `app/backend_codex.py`, `app/manager.py`, `app/db.py`, `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/session.py`, перечисленные тесты; HEAD указан в начале.
4. **Tier 2 исторический / чужие измерения:** [#520 research](../520/research.md), [#305 report](../305/report.md), [#224 report](../224/report.md); `git show b604ef44`, `git log -S 'codex-home' -- app/manager.py app/backend_codex.py`.
5. **Tier 1 snapshot владельца:** `/home/kesha/orchestra/.orchestra/tasks/523/codex-home-snapshot.json`; прочитан, summary сохранён без изменения оригинала.
6. **Tier 2:** установленный `/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex`: help, generated schema, ограниченные строковые извлечения. Rust source text локально отсутствует; binary strings имеют более узкую доказательную силу, чем исходник.
7. **Tier 2:** [официальная Configuration Reference](https://learn.chatgpt.com/docs/config-file/config-reference), открыта 06.09.2026 через redirect с `https://developers.openai.com/codex/config-reference/`. Документация не привязана к тегу 0.153.4; наличие важных полей отдельно проверено установленным CLI.
