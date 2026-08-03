# migrate-vps — личная память

## Проверки на VPS 158.220.127.161 (read-only)
- `sqlite3` бинаря на VPS НЕТ. Читать БД так:
  `sudo -u kesha /home/kesha/.local/bin/uv run python -c "import sqlite3; ..."`,
  открывать через `file:...?mode=ro&uri=True` — не трогает боевой файл.
- Orchestra там под юзером `kesha`, `/home/kesha/orchestra`, systemd `orchestra.service`.
  На том же хосте живут `kesha-bot-vps`, `dnd-game-master`, `nginx`, `telegram-bot-api`,
  `mtg`, `hysteria-server`, `tinyproxy`. **Хост не пустой — любая нагрузка соседствует
  с боевым ботом и с прокси `:12343`, через который ноут ходит к API.**

## Проверять размер репозитория, а не каталога
`du -sh` по проекту врёт о стоимости переноса. Parsing = 91 ГБ каталог, но `.git` = 7.5 МБ
и 50 tracked-файлов; 82 ГБ — это untracked `_research/`. Всегда мерить тройкой:
`du -sh .git` + `git ls-files | wc -l` + `git remote -v`.
Вывод переворачивается: «не влезет на диск» → «влезает легко, но переносить нечего».
Заодно `git remote -v` ловит репозитории **без remote** (stargate-tactics) — их клонировать
неоткуда, это отдельный блокер.

## OOM/systemd: `systemctl show` врёт, ground truth — `/proc`
`systemctl show <unit> -p OOMScoreAdjust` печатает **`infinity` у всех юнитов независимо от
настройки**. По нему нельзя отличить «настроено» от «не настроено» — то есть нельзя проверить
собственную работу. Реальное значение только тут:
`cat /sys/fs/cgroup/system.slice/<unit>.service/cgroup.procs` → по каждому pid
`cat /proc/<pid>/oom_score_adj`.

Наследование потомками — **проверено, работает**: у `kesha-bot-vps` дочерние `claude` и
`workspace-mcp` несут `adj` юнита. Значит `OOMScoreAdjust=` в юните защищает и CLI-агентов,
а `MemoryMax`/`MemoryHigh` считают весь cgroup (оркестратор + воркеры) разом.

## Перед защитой от OOM — померить, КТО реально жирный
Интуиция «убьют самый жирный процесс, то есть наш» может быть перевёрнута. На VPS:
бот Кеши 1446 МБ (пик 2297), Orchestra 142 МБ (пик 158) — в 10 раз меньше. Дефолт работал бы
против требования, а не случайно за него. Мерить так:
`systemctl show <unit> -p MemoryCurrent --value` и `memory.peak` в cgroup; заодно
`journalctl -k | grep -c oom-kill` — были ли срабатывания вообще (было 0).

## Миграцию БД доказывать прогоном, а не чтением diff
`app/db.py:370 _migrate()` аддитивен (CREATE TABLE IF NOT EXISTS + ALTER ADD COLUMN под
`PRAGMA table_info`), но читать это недостаточно. Быстрый способ доказать:
scp боевой копии в /tmp → `db.DB_PATH = Path(work)` → `db.init_db()` → сверить счётчики строк
до/после. **`DB_PATH` — это `Path`, не `str`**, иначе падает
`AttributeError: 'str' object has no attribute 'parent'` в `_conn()`.
