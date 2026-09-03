# #412 — Раздача базы знаний по репозиториям проектов

Срез данных: **2026-08-27 14:49 UTC**. Код проверялся по `main` на
`99fa70980f2fe639099aa41e539f9f6b03b6d661`; central canonical — HEAD
`309f4b058a57576065b15f421679de670ab248f8`. Работа research-only: live-данные,
код и репозитории проектов не менялись.

## Зафиксированное решение пользователя

- База знаний проекта живёт **внутри его Git-репозитория, в `<project>/docs/kb/`**.
- Central `~/.local/state/orchestra/knowledge-v1/` не остаётся владельцем или общим кешем:
  project records раздаются своим проектам.
- После cutover в контуре Orchestra остаются знания самой Orchestra и engine state:
  registry активных проектов/агентов, runtime sessions, delivery state и account quotas.
- Сначала выполняется byte-preserving раздача, затем отдельным коммитом меняется формат.

Вопрос «куда» закрыт. Этот отчёт отвечает, **что, кому, в каком формате и каким
проверяемым порядком раздать**.

## Короткий вывод

На срезе central Git содержит **20,948 immutable evidence records / 13,103,260 apparent
bytes по 17 проектам**. Все 17 source repository сейчас доступны и являются Git repo;
четыре из них не имеют remote, поэтому **1,754 records ещё нельзя считать переносимыми в
cloneable состояние**. Зарегистрированный `/mnt/data/media` не является Git repo и имеет
0 evidence records, но уже имеет 1 debt record — это отдельный special case.

В `main` текущая человеческая база Orchestra — **21 Markdown-файл, 276,065 apparent bytes,
335,872 allocated bytes (`du -sh` = 328K)**. Пять готовых extraction-файлов содержат
**764 facts / 588,931 bytes**: 689 current, 75 rejected, 284 topic labels, 22 source files.
Переизвлекать их не надо.

**Рекомендация формата одной строкой:** сохранить `docs/kb/*.md` для людей и grep, а
machine-state хранить в том же каталоге как **один canonical JSON record на файл** под
`docs/kb/records/`; YAML и монолитные JSON не использовать.

Полная работа оценивается в **17–30 engineer-days**. Основная цена — не копирование 13.1 МБ,
а смена шести owners: runtime, typed knowledge, projection/search, cutover, scripts и prompts.

## 1. Карта и граница

### 1.1. Что переезжает, а что остаётся engine state

| Слой | Текущий путь и объём | Целевой путь/судьба | Почему |
|---|---|---|---|
| Human KB Markdown | `<repo>/docs/kb/*.md`; Orchestra `main`: 21 файла / 276,065 apparent Б / 335,872 allocated Б | остаётся на месте | уже удовлетворяет правилу «clone repo → knowledge приехала» |
| Immutable evidence records | `/home/maxim/.local/state/orchestra/knowledge-v1/canonical/evidence/<project>/*.json`; **20,948 / 13,103,260 Б** | `<repo>/docs/kb/records/evidence/<stable_id>.json` | project data; record уже содержит `project_id`, Git commit/blob, source path и digest |
| Extracted facts Orchestra | `main:docs/tasks/kb-extract/part-1..5.json`; **764 / 588,931 Б** | `/mnt/data/Projects/Python/orchestra/docs/kb/records/facts/<topic>/<fact_key>/<stable_id>.json` | это facts только из KB/CLAUDE.md проекта Orchestra, не общий corpus 17 проектов |
| Fact events/topic registry | central `canonical/knowledge/`; сейчас только пустой `registry.json` 35 Б, facts 0 | `<repo>/docs/kb/records/{events/,registry.json}` | typed history принадлежит тому же project Git |
| Project task states/events | central `canonical/tasks/projects/`; **690 states + 877 events / 3,739,587 Б** | `<repo>/docs/tasks/records/...`, не `docs/kb/` | task history — project data, но не knowledge topic; 8 alias/unregistered states требуют identity resolution (§1.4) |
| Project debt | `/home/maxim/.local/state/orchestra/knowledge-v1/debt/`; 233 / 54,161 Б, из них 218 project-tagged | `<repo>/docs/kb/records/debt/`; non-project debt остаётся engine | privacy/source debt должен ехать рядом с record, иначе gate ложно зеленеет |
| Current projection | `…/knowledge-v1/current.db`; 808,095,744 Б, 20,463 records, **8,255 foreign / 85,080,576 chars** | foreign rows удалить после project parity; при необходимости индекс строится project-local и gitignored | derived copy не может остаться «знанием X ещё и в Orchestra» |
| Legacy vector/FTS | `/mnt/data/Projects/Python/orchestra/data/vec.db` + WAL; 760,606,720 + 10,551,352 Б | foreign file/log chunks удалить; project search работает по files/grep либо local rebuildable index | central content copy запрещён фиксированным решением |
| Scope/project attachment registry | `/home/maxim/.local/state/orchestra/knowledge-v1/scope-registry.json`; 18 entries | **остаётся engine state**, но project manifest становится owner `canonical_project_id` | engine должен авторизовать scope→repo; registry нельзя удалять до manifest parity |
| Runtime receipts/state | `runtime-state.json`, generation/gate receipts | остаются engine state, перестают содержать foreign content heads | cutover/recovery — свойство движка, не знания проекта |
| Agent/session registry и logs | `/mnt/data/Projects/Python/orchestra/data/orchestra.db`: 543 sessions, 196k+ logs | остаются engine state по прямому решению пользователя | resume, dashboard, delivery, parent/child и native runtime требуют общий registry |
| Quota/usage | `usage_snapshots`, `turn_usage`, quota decisions | aggregate остаётся engine; project attribution может быть ссылкой | provider subscription window общий для всех проектов |
| Active message/merge/TG journals | `message_deliveries`, `merge_operations`, `tg_file_deliveries` | остаются engine до terminal state | FIFO, idempotency и UNKNOWN delivery не принадлежат одному repo |

Evidence и facts — разные сущности. **20,948** — immutable references на Markdown snapshots;
**764** — уже извлечённые atomic claims Orchestra. Раздача не дедуплицирует и не превращает
20,948 evidence в 764 facts: первый проход обязан сохранить каждый source record byte-for-byte.

### 1.2. Таблица раздачи evidence

Целевой suffix для всех Git repo одинаков:
`docs/kb/records/evidence/<stable_id>.json`.

| Canonical project | Records | Apparent bytes | Repository root | Git / remote | Точный destination directory |
|---|---:|---:|---|---|---|
| `orchestra` | 12,759 | 7,607,020 | `/mnt/data/Projects/Python/orchestra` | yes / 3 | `/mnt/data/Projects/Python/orchestra/docs/kb/records/evidence/` |
| `cog-second-brain-77dd306ac2a0` | 5,106 | 3,436,902 | `/home/maxim/Рабочий стол/Cursor/COG-second-brain` | yes / 2 | `/home/maxim/Рабочий стол/Cursor/COG-second-brain/docs/kb/records/evidence/` |
| `scope-mnt-data-projects-comfy-image-pipeline-11e5d3b4b1f9` | 1,728 | 1,209,380 | `/mnt/data/Projects/comfy-image-pipeline` | yes / **0** | `/mnt/data/Projects/comfy-image-pipeline/docs/kb/records/evidence/` |
| `seedon` | 321 | 189,043 | `/mnt/data/Projects/Python/seedon` | yes / 1 | `/mnt/data/Projects/Python/seedon/docs/kb/records/evidence/` |
| `sensar-5e197e867bb2` | 180 | 115,021 | `/home/maxim/Рабочий стол/Cursor/Sensar` | yes / 1 | `/home/maxim/Рабочий стол/Cursor/Sensar/docs/kb/records/evidence/` |
| `tradingcryptobot` | 177 | 111,200 | `/mnt/data/Projects/Python/TradingCryptoBot` | yes / 1 | `/mnt/data/Projects/Python/TradingCryptoBot/docs/kb/records/evidence/` |
| `mnt-data-projects-python-claude-code-game-master-ccdad4e9b586` | 152 | 109,706 | `/mnt/data/Projects/Python/Claude-Code-Game-Master` | yes / 2 | `/mnt/data/Projects/Python/Claude-Code-Game-Master/docs/kb/records/evidence/` |
| `mnt-data-projects-python-aperant-0972b1340a75` | 112 | 75,751 | `/mnt/data/Projects/Python/Aperant` | yes / 2 | `/mnt/data/Projects/Python/Aperant/docs/kb/records/evidence/` |
| `kesha-tg-bot` | 96 | 57,895 | `/mnt/data/Projects/Python/kesha-tg-bot` | yes / 1 | `/mnt/data/Projects/Python/kesha-tg-bot/docs/kb/records/evidence/` |
| `polus` | 86 | 48,480 | `/home/maxim/polus` | yes / 1 | `/home/maxim/polus/docs/kb/records/evidence/` |
| `university` | 77 | 46,439 | `/mnt/data/Projects/University` | yes / 1 | `/mnt/data/Projects/University/docs/kb/records/evidence/` |
| `vpn-service-7c16d6f598b1` | 75 | 46,944 | `/mnt/data/Projects/Python/VPN-Service` | yes / 2 | `/mnt/data/Projects/Python/VPN-Service/docs/kb/records/evidence/` |
| `parsing-hub` | 43 | 25,923 | `/mnt/data/Projects/Python/Parsing` | yes / 1 | `/mnt/data/Projects/Python/Parsing/docs/kb/records/evidence/` |
| `stargate-tactics` | 12 | 7,325 | `/mnt/data/Projects/Python/stargate-tactics` | yes / **0** | `/mnt/data/Projects/Python/stargate-tactics/docs/kb/records/evidence/` |
| `mnt-data-projects-unity-defaultprojectunity-317002a674e4` | 10 | 7,246 | `/mnt/data/Projects/Unity/DefaultProjectUnity` | yes / 1 | `/mnt/data/Projects/Unity/DefaultProjectUnity/docs/kb/records/evidence/` |
| `mnt-data-projects-python-games-b14eae05bed5` | 9 | 5,880 | `/mnt/data/Projects/Python/games` | yes / **0** | `/mnt/data/Projects/Python/games/docs/kb/records/evidence/` |
| `webview-c212de852078` | 5 | 3,105 | `/mnt/data/Projects/Python/WebView` | yes / **0** | `/mnt/data/Projects/Python/WebView/docs/kb/records/evidence/` |
| **Итого** | **20,948** | **13,103,260** | 17 reachable Git repo | 4 repo / 1,754 records без remote | union destinations |
| `mnt-data-media-30494f74a194` | **0** | 0 | `/mnt/data/media` | **no Git** | special: создать Git owner либо quarantine (§1.3) |

Четыре repo без remote — Comfy, stargate-tactics, games, WebView. Записать records в их
локальные Git branches недостаточно: требование «скопировал repo» не доказано, пока не создан
private remote и не выполнен fresh clone с тем же manifest head.

### 1.3. Осиротевшие, недоступные и non-Git scopes

На текущем срезе **0 из 20,948 evidence records осиротели**: все 17 destination repo доступны.
Но механизм обязан fail-closed.

| Случай | Явное место | Статус миграции | Что нельзя делать |
|---|---|---|---|
| Repo временно недоступен | `/mnt/data/Projects/_orchestra-orphans/<project_id>/docs/kb/records/` в отдельном private Git repo | `quarantined: repository_unreachable`; global cutover заблокирован | не отдавать record соседнему project и не считать его перенесённым |
| Project удалён/identity неизвестна | тот же quarantine + manifest с old scope/project id/digest | требуется ручное назначение owner или явное решение удалить | не угадывать repo по похожему basename |
| `/mnt/data/media` non-Git | предпочтительно создать Git owner прямо для `/mnt/data/media/docs/kb/`; до решения — quarantine `mnt-data-media-30494f74a194` | сейчас 0 evidence, 1 debt; cutover future writes заблокирован | не складывать media knowledge обратно в Orchestra |
| Git repo без remote | record можно stage локально, но статус только `prepared`, не `verified` | remote + fresh clone обязательны | не удалять central source после локального commit |

Quarantine — временный владелец вне repo Orchestra, а не конечная база. Его manifest входит
в global count; ненулевая quarantine count запрещает финальный cleanup central store.

### 1.4. Task records вне evidence registry

Из 690 task states **682** уже имеют прямой registered project id. Оставшиеся 8 не
выбрасываются:

| Canonical id | States / events | Найденный candidate repo | Требуемый гейт |
|---|---:|---|---|
| `mnt-data-cursor-cog-second-brain-ebf4c5a1c0e2` | 2 / 2 | COG repo | доказать alias→`cog-second-brain-77dd306ac2a0` по legacy identity |
| `university-9d38443e2220` | 2 / 2 | `/mnt/data/Projects/University` | доказать alias→`university` |
| `mnt-data-projects-python-orchestra-13dc8d0cd9fb` | 1 / 1 | Orchestra repo | доказать alias→`orchestra` |
| `family-tree` | 1 / 1 | `/mnt/data/Projects/Python/Parsing/family-tree` (Git, remote `origin`) | добавить project manifest/registry entry |
| `inscryption-ai` | 1 / 1 | `/mnt/data/Projects/Python/inscryption-ai` (Git, remote `origin`) | добавить project manifest/registry entry |
| `zahoron-mobile` | 1 / 1 | `/mnt/data/Projects/Python/Parsing/zahoron-mobile` (Git, remote `origin`) | добавить project manifest/registry entry |

До доказанного mapping эти 8 states идут в quarantine, а не в «наиболее похожий» repo.

## 2. Формат внутри `docs/kb/`

### Измеренный baseline

- Markdown: 21 files; 276,065 apparent Б; 335,872 allocated Б; `README.md` + 20 topic files.
- Extraction: 5 JSON arrays; 588,931 Б; 764 facts; 689 current / 75 rejected;
  284 labels; 22 source files.
- У 275/764 facts `decided_at=null`, у 397/764 `reason=null`. Миграция обязана сохранить
  `unknown/null`, а не выдумать дату или причину.
- `scripts/kb_promote_facts.py:96-106,366-423` уже задаёт deterministic UUIDv5,
  `fact_key`, reason/date/evidence metadata и provenance. Это готовый mapping, не новая extraction.

### Сравнение

| Вариант | Читается/правится человеком | Merge двух агентов | Поиск без индекса | Причина и дата | Цена/риск |
|---|---|---|---|---|---|
| Только Markdown как сейчас | лучший | разные topic files merge; append в один topic/README конфликтует; stable fact identity нет | лучший: `rg`/обычный просмотр | контракт просит evidence/date, но не валидирует; текущие пропуски возможны | самый дешёвый, но не закрывает typed state/supersession |
| Один YAML/JSON на topic или весь project | YAML читаемее JSON, но ручные commas/indent/schema ошибки | один файл становится merge hotspot; независимые additions конфликтуют вокруг списка/closing token | `rg` работает, но контекст хуже | schema может требовать поля | не использовать: новый YAML parser/canonicalization или конфликтный monolith |
| **Hybrid: Markdown + one-record-per-file JSON** | Markdown остаётся human entrypoint; JSON редактируем точечно | разные facts создают разные files; конфликт одного `stable_id` желателен и fail-loud | `rg` ищет и `.md`, и JSON; README работает без index | JSON schema хранит `reason`, `decided_at`, status, provenance; null остаётся явным | использует текущий JSON validator/UUID mapping; нет новой зависимости |

One-record-per-file не новый untested shape: central evidence уже хранит так 20,948 files;
весь mixed canonical Git с 68 commits занимает 49,559,679 apparent Б. Цена checkout/inode
остаётся, но merge разных stable IDs не создаёт общего list hotspot.

### Рекомендуемое дерево

```text
docs/kb/
├── README.md
├── <topic>.md
├── manifest.json
└── records/
    ├── evidence/<stable_id>.json
    ├── facts/<topic>/<fact_key>/<stable_id>.json
    ├── events/<event_id>.json
    └── debt/<debt_sha256>.json
```

Дублирования истины нет: Markdown — human explanation/source evidence; JSON fact — promoted
atomic state с явной ссылкой на Markdown path+lines+Git commit. `manifest.json` содержит
schema version, `canonical_project_id`, heads/counts и не повторяет bodies.

## 3. Кто должен узнать о project-local owner

Literal path `docs/kb/` уже правильный; менять его на другой нельзя. Меняется **семантика owner**:
central JSON перестаёт быть truth, а project folder становится truth.

### Production code и API

| Owner (`main`) | Сейчас | Требуемое изменение | Пропуск ломает |
|---|---|---|---|
| `app/ia/runtime.py:432-488,745-863,1788-1837` | central scope registry; импортирует каждый `.md` в central `evidence/<project>`; поднимает один KnowledgeService | resolve repo from project manifest; писать/читать `<repo>/docs/kb/records`; registry оставить attachment map | новые records снова окажутся central; fresh clone не самодостаточен |
| `app/ia/knowledge.py:165-324,485-815,825-956` | один `canonical_root`, пишет registry/facts/events/evidence refs | per-project service/root; source root = текущий Git repo, не absolute old scope | promote/query смешивают проекты или пишут старый root |
| `app/ia/projections.py:521-772,920-983` | собирает один canonical head и central current projection; legacy rebuild пишет central refs | vector-of-project heads либо strictly project-local read; foreign central projection удалить | stale/foreign knowledge останется в engine |
| `app/ia/cutover.py:23-38,262-493` | прямо считает `Read docs/kb` и `Append ... docs/kb` forbidden legacy directives | инвертировать gate: эти anchors обязательны; cutover manifest = project repo commits | корректные prompts будут блокировать новый cutover |
| `app/routes/knowledge.py:18-70` | один configured knowledge runtime | route по caller scope в project service | API авторизует scope, но читает чужой/global owner |
| `app/routes/memory.py:31-128` | gen3 branch читает central runtime; legacy branch — central RAG | project-local Markdown/facts; cross-project только on-demand federation без stored copy | `search_memory` выдаёт старый central content |
| `app/rag.py:756-850`, `app/rag_service.py:20-190` | индексирует все `.md` и logs в один `data/vec.db` | Markdown reader остаётся; index path partition/project-local и rebuildable | foreign chunks остаются второй копией knowledge |
| `app/mcp_stdio.py:2920-2993` | `knowledge`/`search_memory` — agent consumers | contract/result source должен показывать project head/path | агент не различит local truth и stale cache |

### Prompts — полный literal-owner список

| Файл (`main`) | Роль | Что делать |
|---|---|---|
| `pipelines/default/prompts/base.md:66,69` | говорит, куда писать durable knowledge | путь оставить; добавить, что JSON/Markdown owner — текущий repo, runtime memory/central store запрещены |
| `pipelines/default/prompts/modules/memory-search.md:7-16` | mandatory pre-work read | README/topic read оставить; machine facts читать через project-local `knowledge`, не central |
| `pipelines/default/prompts/modules/research-method.md:107-155` | writer contract Markdown KB | Markdown append оставить; добавить delivery check manifest/fact promotion, если есть structured fact |
| `pipelines/default/prompts/modules/orchestration.md:20` | approval gate требует KB entry | путь оставить |
| `pipelines/default/prompts/modules/report-format.md:30` | отчёт Phase 1 | путь оставить |
| `pipelines/default/prompts/roles/full-cycle.md:43-46` | обязательный writer | путь оставить; owner semantics получает из base/research-method |
| `pipelines/default/prompts/roles/orchestrator.md:68` | что сохранять из user decision | путь оставить |

Prompt rollout идёт **последним**: code owner должен сначала успешно прочитать real project-local
record из настоящего agent contour. Иначе обязательный prompt ломает всех агентов.

### Scripts, tests и offline consumers

| Файл (`main`) | Сейчас | Изменение |
|---|---|---|
| `scripts/kb_promote_facts.py:76-106,141-205,326-443,570-760` | читает готовые 764 facts/source Markdown, но default output — central canonical/API | сохранить extraction и UUID logic; output/root сделать project `docs/kb/records` |
| `scripts/ia_migrate_documents.py:1-16` | wrapper старого central document cutover | заменить fixed project-distribution manifest/API |
| `scripts/kb_extract_report.py:118` | human report про 20 topics | факты не переизвлекать; только обновить текст источника при необходимости |
| `docs/tasks/256/eval/audit_structure.py:80-162` | offline audit `docs/kb` linkage | расширить на `manifest.json`/records, сохранив Markdown checks |
| `tests/test_kb_promote_facts_script_409.py` | pins source paths и central root | перепинить project-local destination; immutable 764 corpus |
| `tests/test_knowledge_import_linking_409.py` | pins `docs/kb/repo-ops.md` evidence import | проверить repo-relative source без absolute scope |
| `tests/test_knowledge_runtime_evidence_link_409.py` | runtime evidence link | проверить project root routing |
| `tests/test_knowledge_runtime_debt_361.py`, `tests/test_knowledge_detail_summary.py` | central projections/heads | новые per-project heads и zero-foreign central projection |

## 4. Порядок раздачи, поломки и обратимость

**Раздача сначала, формат потом.** Если сначала преобразовать central records, одновременно
меняются bytes и owner: при расхождении невозможно понять, потеря случилась в transformation
или routing. Byte-identical landing даёт один доказуемый переход; format conversion затем
становится обычным Git commit внутри каждого проекта.

| Шаг | Действие | Цена | Что ломается/гейт | Обратимость |
|---|---|---:|---|---|
| G0 | off-host backup exact central snapshot (§7) | 0.5–1 день | без verified restore следующие шаги запрещены | bundle restore |
| G1 | frozen global manifest на HEAD `309f4b…`: 20,948 evidence + task/debt inventories | 1–2 дня | новый central HEAD после freeze → abort/rebuild manifest | read-only, ничего откатывать |
| G2 | project manifests с сохранёнными IDs/aliases; remotes для 4 repo; media/orphan policy | 1–2 дня | collision/unreachable/no remote → project остаётся `blocked`, global cutover не начинается | revert manifest commit |
| G3 | byte-identical landing в 17 migration branches; task records отдельно в `docs/tasks/records` | 2–4 дня | возможны Git conflicts/large file count; runtime всё ещё central | revert/delete migration branches |
| G4 | fresh-clone verification всех remotes + global digest parity (§6) | 1–2 дня | 20,948 total, per-project count или digest не совпали → stop | central owner не менялся |
| G5 | code/API/scripts dual-read shadow: project-local candidate сравнивается с central, writes временно dual | 5–8 дней | пропущенный owner даёт mismatch/debt; prompt ещё не меняется | feature generation → central |
| G6 | один global owner switch, привязанный ко всем 17 project commit SHAs; central read-only | 1 день | хотя бы один repo/head недоступен → switch не совершается | generation rollback на central snapshot |
| G7 | отдельный format commit: 764 готовых facts → per-fact JSON; Markdown остаётся | 2–4 дня | 764 mapping не 1:1, current/rejected/date/reason drift → revert format commit | `git revert` независимо от location cutover |
| G8 | rebuild/purge `current.db`/`vec.db`; создать fresh engine-only state root; удалить mixed central repo из engine | 2–4 дня | central scan обязан показать 0 foreign records/chunks; rollback требует G0 bundle | bundle + project commit revert до конца retention |
| G9 | после real-agent read success обновить prompts; после retention удалить temporary backup только по отдельному решению | 1–2 дня + retention | ранний prompt rollout ломает все agents; раннее удаление backup необратимо | prompt revert; backup deletion необратима |

**Итого: 17–30 engineer-days.** Data plane мал (13.1 МБ evidence), но 17 Git commits/remotes,
global owner generation и purge старых projections являются high-risk seams.

Минимум half-moved состояний достигается так: G3 готовит все repo, но ни один не становится
active; G6 переключает owner одной generation, содержащей полный map `project_id→commit SHA`.
Per-project постепенный active cutover не рекомендуется: он создаёт 17 комбинаций owners.

## 5. Судьба central store после раздачи

Решение фиксировано: shared project knowledge не остаётся ни owner, ни cache.

| Central component | После verified project cutover | Гейт удаления |
|---|---|---|
| `canonical/evidence/<project>/` | удалить из engine для всех projects; Orchestra records уже находятся в Orchestra repo `docs/kb/records/evidence/` | per-project raw-byte parity + fresh clones |
| `canonical/knowledge/` | future writes запрещены; facts/events живут в repo владельца | live `knowledge` read/write из project path |
| `canonical/tasks/projects/` | удалить после раздачи в project `docs/tasks/records/` и alias resolution | 690 states / 877 events parity |
| mixed central Git history | **не** лечить одним `git rm`: old objects сохраняют foreign data; создать fresh engine-control state, old exact bundle держать off-host до retention | G0 restore rehearsal + G8 zero-foreign scan |
| `current.db`, `task-current.db` | retire/rebuild без project bodies; не source of truth | foreign record count = 0 |
| central `vec.db` | удалить foreign file/log chunks; optional indexes только project-local/rebuildable | foreign chunk count = 0 |
| project debt | раздать в `docs/kb/records/debt/` | count/digest parity; quarantine=0 |
| `scope-registry.json`, runtime/gate receipts | оставить как engine attachment/cutover state | receipts больше не содержат foreign content owner |

Cleanup обратим только через G0 bundle до конца retention. Удаление bundle после retention —
отдельное необратимое действие, не часть первого cutover.

## 6. Чем доказать полноту и откат

### Frozen distribution manifest

Каждая source record строка:

```text
project_id | stable_id | source_relative_path | destination_repo |
destination_relative_path | size | sha256(raw bytes)
```

Manifest также хранит central source HEAD, `scope-registry.json` SHA-256, per-project count,
apparent bytes, digest sorted record list, target branch/commit/remote ref и quarantine reason.

### Обязательные проверки

| Проверка | Точный критерий |
|---|---|
| Count parity | per-project counts равны §1.2; union = **20,948**; task states/events = 690/877 |
| Byte parity | для каждого record SHA-256 raw source bytes = SHA-256 blob в target commit |
| Identity isolation | `project_id` record совпадает destination manifest; пересечение `stable_id` разных projects пусто |
| Git provenance | `git_commit:path` в destination repo разрешается в записанный `git_blob`; `source_sha256` совпадает blob bytes |
| Remote durability | fresh clone каждого remote содержит exact target commit и manifest; local branch не считается доказательством |
| Fact conversion | 764 inputs → 764 stable UUIDv5 outputs; 689 current + 75 rejected; null reason/date counts остаются 397/275 |
| Central cleanup | после G8 в engine central evidence/tasks/knowledge foreign count = 0; `current.db` foreign = 0; central vec foreign chunks = 0 |
| Live consumer | реальный agent current project читает known Markdown fact и structured fact; другой project их не получает |

Rollback до G8: переключить generation на frozen central HEAD и revert project migration
commits. После G8: восстановить verified bundle/control snapshot, затем revert project commits.
Удаление backup — отдельная необратимая операция и не входит в первый cutover.

## 7. Срочная резервная копия до раздачи

| Факт | Срез |
|---|---:|
| Central Git | `/home/maxim/.local/state/orchestra/knowledge-v1/canonical/` |
| HEAD / commits | `309f4b058a57576065b15f421679de670ab248f8` / 68 |
| Apparent size | 49,559,679 Б |
| Remote | **0** |
| `git fsck --full` | 0 errors |
| Non-rebuildable content | 20,948 evidence, 690 task states, 877 task events + Git history |

До G1 нужен **private off-host** backup, не каталог на том же `/mnt/data`:

1. Остановить knowledge/task mutations на короткий freeze и зафиксировать exact HEAD.
2. Создать `knowledge-v1-309f4b058a57576065b15f421679de670ab248f8.bundle`
   через `git bundle --all`.
3. Скопировать bundle в новый private off-host owner, например private bare remote
   `orchestra-knowledge-prelocality-412`; публичный `origin` Orchestra запрещён.
4. Вместе сохранить
   `/home/maxim/.local/state/orchestra/knowledge-v1/{scope-registry.json,runtime-state.json,debt/,receipts/}`
   и WAL-safe `sqlite3.Connection.backup()` файла
   `/mnt/data/Projects/Python/orchestra/data/orchestra.db` для task/session linkage.
5. В scratch на другом host выполнить bundle verify/clone, `git fsck --full`, затем доказать
   HEAD, 20,948 evidence и 690/877 task state/event counts.

Настроенного off-host destination в текущем config не найдено; значит backup gate сейчас
**не пройден**. Создание bundle займёт 15–30 минут и ≈49.6 МБ передачи; full control/DB
snapshot — ещё 20–60 минут и ≈0.7 ГБ. Четырём project repo без remote нужен отдельный
private remote до G4.

## 8. Findings и confidence

| Finding | Confidence | Основание |
|---|---|---|
| 20,948 evidence records однозначно распределяются по 17 reachable Git repo | **CONFIRMED** | direct filesystem JSON count + persisted scope registry, tier 1 |
| 1,754 records находятся в четырёх repo без remote | **CONFIRMED** | live `git remote` по каждой destination, tier 1 |
| `/mnt/data/media` — non-Git special case с 0 evidence/1 debt | **CONFIRMED** | scope registry + filesystem + debt inventory |
| Hybrid Markdown + per-record JSON лучше закрывает четыре критерия пользователя | **LIKELY** | current 21-file Markdown corpus, 764 JSON corpus и primary schema/UUID code; migration не выполнена |
| Раздача до format conversion уменьшает число независимых причин mismatch | **LIKELY** | byte-parity oracle существует только до transformation; архитектурный вывод |
| 17–30 engineer-days | **LIKELY** | сумма диапазонов девяти named gates; это estimate, не elapsed measurement |
| Central без remote имеет critical loss impact | **CONFIRMED** | remote=0; projections не содержат Git history и не являются exact owner |

## Counter-evidence и открытые границы

- Большая часть пользовательского пути уже готова: `docs/kb/` лежит внутри каждого repo;
  prompt literals менять почти не надо. Основная работа — structured owner/cutover.
- Evidence JSON хранит references, а не Markdown bodies. Раздача 20,948 records сама по себе
  не создаёт curated KB; 764 facts решают только corpus Orchestra.
- Четыре no-remote repo и non-Git media опровергают тезис «раздали локально → backup решён».
- `app/ia/cutover.py` сейчас запрещает правильные `docs/kb` directives; старый cutover нельзя
  переиспользовать без изменения его семантики.
- `source_scope` в evidence содержит абсолютный путь старой машины. Byte-identical G3 сохраняет
  его ради proof; G7 schema v2 должен читать repository root из project manifest, не из этой строки.
- У 275 facts нет decision date, у 397 нет reason. Correct migration сохраняет unknown; она не
  может восстановить отсутствующий контекст без нового research.

## Affected files будущего плана

`app/ia/runtime.py`, `app/ia/knowledge.py`, `app/ia/projections.py`, `app/ia/cutover.py`,
`app/routes/knowledge.py`, `app/routes/memory.py`, `app/rag.py`, `app/rag_service.py`,
`app/mcp_stdio.py`, `scripts/kb_promote_facts.py`, `scripts/ia_migrate_documents.py`,
`scripts/kb_extract_report.py`, семь prompt-owner files из §3, named tests из §3.

Риски: live central HEAD drift; project ID aliases; missing remote; rewritten/shallow Git
history; one scope with nested repos; absolute source paths; privacy debt loss; prompt rollout
before live owner; deletion of old Git objects without verified off-host restore.

## Метод и источники

1. [Direct measurement] `find`/JSON parse central evidence, tasks, debt; `du -sb`, `du -s -B1`;
   watermark и exact per-project table в §1.2.
2. [Direct measurement] `git -C <repo> rev-parse --show-toplevel`, `git remote` для 17 repo;
   search of task candidates for family-tree/inscryption/zahoron.
3. [Direct measurement] parse `main:docs/tasks/kb-extract/part-1..5.json`: 764/588,931,
   status/topic/source/missing-field distributions.
4. [Primary code] `main:app/ia/runtime.py:432-488,745-863,1788-1837`;
   `main:app/ia/knowledge.py:165-324,485-815,825-956`.
5. [Primary code] `main:app/ia/projections.py:521-772,920-983`;
   `main:app/ia/cutover.py:23-38,262-493`.
6. [Primary code] `main:app/rag.py:756-850`; `main:app/rag_service.py:20-190`;
   `main:app/routes/{knowledge,memory}.py`; `main:app/mcp_stdio.py:2920-2993`.
7. [Primary code] `main:scripts/kb_promote_facts.py:76-106,141-205,326-443,570-760`;
   `main:scripts/ia_migrate_documents.py`; `main:scripts/kb_extract_report.py`.
8. [Primary prompt] семь exact prompt paths в §3, verified by `git grep -F docs/kb main`.
9. [Existing evidence] `docs/kb/knowledge-base-architecture.md`,
   `docs/kb/information-architecture-synthesis.md`, `docs/kb/task-storage-architecture.md`.

## Review status

Два Luna rounds были израсходованы на более широкую, затем superseded постановку до того,
как пользователь зафиксировал destination и обязательную полную раздачу. Артефакт
`docs/tasks/412/review-research-luna.md` сохраняет dissent и найденные backup/registry gaps;
они учтены здесь. Новый model round не запускался: это превысило бы prose ceiling. Поэтому
clean reviewer verdict именно для этой уточнённой версии отсутствует; приёмка опирается на
read-only counts, primary code trace и mechanical completeness checks.

Последний blocker старого scope требовал включить private artifact store в **full-system**
recovery. В уточнённом scope G0 — rollback именно knowledge/task distribution; artifact store
не source и на этом контуре пуст (`artifacts` table 0, resolved directory отсутствует).

Review gate inputs: author `gpt-5.6-sol`/Codex/full-cycle; changed consumers — только
`docs/tasks/412/research.md`, `docs/kb/data-locality.md`, `docs/kb/README.md`; AC — fixed
destination, distribution ledger, ≥2 formats, full owner list, reversible order, central cleanup,
pre-cutover backup. Mechanical command проверил source total `20,948 / 13,103,260`, facts
`764 / 588,931`, null date/reason `275/397`, 10 required section anchors и все 9 literal
`docs/kb` owners из `app/`, `pipelines/`, `scripts/`; missing owners = `[]`.
