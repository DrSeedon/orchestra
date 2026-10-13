# V-825 — что на диске VPS лишнее (исследование, ничего не удалялось)

Замер 13.10.2026 ~14:00 CEST: `/` 290 ГБ, занято ~273 ГБ (88–89%), свободно ~37 ГБ (диск колеблется: 91% при постановке задачи → 88% сейчас). Источники: `evidence/` (top-level.txt, drill1–3.txt, meta.txt + meta.py, worktree-status.txt, gitgc-and-misc.txt). Все размеры — `du -xsB1` (реально занятые блоки); sudo использовался только на чтение.

## Итог

- **Без риска, ≈11–12 ГБ** (пересоздаётся само или уже лежит в корзине): корзина root (4.4), кеши npm/uv/playwright/pip у root и kesha (≈5.3), журнал journald после vacuum (≈1.2), эксклюзивная часть кеша uv (0.85).
- **С решением владельца / оркестратора проекта, ≈70 ГБ верхняя граница** (каждая строка — отдельное решение): простаивающие воркеры с worktree (≈11–14), результаты исследований и стенды в ~ (≈25), старые транскрипты Claude/Codex (≈5), build-хлам киоска (≈5–6), `knowledge-v1/current.db` (3.3), `comfy-monorepo.git` (5.6), `.orchestra/tasks/*/raw` чужих проектов (≈3.7), ассеты видео-навыков (≈5), дубликат venv mirofish (≈2.8), `.rembg` (2.1) и мелочь.
- **Не трогать / только перечислено:** katya-work (репо 13.5 + 13 worktree ≈58.8 + её `.claude/projects` и drive ≈3.4 = ≈75 ГБ — это 27% диска), кеш `~/.cache/uv` (14.4 ГБ по `du`, но почти всё — жёсткие ссылки venv: эксклюзивно 0.85 ГБ), живые данные Orchestra (`data/orchestra.db`, `data/backups` 3.0, `data/storage-*`, `ORCHESTRA_TASK_REPOSITORY=…/data/storage-preflight-final-20260908/tasks`), `data/models` (используются из `.env`).
- Главный вывод: крупно освободить место без чужих решений нельзя — «настоящий мусор» занимает ≈12 ГБ, остальное это либо данные katya-work, либо исследовательские артефакты, у каждого из которых есть автор. Единственный быстрый крупный рычаг: **убрать простаивающих воркеров с worktree** (оркестратор, правило worker-lifecycle) и **решить судьбу `~/festival-*`, `research-archive`, `komandor-data`, `enisei-kiosk-build`** (владелец).
- Не нашёл: docker (`/var/lib/docker` нет), snap-кеши (`/var/lib/snapd` ничтожен), apt-кеш 0.12 ГБ, `/var/crash` 0.11 ГБ. Раздутых `.git`: `git gc` почти ничего не даст (см. ниже).

Оговорка про atime: `atime` каталогов за 10.10 и 13.10 в большинстве строк — следы аудитов (V-764/V-789/мои сканы), а не использование; надёжен только mtime и список открытых файлов/cmdline процессов (сняты `lsof` и `/proc` на момент замера).

## Таблица (> 300 МБ, по убыванию)

Колонки: путь | размер | что и чьё | последнее использование | восстановимость | риск | кто решает.

| Путь | ГБ | Что это / чьё | Последнее использование (mtime; открыт; ссылки) | Восстановить | Риск | Решает |
|---|---:|---|---|---|---|---|
| `worktrees/home-kesha-katya-work/*` (13 шт., largest google-slaydy 10.3) | 58.8 | worktree проекта katya-work, сессии idle/waiting | живые сессии, mtime до 13.10 | в git-ветках | — | **ТРОГАТЬ НЕЛЬЗЯ** (только перечислено) |
| `~/.cache/uv` | 14.4 | кеш uv; **жёсткие ссылки venv** (107 тыс. файлов с nlink>1; эксклюзивно 0.85) | 11 открытых файлов, 6 cmdline | пересоздаётся | высокий: prune не вернёт места, а `--force` ломает venv | не трогать |
| `~/katya-work` (.git 7.0 + artifacts 5.65) | 13.5 | основной репо katya | cwd процесса, mtime 13.10 | git | — | **ТРОГАТЬ НЕЛЬЗЯ**. Заметка владельцу её оркестратора: в `.git/objects/pack` лежат 2 хвоста `tmp_pack_*` на 1.63 ГБ (прерванная упаковка) |
| `worktrees` непроектные idle-воркеры (orchestra 7, seedon 8, прочие) | ≈13.8 | worktree сессий (venv .52 + `.orchestra`/resources .3–.7 каждый) | idle: fix-* с 05.10; prompt-engineer с 12.09; seedon/sales с 03.08; b2b-tenders с 30.09; course-video 06.10, tender-scout 07.10; ai-table-worker с 18.08 | да: ветки в git, venv пересоздаётся `uv` | средний: нужен `worker_wip` на незакоммиченное | оркестратор (правило 72 ч) |
| `~/apps/mirofish/backend/.venv` + `.venv312` | 7.7 + 2.9 (общих жёстких ссылок 4.85; дубликат даёт 2.8 ГБ) | два venv mirofish (py3.11 uv и py3.12); `.venv312` обслуживает работающий redislite, mirofish живёт (процесс mirofish-usage-proxy у seedon-воркера) | mtime 05.10; 8 открытых файлов | да (pip/uv) | средний: надо выяснить, какой venv нужен | оркестратор seedon/mirofish |
| `~/orchestra/data/uploads` | 6.7 | вложения чатов Orchestra, ссылки в БД | свежие: 4.8 ГБ моложе 30 дн., 1.5 ГБ старше 30 дн. | **нет** (нет копии) | высокий: ссылки в БД | владелец |
| `~/work/enisei-kiosk-build` | 6.2 | сборки киоска Енисей: ≈18 каталогов `stage-*` по 0.39 ГБ + `linux-*`, `node_modules` | mtime 07.10, не открыт, cfg-ссылок нет | да (пересборка) | низкий для `stage-*`; `linux-final` — результат | владелец/оркестратор киоска |
| `~/.claude/projects` | 5.6 | транскрипты Claude-сессий, нужны для resume (`app/backend_claude.py::_resume_transcript_exists`) | 2.1 ГБ старше 14 дн.; в БД сопоставить не удалось (имена файлов = id CLI, не id Orchestra) | **нет** | высокий: потеря resume и истории | владелец |
| `projects/seedon/.orchestra/tasks` | 5.6 | доказательства задач seedon (V-131/raw 2.4, V-65/raw 1.3) | mtime 13.10 | **нет**, если не в git | средний | оркестратор seedon |
| `~/archive/comfy-monorepo.git` | 5.6 | bare-репо «архив монорепо comfy» (одна pack 5.19 ГБ, ветки adhoc-* воркеров), последний коммит 19.09 | atime 10.10 | **нет** (возможно единственная копия) | высокий | владелец (comfy) |
| `~/.orchestra/codex-home` | 5.0 | CODEX_HOME на сессию (43 открытых файла): idle 2.8, waiting 1.6, running 0.6 | живые сессии | нет (история сессий) | высокий | не удалять без архивации сессий |
| `~/festival-assets` | 4.7 | ассеты фестиваля (video2 3.5) | mtime 08.09 | да? (сорсы вне) | неизвестен | владелец |
| `/root/.local/share/Trash` | 4.4 | **уже в корзине root**: 5× `orch-offline-verify-*` (0.87 каждый, 25.09) + 6 `rehearsal-V19…V30` (aitable, 07–09.10) | не открыт | уже удалено | низкий | я/оркестратор; рехерсали свежие — пропустить |
| `~/.local/state/orchestra/knowledge-v1` | 4.1 | `current.db` 3.3 ГБ (03.09) + canonical/evidence 0.6 + .git; **в коде `app/` нет ссылки**, не открыт | mtime 08.09 | нет (данные) | средний: возможный источник отката миграции знаний | владелец |
| `projects/comfy-image-pipeline/.orchestra/tasks` | 3.9 | доказательства задач comfy (55, 57…) | mtime 15.09 | нет, если не в git | средний | оркестратор comfy |
| `~/.codex/sessions` | 3.45 | rollout-журналы Codex; 3.14 ГБ старше 30 дн. | mtime 13.10 | нет | высокий (история) | владелец |
| `~/komandor-data/raw` + `duckdb_tmp` | 3.3 + 1.3 | исходники (2023) и временные DuckDB-файлы проекта Командор (University); на 8899 всё ещё работает jupyter | raw mtime 2023, duckdb_tmp 19.09 | raw — повторная выгрузка из Google Drive (fetch.sh), tmp — пересчёт | низкий для tmp, средний для raw | University-orchestrator/владелец |
| `~/orchestra/data/backups` | 3.0 | ежедневные бэкапы БД (2 × 1.5 ГБ zst) | 13.10, ротация | — | это единственные бэкапы БД | не трогать |
| `~/.cache/ms-playwright` | 2.7 | 10 каталогов версий; в работе `headless_shell-1223` и `-1228`; `headless_shell-1194` (0.34) никто не использует | mtime 08–11.10, 18 открытых файлов | `playwright install` | низкий для 1194; остальные — ломают тесты | я (только 1194, 0.34) |
| `~/research-archive/golos-v2-analysis` | 2.7 | анализ голоса v2 | mtime 11.09 | нет | неизвестен | владелец |
| `~/.local/share/orchestra-tts` / `orchestra-manim` / `orchestra-pw-browsers` | 2.3 / 1.95 / 0.68 | ассеты навыков видео (Vosk/Kokoro, Manim, Playwright) | mtime 04–05.10 | да (скачивание/установка) | низкий, но ломает video-artifact до переустановки | владелец |
| `~/.rembg/models` | 2.1 | модели rembg (в `app/` не упоминаются; использует comfy/painter) | mtime 27.09 | да (скачиваются) | низкий | владелец comfy |
| `~/katya-drive` (+`.claude/projects` katya 1.1) | 2.0 | диск Кати | открыт процессом, mtime 13.10 | — | — | **ТРОГАТЬ НЕЛЬЗЯ** |
| `~/festival-2026-results` | 2.0 | результаты фестиваля, painter-guest-works 1.9 | mtime 19.09 | нет | неизвестен | владелец |
| `~/.cache/huggingface` | 1.8 | модели, использует kesha-bot (открыт) | 08.10 | да | высокий для бота | не трогать |
| `/root/.npm/_cacache` | 1.8 | кеш npm root | mtime 08.10, не открыт | да | нет | я |
| `/var/log/journal` | 1.7 | systemd-журнал (1.5 ГБ в учёте journald) | живой, 45 открытых | не нужно | низкий: `journalctl --vacuum-size=500M` даёт ≈1.2 ГБ | я/оркестратор |
| `~/.npm` | 1.5 | кеш npm kesha | не открыт (V-806 видел занятым) | да | нет | я |
| `~/readme-stand-V690` / `V686` | 1.4 / 0.9 | стенды README (captures, orchestra-копия) | mtime 04.10 | пересборка | возможно «стенд» из ограничений задачи — **сначала уточнить** | оркестратор README |
| `projects/comfy-image-pipeline/projects` | 1.4 | рабочие данные comfy | mtime 07.10 | нет | неизвестен | оркестратор comfy |
| `~/split` | 1.4 | выделенные из монорепо mfm-2026-photobooth/voice | mtime 19.09 | возможно в git | неизвестен | владелец |
| `opt/kesha-bot/storage` | 1.3 | живые данные бота | открыт | нет | **высокий** | не трогать |
| `projects/comfy-image-pipeline/.git` | 1.3 | pack 1.13 ГБ + loose 84 МБ; `git gc` ≈ −0.05 | — | — | — | не нужно |
| `~/handoff-2026-09-21` | 1.2 | хэнд-офф 21.09 (stage/stage2) | mtime 21.09 | неизвестно | неизвестен | владелец |
| `~/maxim-drive/backup-2026-09-24` | 1.2 | бэкап drive | mtime 21.09 | это и есть копия | неизвестен | владелец |
| `/opt/orchestra/runtimes` | 1.2 | 3 runtime-каталога, живой `…-rag-v2` (0.66) используется юнитом; `…py312` 0.52 | 41 открытый файл, ссылка в drop-in | да | высокий для rag-v2 | не трогать |
| `projects/dnd-game-master.rsync-old` | 1.2 | старая rsync-копия dnd (внутри `.venv` 0.59 + `.uv-cache` 0.55) | mtime 23.09, не открыт, ссылок нет | venv/кеш пересоздаются; остальное есть в проекте | низкий | оркестратор dnd (≈1.1 ГБ) |
| `projects/seedon/.git` | 1.2 | pack 0.97 + loose 0.12; `git gc` ≈ −0.1 | — | — | — | не нужно |
| `~/deliverables` | 1.1 | выгрузки задач V-82/V-115/V-116 | mtime 07.10 | неизвестно | неизвестен | владелец |
| `~/.local/share/seedon/v111` | 1.0 | данные V-111 (внутри живого `~/.local/share/seedon`, где тендерная БД) | mtime 30.09 | нет | средний | оркестратор seedon |
| `~/venvs/sentiment` | 0.9 | venv проекта University | mtime 13.10 | да | низкий | оркестратор University |
| `var/lib/photoserver/photos` | 0.9 | фото photobooth (живой сервис) | mtime 16.09 | нет | высокий | не трогать |
| `~/bench219`, `~/bench-v637`, `data/bench134` | 0.8, 0.6, 0.5 | артефакты старых бенчмарков | mtime 12.08 / 25.09 / 04.08 | воспроизводимы дорого | низкий | владелец |
| `~/.local/share/Trash` (kesha) | 1.8 | корзина kesha — **моложе 3 дней** | 13.10 | уже удалено | — | **владелец, по условию задачи не трогать** |
| `/root/sensar-build-env-backup`, `/root/.cache/uv`, `/root/.cache/ms-playwright` | 0.76, 0.72, 0.67 | бэкап окружения sensar (01.09), кеши root (08.10 и 03.07) | не открыты | кеши да; backup — единственный? | низкий (кеши) | кеши — я, backup — владелец |
| `/var/www/cog-balatro`, `wall`, `dl` | 0.66 / 0.38 / 0.2 | статика под nginx (balatro, wall, dl) | mtime 20.09 / 08.09 / 08.10 | пересборка проектов | средний | оркестратор проекта |
| `/var/cache/orchestra-uv` | 0.65 | кеш uv сервиса | atime 08.10 | да | низкий | я |
| `projects/seedon/site`, `~/orchestra-scratch`, `~/salvage-tmp-20260906`, `~/design-refs`, `~/avito-research-data` | 0.58, 0.46, 0.46, 0.38, 0.37 | рабочие/исследовательские остатки | mtime 08.2026–10.09 | неизвестно | неизвестен | владелец |
| `worktrees/bash-latency-20260905` | 0.71 | worktree-ветка `experiment/bash-latency-20260905`, **без сессии в БД**, есть незакоммиченные правки | mtime 05.09 | `.venv` да, правки нет | средний | оркестратор |
| `/opt/ai-table-staging`, `ai-table-i1` | 0.35, 0.84 | живые сервисы (cfg-ссылка `ai-table-staging.service`) | 13.10 | — | высокий | не трогать |
| `~/orchestra/.git`, `opt/kesha-bot/.git`, `opt/cog-second-brain/.git` | 0.81, 0.30, 0.36 | `git gc` у kesha-bot: loose 282 МБ, в pack 2.5 МБ — выигрыш не оценён | — | — | — | не нужно |

## Рекомендации

1. Сразу (мои 11–12 ГБ, нужна лишь команда оркестратора): `trash-empty` для старых `orch-offline-verify-*` в корзине root (4.3), `npm`/`uv`/`playwright`-кеши root и kesha (≈5.3), `journalctl --vacuum-size=500M` (≈1.2), `headless_shell-1194` (0.34), uv-prune только неиспользуемых архивов (0.85, без `--force`).
2. Оркестратор: пройти по списку простаивающих воркеров (>72 ч) и закрыть по правилу worker-lifecycle — это ≈11 ГБ worktree-кода и venv, не трогая ветки.
3. Владельцу: одним сообщением решить судьбу блоков «исследования в ~» (≈25 ГБ), `knowledge-v1/current.db` (3.3), `comfy-monorepo.git` (5.6), `enisei-kiosk-build/stage-*`, дубликата venv mirofish.
4. Хозяину katya-work (через её оркестратор): `tmp_pack_*` 1.63 ГБ в `.git`, 13 worktree по 3–10 ГБ.

## Ограничения

`du` пересекает hardlink-и: суммы по dirs (особенно mirofish, uv) нельзя складывать; `~/.claude/projects` не сопоставлен с сессиями БД (имена файлов — id CLI); «стенд реестра» из ограничений задачи точно не опознан — на всякий случай в таблице отмечены `readme-stand-*` и `/var/www`; atime не используется как свидетельство; `ORCHESTRA_TASK_REPOSITORY` прочитан из `/proc/<MainPID>/environ` (значение `…/data/storage-preflight-final-20260908/tasks`), остальные переменные не выводились.
