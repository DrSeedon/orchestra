# V-786 — инвентаризация VPS (vmi3407579): сервисы, ресурсы, лишнее, cgroup-гарантии, сироты

Только чтение: ни один процесс/юнит/лимит не менялся. Сырьё — `evidence/` (10s-sample.json, service-inventory.json, orchestra-cgroup-processes.json, orphan-log-details.json, cmdlines.txt, listen.txt, sar-*.csv, systemd-and-cgroups.txt). Замеры 08.10.2026 ~11:30–11:57 UTC. Окно sysstat: 07.10 11:30 → 08.10 11:30, 144 точки по 10 минут.

## 1. Машина и нагрузка

8 vCPU, 25 GiB RAM (доступно ~19 GiB), swap 16 GiB (занято 1.5 GiB), диск `/` 290 GiB, занято 243 GiB (84%), свободно 47 GiB. Крупнейшие каталоги: worktrees Orchestra 50 GiB, data Orchestra 16 GiB, `~kesha/.cache` 16 GiB, `~kesha/projects` 18 GiB; journald всего 308 MiB (не проблема).

Сутки (sar): idle в среднем 55%, p95 нагрузки CPU: user 38% + nice 69% (nice — агентские задачи), iowait max 20%. loadavg-1 средний 11, максимум 108 в 09:30 UTC (blocked=90 — пик блокированных на IO). Своп: pswpout p95 305 стр/с, максимум 1049 стр/с; majflt p95 72/с. Память занята 14–51%, максимум 12.5 GiB. Steal 0. PSI на корне: cpu some avg300 2.4%, memory some ≈0. `memory.events` юнита Orchestra: `high 2 618 464`, `max 0`, `oom_kill 0` — упор в MemoryHigh был регулярным (реклейм/троттлинг), до OOM не доходило.

Топ потребителей (RSS, 10-секундный замер): orchestra.service 3.0 GiB (47 процессов, 5.4% ядра), kesha-bot-vps 1.47 GiB (пик cgroup 3.85 GiB, лимитов нет), cron.service-cgroup 1.3 GiB (20 процессов, 11% ядра — что именно запущено из cron, не установлено), ai-table-i1 243 MiB, nginx 116 MiB. Транзиентный `session-166929.scope` грёб 100% ядра в замере, к моменту проверки сессия уже закрылась — природа не установлена.

## 2. Сервисы (195 загруженных юнитов, 72 active)

Рабочие пользовательские/проектные: orchestra, telegram-bot-api, orchestra-proxy (root), kesha-bot-vps, dnd-game-master, ai-table-i1 (изолированный user aitable), photoserver, photobooth-enroll-web, photobooth-mirror-sync (oneshot), kiosk-heartbeat. Сеть/прокси: nginx, xray.service (nobody), hysteria-server, mtg, tinyproxy, tailscaled, fail2ban, ssh. Остальное — системная база (journald, logind, resolved, networkd, cron, rsyslog, dbus, polkit, udisks2, fwupd, ModemManager, multipathd, unattended-upgrades, getty@tty1, serial-getty@ttyS0).

Лимиты на уровне юнитов: только у orchestra.service (MemoryHigh=14 GiB, MemoryMax=16 GiB, OOMScoreAdjust=800, Delegate). У kesha-bot-vps (OOM −500), ai-table-i1, nginx, остальных MemoryHigh/Max=infinity, `MemoryLow/Min=0` нигде, `CPUWeight` не задан нигде (кроме `agents`=50).

## 3. Лишнее (кандидаты, решение владельца)

Малая выгода каждого; ничего не трогал.
- ModemManager (3 МБ, VPS без модема), multipathd (19 МБ, одиночный диск без multipath), udisks2 (7 МБ), fwupd (31 МБ, виртуалка), apport (отчёты о падениях) — типичный мусор облачного образа Ubuntu, суммарно ~60 МБ RSS и несколько процессов; риска нет, выигрыш мал.
- serial-getty@ttyS0 / getty@tty1 — консоль провайдера, оставить как аварийный доступ.
- Диск (реальная статья): worktrees 50 GiB — многие каталоги принадлежат архивным сессиям; `.cache` 16 GiB; это тема предыдущего disk-audit, здесь только цифры.
- Сироты из §5: ~118 MiB RSS, 0% CPU — по ресурсам ничтожны, значимы как мусор и как поверхность (jupyter, 0.0.0.0).
- cron.service: 1.3 GiB RSS и 11% ядра — крупнейший неопознанный потребитель; что за задания, нужно смотреть отдельно (не установлено).

## 4. Схема гарантий через cgroup (рекомендация, не применялось)

Факты: иерархия `system.slice/orchestra.service` → `orchestra-api` (без лимитов) и `agents` (CPUWeight 50; при двух чтениях подряд показал MemoryHigh/Max 10.5/14 GiB и затем 4.1/6.1 GiB — лимиты кто-то перенастраивает на лету, кто — не выяснял). Дроп-ин `50-workflow-cgroups.conf`: `Delegate=cpu memory io`, `DelegateSubgroup=orchestra-api`. `app/runaway_guard.py` и `app/runtime_process_group.py` — прикладные защиты поверх.

Что даёт гарантии в cgroup v2 (man systemd.resource-control, прочитан в VPS): `MemoryLow/Min` защищают только если выделение задано на ВСЕХ предках, поэтому нужен `system.slice` (или родительский slice) с `MemoryLow`, из которого «раздаётся» вниз; `MemoryMin` — жёсткая, `MemoryLow` — мягкая. `CPUWeight` — относительный, работает только при конкуренции. `MemoryHigh` — троттлинг/реклейм, `MemoryMax` — OOM внутри группы.

Предлагаемый минимум (решение владельца): (1) `MemoryLow` для того, что нельзя вытеснять в своп — kesha-bot-vps (~1.5 GiB), nginx, ssh, orchestra-proxy, mtg/hysteria/xray, и на `system.slice` суммарно (≈4–5 GiB); (2) `CPUWeight`/`IOWeight` выше 100 для этих юнитов и 50 для `agents` (уже); (3) не мешать агентам: `agents` остаётся под MemoryHigh/Max, чтобы рост агентов бил по ним, а не по боту; (4) лимиты применять через `systemctl set-property` в `/etc` (см. коммит 901b6295, иначе теряются при daemon-reload). Проверка эффекта — `memory.events` (`low`, `high`) и swap-out из sar до/после; без измерения это только гипотеза.

## 5. Сироты в cgroup Orchestra (22 процесса; корень юнита перенесён в orchestra-api, ничего не убито)

Все: uid 1001 (kesha), в `orchestra-api` (49 процессов там всего, из них эти 22), суммарно ~118 MiB RSS, CPU за 10 с — 0.0–0.2%. «Кем запущен» установлено по логам сессий (ближайшие команды к времени старта процесса, сверка путей/портов с `ss -ltnp`), живость сессий — по `sessions.status`. Командные строки: `evidence/cmdlines.txt` (токен jupyter скрыт).

| Группа | PID | Что | Старт (UTC) / возраст | RSS | Родитель | Запустила сессия (статус) | Вывод |
|---|---|---|---|---|---|---|---|
| painter-geometry | 736, 4131256 | `python3 oil-paint/windows/server.py` (127.0.0.1:45221/33535), cwd удалён | 06.09 05:12 / 03:39, ~32 сут | 2.2 MiB ×2 | 1 | painter-geometry (archived 06.09) | хвост |
| painter-wall-v2 | 1823051 `node --test`, 1823057 node, 1823080 `server.py --data /tmp/oil-paint-t4` (127.0.0.1:42197) | зависший тест t4_offline_windows и его сервер | 08.09 11:35, 30 сут | 1.3/1.3/2.2 | 1823051→1823057→1823080 | painter-wall-v2 (archived 12.09) | хвост (тест завис с 08.09) |
| fix-ci-green | 865393, 881271 | `uvicorn app.main:app` порты 44865/41541 из `.venv` удалённого worktree | 07.09 06:10 / 06:29, ~31 сут | 13.9 / 14.2 | 1 | fix-ci-green (archived 07.09) | хвост; это тестовые инстансы самой Orchestra, чьи `DATA`-пути неизвестны — стоит убрать, а не оставлять |
| balatro-vps | 1256326, 1332343, 1336221, 1340650, 2338767 | `python3 -m http.server` 18112/18121/18122/18123/18102 (127.0.0.1) | 15.09 09:30–11:43 и 18.09 03:40, 20–23 сут | 3.8–5.0 | 1 | balatro-vps (две сессии, обе archived; последняя 08.10 07:53) | хвосты превью |
| autobattler | 2334703 | `http.server` 18113 | 18.09 03:32, 20 сут | 3.9 | 1 | autobattler (archived 08.10 04:31) | хвост |
| seo-cro | 1545102 (127.0.0.1:8765), 2079424 (**0.0.0.0:8785**) | `http.server` | 24.09 08:41 / 25.09 10:29 | 4.0 / 4.0 | 1 | seo-cro (archived 05.10) | хвосты; 8785 слушает все интерфейсы, но ufw его не открывает (политика INPUT DROP, правил на 8785 нет) |
| komandor-jupyter | 2682938 jupyter-lab, 2688110, 2697550 ipykernel | `jupyter-lab --ip=0.0.0.0 --port=8899`, токен, root_dir `/home/kesha/komandor-data` (каталог существует) | 19.09 04:01–04:33, 19 сут | 16.8 / 5.2 / 5.3 | 2682935 / 2682938 | University-orchestrator (**idle**, жива) | не доказанный хвост: сессия жива и данные на месте, но 0% CPU 19 суток; нужен ответ University-orchestrator/владельца. Порт 8899 ufw не открыт (снаружи недоступен), доступ только с самой машины |
| xray (ручной) | 1764588 | `xray run -c d443.json` SOCKS 127.0.0.1:10822; файл конфига `/tmp/d443.json` удалён, процесс держит конфиг в памяти | 01.09 15:38, 37 сут | 7.0 | 1 | VPN-orchestrator (**idle**, жива; создала конфиг командой от 01.09) | не доказанный хвост; отдельный `xray.service` (nobody, 8443) — другой процесс. Нужен ответ VPN-orchestrator, пользуется ли кто-то SOCKS :10822 |
| ssh-туннель b2b | 578260 | `ssh -N -D 127.0.0.1:19080 root@72.56.235.40` | 07.10 02:45, 33 ч | 6.1 | 1 | b2b-tenders (**idle**, жива) | нужная работа: единственный держатель listener :19080 (по `ss`), используется для РЭТ/Росэлторг |
| ssh-дубли | 1544432, 3185421 | `ssh -fN -D 127.0.0.1:19080 …` с установленным TCP к 72.56.235.40:22, но **без своего listener** (порт занят 578260) | 08.10 02:00 и 11:29 | 3.4 / 5.1 | 1 | b2b-tenders (idle) | хвосты: накапливаются при каждом перезапуске туннеля проверкой `pgrep` |

Корреляция с cgroup-логом: список 21 PID из сообщения feat-workflow-tool (log 604421) совпал с процессами в `orchestra-api`; 22-й, ssh 3185421, в нём отсутствует и стартовал 11:29 — после перемещения, т.е. это новый хвост от b2b-tenders, а не «выживший».

Итог по группам: 17 процессов — безусловные хвосты архивных сессий (painter-geometry 2, painter-wall-v2 3, fix-ci-green 2, balatro-vps 5, autobattler 1, seo-cro 2) плюс 2 ssh-дубля = 19; 3 jupyter и xray — под вопросом у живых сессий; 1 ssh-туннель — нужен. Закрыть без вопросов можно только первые 19; сигналов не посылалось.

## 6. Ограничения и непроверенное

Природа cron.service-нагрузки, `session-166929.scope` и перенастройка `agents` на лету не выяснялись. Пользовательские systemd-менеджеры root/tunnel/codexproxy недоступны по шине (читалось только `kesha`). Причина роста `memory.events high` (2.6 млн) не разложена по источникам. «Лишнее» из §3 — по назначению юнитов, не по измеренному вреду.
