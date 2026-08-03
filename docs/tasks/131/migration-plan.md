# #131 — План миграции на VPS

Основан на `research.md` (все факты измерены 2026-08-03). Стратегия — **H2: два контура**,
а не разовый полный переезд.

**Все шаги на VPS выполняет ЮЗЕР вручную.** По правилу проекта агенты на VPS не деплоят.
Ниже — порядок, команды и критерии проверки.

## Целевое состояние

- **VPS `orchestra.seedon.ru`** — основной контур: разработка самой Orchestra + группа A
  (`orchestra`, `seedon`, `VPN-Service`, `COG-second-brain`). Прямой API без прокси.
- **Ноут** — группа B (`Parsing`, `Sensar`, `University`, `stargate-tactics`): проекты,
  чей предмет работы — локальные данные (82 ГБ `_research/`, 15 ГБ `backup/`) или репозиторий
  без remote.
- Синхронизация между контурами — только через `origin` на GitHub. Один проект ведётся
  ровно в одном контуре.

## Точка отката (сделать ДО всего)

Полный откат = вернуть VPS к текущему состоянию: код `41c7dc4`, БД с 3 idle-сессиями.

```bash
# на VPS, под kesha
cd /home/kesha/orchestra
sudo systemctl stop orchestra                    # без остановки WAL снимется неконсистентно
cp data/orchestra.db  ~/backup-131-orchestra.db
cp data/orchestra.db-wal ~/backup-131-orchestra.db-wal 2>/dev/null
cp .env ~/backup-131.env
git rev-parse HEAD > ~/backup-131-commit.txt     # ожидается 41c7dc4
```

Откат: `sudo systemctl stop orchestra` → `git checkout 41c7dc4` → вернуть оба файла БД и
`.env` → `sudo systemctl start orchestra`.

**Проверка отката обязательна ДО деплоя** (грабли из CLAUDE.md: SHA в инструкции отката
надо прогонять, а не верить `--is-ancestor`). Поскольку откат здесь — `git checkout` на
конкретный коммит плюс восстановление файлов, а не `revert`, риск конфликта отсутствует;
но убедиться, что `41c7dc4` реально в истории после `git fetch`.

## Шаги

### Шаг 1 — swap на VPS (блокирующий, делать первым)
Измерено: 7.8 ГБ RAM, **swap = 0**, на хосте живут бот Кеши, DnD, nginx, tinyproxy.
Без swap несколько воркеров Opus → OOM-killer уронит соседние сервисы, включая прокси
`:12343`, через который ноут ходит к API. То есть авария на VPS отрежет и запасной путь.

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h    # ожидается Swap: 4.0Gi
```

### Шаг 2 — бэкап и остановка
См. «Точка отката». Останавливать сервис обязательно: иначе `-wal` снимется на лету и
копия будет неконсистентной.

### Шаг 3 — обновление кода до main
```bash
cd /home/kesha/orchestra
git stash                       # на VPS грязный uv.lock + untracked docs/team-structure.html
git fetch origin && git pull origin main
uv sync
```
Ожидается +256 коммитов. `git stash pop` НЕ делать — локальный `uv.lock` VPS не нужен.

### Шаг 4 — миграция БД (автоматическая, проверена)
Отдельных действий не требует: `init_db()` при старте сам добавит `turn_usage`,
`tool_errors`, `merge_operations`, `improvement_rules`, `voice_costs`.

**Уже проверено экспериментально** на копии боевой БД VPS: `init_db: OK`, `rows lost: NONE`,
`sessions before/after: 4 4`. Механизм в `app/db.py:370` строго аддитивен.

### Шаг 5 — «обновить старые опусы» (при ОСТАНОВЛЕННОМ сервисе)
Три сессии на VPS сидят на Opus 4.6/4.8. Правим до старта, иначе живой сервер перезапишет
`sessions.model` из памяти при auto_resume (известные грабли проекта).

```bash
cd /home/kesha/orchestra
uv run python - <<'EOF'
import sqlite3
c = sqlite3.connect("data/orchestra.db")
c.execute("UPDATE sessions SET model='claude-opus-5[1m]' WHERE model LIKE 'claude-opus-4%'")
c.commit()
print(list(c.execute("SELECT name, model FROM sessions WHERE status!='archived'")))
EOF
```
Пинить именно `[1m]`: голый алиас даёт контекст 200K вместо 1M.
**После старта перепроверить тем же SELECT** — если модель откатилась, значит сервис не
был остановлен.

### Шаг 6 — старт и проверка
```bash
sudo systemctl start orchestra
systemctl is-active orchestra
journalctl -u orchestra -n 50 --no-pager
curl -s -o /dev/null -w "%{http_code}\n" https://orchestra.seedon.ru/     # ожидается 302
```
Критерий успеха: сервис active, в журнале нет трейсбеков, дашборд отдаёт 302, три сессии
на месте и показывают `claude-opus-5[1m]`.

**Локальную БД (253 МБ) НЕ переносить.** Она содержит 85 сессий со скоупами
`/mnt/data/Projects/…` и `/home/maxim/Рабочий стол/…`, которых на VPS нет: спавн упадёт
`repo_path does not exist` (`app/workspace.py:239`). Плюс её вес — это 90 473 строки логов,
а не полезное состояние. Сессии группы A дешевле создать на VPS заново.

### Шаг 7 — репозитории группы A на VPS
```bash
mkdir -p /home/kesha/projects && cd /home/kesha/projects
git clone git@github.com:DrSeedon/seedon.git
git clone git@github.com:DrSeedon/VPN-Service.git
git clone git@github.com:DrSeedon/COG-second-brain.git
```
Суммарно ≈ 0.5 ГБ при 133 ГБ свободных. Сама Orchestra уже лежит в `/home/kesha/orchestra`.
Требуется рабочий SSH-ключ к GitHub под `kesha` (`git@` remotes) — проверить `ssh -T git@github.com`.

### Шаг 8 — `.env` на VPS
Прокси не трогать: строки `HTTPS_PROXY`/`HTTP_PROXY` остаются закомментированными —
измерено, что API отвечает напрямую за 0.3 s.

- `GITHUB_REPO_SCOPE_MAP` — переписать под `/home/kesha/projects/…`; локальные значения на
  `/mnt/data/…` на VPS бессмысленны.
- `SSH_TUNNELS` — на VPS не нужны, он сам конечная точка туннелей.
- Перенести с ноута выборочно: `DEEPGRAM_API_KEY`, `YOUGILE_SEEDON_TOKEN` (если нужен
  YouGile-синк). `TG_BRIDGE_*` на VPS уже свои — **не перетирать**, там живёт бот Кеши.
- `DASHBOARD_PASSWORD` — сменить: дашборд открыт в интернет.

### Шаг 9 — сессии группы A
Создать оркестратора/воркеров на VPS через дашборд под новые скоупы
`/home/kesha/projects/…`. Модель — `claude-opus-5[1m]`.

## Что НЕ делать

- Не переносить локальную `orchestra.db` целиком (шаг 6).
- Не клонировать Parsing/Sensar/University на VPS: без `_research/` (82 ГБ) и `backup/`
  (15 ГБ) они бесполезны, а копировать это по мобильному каналу нереально.
- Не трогать `stargate-tactics` — у него **нет remote**, история в одном экземпляре.
  Если он нужен на VPS — сначала завести remote на GitHub, отдельной задачей.
- Не перетирать `TG_BRIDGE_*` на VPS и не трогать чужие сервисы (`kesha-bot-vps`,
  `dnd-game-master`, `mtg`, `hysteria-server`, `tinyproxy`).
- Не пушить в remotes `enterprise` и `vadim` (правило проекта).

## Открытые вопросы к юзеру

1. **Бот Кеши и Orchestra на одном хосте.** Готов ли юзер к тому, что тяжёлая нагрузка
   воркеров делит 7.8 ГБ с ботом и с tinyproxy, который раздаёт прокси ноутбуку? Swap
   (шаг 1) снижает риск, но не устраняет соседство.
2. **Группа B при мёртвом проводном интернете.** Parsing/Sensar/University/stargate остаются
   на ноуте — то есть при плохой связи они работают через мобильный + прокси, как сейчас.
   Приемлемо или нужен отдельный план для них?
3. **Судьба локальных 85 сессий.** Предлагается оставить их на ноуте как есть (не
   переносить). Подтвердить.
