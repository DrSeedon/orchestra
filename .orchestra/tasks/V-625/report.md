# V-625 — спасение работы с ноутбука (23.09.2026)

Ноутбук maxim-911aird, доступ по обратному SSH-туннелю. Автор всех коммитов — из git config
ноутбука (Maxim, 65215214+DrSeedon@users.noreply.github.com), без Co-Authored-By. Force-push,
rebase и amend не применялись. Репозиторий Orchestra не трогался. Сервисы не перезапускались.

## Главная находка: «незакоммиченная работа» во многих репо — это обнулённые файлы

Ноутбучная Orchestra (запущена, uvicorn pid 313410) при каждом старте делает layout-migration
с сохранением грязного дерева (`app/orchestra_layout.py`, `migrate_project_layout_preserving_dirty`):
`git stash -u` → миграция → побайтовая запись файлов обратно → проверка **только статуса** (путь+XY),
не содержимого → `stash drop`. В какой-то момент файлы в дереве стали нулевой длины (причина
обнуления не установлена: журнал загрузок хранится только с 22.09), после чего каждый следующий
цикл сохранял уже нули и выбрасывал предыдущий стэш. Живое содержимое осталось только в
dangling-коммитах `orchestra-layout-preserve:*` (тысячи штук: comfy 8040, kesha-tg-bot 8067,
seedon 8065, polus 8067, WebView 8068), которые съел бы `git gc` через ~2 недели.

Что сделано: нулевые файлы **не коммитились** (это порча, а не работа). В каждом затронутом репо
последний полный снимок закреплён ссылкой `refs/rescue/layout-preserve-<дата>` (переживёт gc)
и запушен веткой `laptop-preserve-rescue` после проверки на секреты и большие файлы. Баг оформлен
через report_bug. Ноутбучную Orchestra не останавливал — решение владельца.

| Репо | Закреплённый снимок (refs/rescue/…) | Дата | Ветка laptop-preserve-rescue |
|---|---|---|---|
| comfy-image-pipeline | layout-preserve-20260913 = 7cecfd9a2 (27 tracked + 49 untracked) | 13.09 09:37 | 49898beb, 135 файлов (3 находки скана — `secrets.token_urlsafe` в коде, ложные) |
| kesha-tg-bot | layout-preserve-20260904 = ea7f2c2da | 04.09 23:03 | 9648b09, 99 файлов |
| seedon | layout-preserve-20260904 = c29954eeb | 04.09 23:03 | a411f86, 323 файла, **без .env** |
| polus | layout-preserve-20260909 = 37ba2ea13 | 09.09 12:10 | d572baf, 104 файла |
| TradingCryptoBot | layout-preserve-20260904 = 41f25adaa | 04.09 23:03 | 9808ac7, 180 файлов |
| WebView | layout-preserve-20260904 = 1b8a3ac28 | 04.09 23:03 | cb06425, 8 файлов |
| VPN-Service | layout-preserve-20260905 = 23cf7c856 (не повреждён) | 05.09 | d78d37c, 78 файлов |
| Parsing | layout-preserve-20260903 = 8f8b13bbc (не повреждён) | 03.09 | d979efb, 51 файл, **без CREDENTIALS.md и YOUGILE_ARCHIVE.md** |
| University | layout-preserve-20260903 = e2049cab3 (не повреждён) | 03.09 | a6ab274, 79 файлов |
| stargate-tactics | layout-preserve-20260903 = 3190a9c96 (не повреждён) | 03.09 | 4a7da72, 16 файлов |

Обнулённые пути без хорошего снимка: `Parsing/seo-platform/uv.lock` (tracked, 0 байт в дереве;
снимков preserve в этом репо нет — содержимое есть только в HEAD, рабочее дерево не трогал).
Пустые 0-байтные `.orchestra/kb/records/*` появлялись во всех снимках после 04–05.09 — их полные
версии в ветках выше.

## По проектам

«Ветки» — локальные ветки воркеров с коммитами, которых не было ни на одном remote; пушились под
тем же именем, а если имя на remote уже занято расходящейся веткой — как `laptop/<имя>`.
Стэши — как `laptop-stash/<N>`. В конце по каждому репо проверено `git rev-list --branches --not --remotes` = 0.

### С копией на VPS

| Проект | Закоммичено на ноутбуке | Запушено (куда) | Мерж в VPS | Вынесено в ветку и почему |
|---|---|---|---|---|
| seedon (PRIVATE) | 1 коммит: `.env` в .gitignore (сам .env не коммитился); worktree dev-lead: 4 файла → WIP в task-35/dev-lead | origin: `laptop-rescue-20260923` (main ноутбука: 3 коммита — своя миграция в .orchestra, курирование KB, правило поиска), 21 ветка, 3 стэша | нет | VPS `laptop-rescue-20260923` (локальная ветка). merge-tree с VPS main: конфликты add/add и rename/delete — обе стороны независимо переносили docs/ → .orchestra/ (.gitignore, .orchestra/kb/README.md, layout.json, tasks/*/research.md, workers/*.md). 186 файлов отличий, в основном раскладка. |
| seedon/infra (PRIVATE, seedon-infra) | — | 3 ветки; stash@{1}; stash@{0} очищен от `.env.local` (там OPENROUTER_MGMT_KEY) → laptop-stash/0 | — | оригинал стэша с ключом — только bundle на VPS |
| seedon/site (PRIVATE, seedon-site) | — | 8 веток, 1 стэш | — | — |
| COG-second-brain (PRIVATE) | — | main: merge origin/main без конфликтов → push; 22 ветки | **да**: /opt/cog-second-brain, дерево чистое, `git merge origin/main` без конфликтов → 9020e10. VPS не пушил (VPS main ahead 4 — у него свой ритм). | — |
| kesha-tg-bot (**PUBLIC**) | нули не коммитились | origin: `laptop-rescue-20260923` (3 docs-коммита уборки KB), 6 веток (task-14 → laptop/task-14/…), laptop-preserve-rescue | нет | VPS `laptop-rescue-20260923`: та же уборка KB сделана и на VPS другим текстом → add/add в `.orchestra/tasks/kb-research-cleanup/README.md`. Смысловой дубль — выбрать одну версию. |
| VPN-Service (PRIVATE) | — | origin: `laptop-rescue-20260923` (2 коммита: индекс KB, TODO про project-context.toml), 4 ветки + `main`, 2 стэша | нет | VPS `laptop-rescue-20260923`: конфликты .orchestra/kb/README.md, kb-research-cleanup/README.md, CLAUDE.md, docs/HANDOFF-to-vps.md |
| comfy-image-pipeline | нули не коммитились | существующий приватный DrSeedon/comfy-image-pipeline (там были только release/release-slim): main + 36 веток, laptop-preserve-rescue | нет | истории не связаны (merge-base нет): VPS-репо — новый `mfm-2026-infra` (экспонаты вынесены в отдельные репо), ноутбучный — прежний монорепо (613 уникальных коммитов, пакет 740 МБ). На VPS добавлены локальные ветки `laptop-rescue-20260923` (= main ноутбука bc88d1d) и `laptop-preserve-rescue-20260923` (снимок 13.09) и remote `laptop-rescue`. |
| Claude-Code-Game-Master / dnd-game-master (PUBLIC fork) | worktree vanilla-frontend: 5 файлов → WIP 8700b55 | 3 ветки | не требуется: у ноутбука на main нет своих коммитов, VPS main == origin/main | — |
| University (PRIVATE) | — | 2 ветки (task-6/nir-writer — 30 коммитов), 2 стэша, laptop-preserve-rescue | не требуется: main ноутбука — предок origin/main и VPS main | — |

### Только на ноутбуке, remote был

| Проект | Закоммичено | Запушено |
|---|---|---|
| DefaultProjectUnity (PRIVATE) | 1 коммит: сцена, MainMenuController, слайды, AutoBuilder/SliderSetup, пакеты, McpUnitySettings; удалены логи StreamingAssets; старая сборка `Build_SimplePresenter` убрана из индекса, `/Build_*/` в .gitignore (новая `Build_Antiterror` не коммитилась) | ветка `dev19-05-26-antiterror` (12 коммитов, раньше отслеживала dev12-2-12-25), стэш |
| polus (PRIVATE) | нули не коммитились | main ff (+10), 4 ветки, laptop-preserve-rescue |
| TradingCryptoBot (PRIVATE) | нули не коммитились | main ff (+6), 1 ветка, laptop-preserve-rescue |
| Parsing / parsing-infra (PRIVATE) | указатель сабмодуля family-tree → eecfe3f | main ff (+4), 3 ветки, стэши 0/1 без CREDENTIALS.md и YOUGILE_ARCHIVE.md, laptop-preserve-rescue |
| Parsing/ai-assistants, family-tree, parsing-hub, seo-platform (PRIVATE) | — | 4+3+4+2 ветки, 3 стэша ai-assistants |
| Sensar (PRIVATE) | — | master ff (+3), 1 ветка |
| Aperant (**PUBLIC** fork) | — | develop ff (+2: auto-save .serena/.codex, миграция .orchestra) → **origin/develop == develop**; stash → laptop-stash/0. upstream AndyMik90/develop впереди на 2 — не вливал (задача — синк с origin) |
| ai-proxy-manager (PRIVATE) | — | main ff (+1) |
| inscryption-ai (PRIVATE) | — | 9 веток (task-14/feat-mccfr-scale — 68 коммитов) |
| claude-server (**PUBLIC**) | 4 файла (CLAUDE.md, README, index.html, server.py) | master |
| CursorUsageAnalyzer (**PUBLIC**) | 5 файлов (uv-проект) | main |
| claude-plugins-official (**PUBLIC** fork) | server.ts (debounce 10 мин) | main → df2232b |
| AIMedical (PRIVATE) | manifest.json | main |
| AISwapFace (PRIVATE) | 5 файлов + `mono_crash.*` в .gitignore | dev21-11-25 |

### Без remote → новые ПРИВАТНЫЕ репо DrSeedon

| Проект | Закоммичено | Репо |
|---|---|---|
| WebView | архив `Kiosk-PDF.z01` (51 МБ, уже в первом коммите — историю не переписывал, запушен как есть, лимит GitHub 100 МБ) убран из индекса, `*.z0N` в .gitignore | DrSeedon/WebView: main + 1 ветка + laptop-preserve-rescue |
| games (перевод модов Starsector) | CLAUDE.md | DrSeedon/games: main + 13 веток |
| stargate-tactics | — | DrSeedon/stargate-tactics: main + 6 стэшей + laptop-preserve-rescue |
| media | CLAUDE.md | DrSeedon/media: master |
| test-project | — | DrSeedon/test-project: master + 16 веток |
| DnD-Music-MCP | main.py, generate_presets.py, test_gen.py, engine/presets, samples (12 wav, 15 МБ); `ACE-Step-1.5/` (19 ГБ, сторонний клон) в .gitignore, его локальные скрипты скопированы в `ace-step-local/` | DrSeedon/DnD-Music-MCP |
| spacewar-tactics (~/) | optics_lab, project.godot | DrSeedon/spacewar-tactics: main + 2 ветки |
| voidworks (~/) | project.godot | DrSeedon/voidworks: main + 2 ветки |
| clawd (~/) | 25 файлов рабочего пространства; `memory/moltbook-credentials.json` **не коммитился** (в .gitignore) | DrSeedon/clawd |
| E-CommerceBench (клон QwenLM, чужой remote) | ветка `laptop-rescue`: run30.sh, models_config.local.json, log/run30_* (9 МБ); `__pycache__` — в .git/info/exclude; клон был shallow → `fetch --unshallow` | DrSeedon/E-CommerceBench-laptop (в QwenLM ничего не пушилось) |
| zahoron-laravel / zahoron-mobile / zahoron-phone | — | DrSeedon/zahoron-archive: `laravel/*` 40 refs, `mobile/*` 25, `phone/*` 4 (вкл. стэши). **Клиентский remote kislinsky/zahoron и DrSeedon/zahoron-mobile не тронуты.** |

## Секреты

Скан по форме (приватные ключи, gh*_/sk-/AKIA/AIza/xox/TG-бот, JWT, `password|secret|api_key|token = <длинное>`, URL с кредами)
перед каждым коммитом и по каждому пушу: неопубликованные коммиты всех веток, каждый стэш, каждый снимок.

- Не ушло на GitHub, сохранено git bundle на VPS `/home/kesha/laptop-rescue-20260923/` (каталог 700, файлы 600):
  `seedon-secrets.bundle` (снимок с .env), `seedon-infra-secrets.bundle` (стэш с .env.local),
  `parsing-secrets.bundle` (стэши и снимок с CREDENTIALS.md — TG-бот, gho_, AIza — и YOUGILE_ARCHIVE.md с ghp_).
- **Мой инцидент:** первым проходом очищенный стэш Parsing (`laptop-stash/0`) ушёл в ПРИВАТНЫЙ parsing-infra вместе
  с `YOUGILE_ARCHIVE.md`, где лежит `ghp_99Ted…` — скрипт тогда не блокировал пуш по находке. Ветка удалена через ~1 минуту
  и перезалита без файла; скрипт исправлен (пуш только при HITS=0). Объект мог остаться на GitHub до их GC — **токен стоит отозвать**.
- Запушено осознанно в приватные репо (историю не переписываем, файлы — собственные данные владельца):
  COG — старые VK access_token/client_secret в `04-projects/tg-archive/saved-messages/2023-11.md` (авто-синк 15.09);
  VPN-Service — MTProto-ссылка и тестовый hysteria2-пароль в доках; media — ключ локального Jackett (127.0.0.1:9117) в CLAUDE.md;
  zahoron-archive — ключ карт в `lib/main.dart` клиентского приложения.
- Публичные репо (kesha-tg-bot, Aperant, CCGM, claude-server, CursorUsageAnalyzer, claude-plugins-official): находок 0.
  В kesha-tg-bot в новых доках — IP серверов (уже есть на origin/main) и email владельца.

## Не сделано и почему

- Зонтичный репо `/mnt/data/Рабочий стол/Cursor` (DrSeedon/Cursor, PRIVATE): 2 незапушенных коммита «upd» содержат
  `Build_GPTAvatar0.36.zip` 687 МБ — GitHub такое не примет, а переписывать историю нельзя; 17 372 изменения в дереве —
  в основном удаления каталогов, переехавших в отдельные проекты. Не трогал, решать владельцу.
- `.serena/project.yml` в ~15 worktree/репо — автоперегенерация Serena, не работа; `.orchestra/.layout-migration.json`
  (Parsing, stargate, University) — служебный файл ноутбучной Orchestra. Не коммитились.
- Не трогал: временные прогоны `/mnt/data/luna-autonomy-*`, `/mnt/data/task346-serena.*`, `/mnt/data/tmp/*`, моды RimWorld,
  репозитории orchestra*.
- VPS-репозитории не пушились: мерж/ветки сделаны локально в их checkout.
