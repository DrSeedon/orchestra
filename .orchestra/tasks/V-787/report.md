# V-787 — cron.service-cgroup и cgroup-гарантии

Evidence: `evidence/` (before.txt, after.txt, after-final.txt, apply.sh/apply.log, rollback.sh, crontabs-and-runs.txt, cron-sample-30min.txt, snap.sh, sampler.sh).

## 1. Что живёт в cron.service

Сам демон: один процесс `/usr/sbin/cron -f -P` (PID 3169879, RSS 2.2 МиБ, root, с 11.09, ~27 сут), 0% CPU. Все остальное — дочерние процессы заданий, которые systemd учитывает в cgroup cron.service. Поэтому «1.3 ГБ и 11% ядра» — это суммарная нагрузка заданий, а не cron. Память сейчас 47 МиБ, из них anon 0.1 МиБ, остальное page cache; пик 1.5 ГиБ — кэш файлов и работа сборщиков тендеров. Средний CPU за жизнь юнита: 3 сут 7 ч 42 мин за ~27 сут ≈ 12% ядра — совпадает с замером 11%.

Задания (24 ч по journal, `crontabs-and-runs.txt`):
| Задание | Кто/откуда | Частота | Нужно? |
|---|---|---|---|
| `/usr/local/sbin/seedon-delivery-watchdog` (python, пишет в logger) | /etc/cron.d/seedon-delivery-watchdog, user kesha, с 12.08 | каждую минуту (1439/сут) | да — страж доставки seedon-бота |
| `debian-sa1` | /etc/cron.d/sysstat | каждые 10 мин + ежедневно | да — источник sar, использован в V-786 |
| сборщики тендеров seedon (`tender-cron.sh last/big/roseltorg/watch/eis44/eis223`, прямые `run.py` РТС-Маркет, РТС-поиск, ночной) | crontab kesha, проект seedon (b2b-tenders, правки 30.09–03.10) | ежечасно, раз в 4 ч и т.п. | да, пока жив проект seedon; главный источник CPU и RAM (python3 run.py, до таймаутов 600–3000 с, под flock) |
| `tender-accumulate.sh` | crontab kesha | ежечасно | как часть seedon |
| `ops-cron.sh` (сборка календаря, rsync на ops.seedon.ru) | crontab kesha, V-148 | каждые 30 мин | да, пока жива страница ops |
| duckdns update для dnd-game-master | crontab kesha | каждые 30 мин | да, если dnd-game-master публикуется по DDNS |
| run-parts cron.hourly (fstrim) / cron.daily | система | ежечасно/сутки | да |
| certbot renew | /etc/cron.d/certbot | 2 раза/сутки, условие `! -d /run/systemd/system` не выполняется → холостой | мусор, но безвредный |
| `@reboot staticroute` | /etc/cron.d/staticroute | при загрузке | да |

Сэмпл процессов (≈30 мин, 2-секундный шаг, `cron-sample-30min.txt`, сэмплер ещё дописывал хвост на момент отчёта): большую часть времени виден только демон; под нагрузкой появляются watchdog (python3 + bash + logger), ssh (ConnectTimeout=6, из watchdog), fstrim. Итог полного окна (15:00–15:30 CEST, сэмплер завершён): CPU cgroup 3,4% одного ядра, memory.peak 1,51 ГиБ (прежний, новый пик не выставлен). Тяжёлых сборщиков тендеров в окне не попало — они запускаются в свои минуты (:15, :20, :25, :45, :50, :59). Следовательно, вывод о том, что именно сборщики дают 1.3 ГиБ пика, — по расписанию и таймаутам, прямым замером не подтверждён.

Вывод: убивать нечего; нагрузка — расписание seedon-проектов (владелец решает, нужна ли частота сборщика каждый час и `watchdog` каждую минуту). Устаревшее: record по certbot-cron, бэкапы `crontab.bak-*` в ~/.local/share/seedon (мелочь).

## 2. Гарантии (применено через `systemctl set-property` без --runtime → /etc/systemd/system.control)

Измерения: у kesha-bot-vps RSS 1.46 ГиБ, пик cgroup 3.85 ГиБ (memory.peak), memory.events все нули; system.slice сейчас ~14.8 ГиБ (orchestra 4–10 ГиБ, бот 1.5, прочее). Защита работает только при выделении на всех предках, поэтому на system.slice задан бюджет.

| Юнит | MemoryMin | MemoryLow | CPUWeight | IOWeight |
|---|---|---|---|---|
| system.slice | 2G | 10G | — | — |
| kesha-bot-vps | 1536M | 4G | 500 | 500 |
| orchestra.service | — | 4G | 200 | 200 |
| nginx, ssh, telegram-bot-api, orchestra-proxy, xray, hysteria, mtg, tinyproxy | — | 128M (nginx 256M, tg-bot-api 512M) | 150 | 150 |

Обоснование: Min бота 1.5G ≈ его RSS (жёсткая гарантия обычной работы), Low 4G ≈ пик 3.85G; сумма Min детей (1.5G) ≤ Min слайса (2G), сумма Low детей (бот 4G + orchestra 4G + сети ≈1.8G ≈ 9.8G) ≤ Low слайса 10G. Orchestra-у Low 4G (чуть выше типичной работы 3–5G), внутреннее деление (orchestra-api 100/agents 50) не тронуто. Вес CPU/IO: бот 500 > orchestra 200 > сети 150 > остальное 100.

Проверка эффективных cgroup-файлов (after-final.txt): memory.min/low, cpu.weight, io.weight совпали с заданным у system.slice, kesha-bot-vps, orchestra.service и сетевых; после `daemon-reload` значения остались; все 10 сервисов active, перезапусков не было; oom/oom_kill = 0.

**Инцидент по ходу:** после set-property на orchestra.service эффективные memory.high/max скатились к 8G/12G (а не 14G/16G), хотя файлы /etc остались 15032385536/17179869184. Причина: устаревший `/run/systemd/system.control/orchestra.service.d/50-Memory{High,Max}.conf` (от 03.08, значения 8G/12G); runtime-слой перекрывает /etc, а до моего reload systemd держал в памяти 14G/16G. Исправил в тот же момент: `systemctl set-property --runtime orchestra.service MemoryHigh=15032385536 MemoryMax=17179869184` → эффективные memory.high=15032385536, max=17179869184 (как и было до меня). Окно с 8G/12G длилось ~15 с при потреблении 4.2 ГиБ; `memory.events` orchestra не изменились (high 2619622, max 0, oom 0). **Рекомендация владельцу:** удалить устаревший run-слой после ближайшей перезагрузки не нужно (tmpfs, исчезнет сам), но до неё любой `daemon-reload` будет держать run-слой приоритетным; значение я уже совместил с /etc, так что расхождения нет. Это же объясняет «перенастройку на лету» из V-786 для agents? — нет, agents задаётся приложением (runtime_process_group), отдельно.

## 3. Откат одной командой
`ssh kesha@localhost 'bash -s' < .orchestra/tasks/V-787/evidence/rollback.sh` — сбрасывает только значения V-787 (Min/Low/CPUWeight/IOWeight), MemoryHigh/Max orchestra не трогает.

## 4. Ограничения
Эффект гарантий под реальным давлением не измерен (сейчас памяти хватает, `low` events = 0): проверять по `memory.events: low`/swap-out в sar при следующем пике. `ssh.service` настроен, но соединения идут через `ssh.socket` — cgroup сервиса получает вес только на время сессий.
