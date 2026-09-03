# #211 — план реализации после гейта

Дата: 2026-08-12. Это проект Phase 1. Ни один шаг ниже не разрешён к исполнению до отдельного
гейта на системную конфигурацию боевой машины.

## Approach

Один владелец остановки — маленькая stdlib-only systemd-служба вне `orchestra.service`.
Policy хранится отдельно от логики. Она не ищет процесс «по похожему имени», а требует точное
совпадение cgroup + executable + NUL `argv0=ugrep`, затем проверяет age/RSS, открывает pidfd,
kernel-freeze'ит cgroup `orchestra.service`, подтверждает `cgroup.events frozen=1`,
перепроверяет identity/start time и только затем посылает `SIGKILL` этому handle. При
несовпадении — no kill; cgroup всегда thaw в `finally`. Решение и результат пишет в journal.

Orchestra application code, DB и TG в v1 не меняются. Если позже понадобится уведомление,
приложение будет только читать journal-event и объяснять его, без signal permissions и без
копии policy.

Provisional policy для первого dry-run (не armed values):

```text
TARGET_CGROUP=/system.slice/orchestra.service
TARGET_EXE=/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
TARGET_ARGV0=ugrep
MAX_AGE_SEC=181
MAX_RSS_KIB=528578
POLL_SEC=10
RSS_ACTION=log
DRY_RUN=true
```

До armed режима остаётся текущая временная защита владельца. После direct dry-run строятся
новые thresholds и только затем возможен `DRY_RUN=false`. После активации guard снимается
`MemoryHigh`; `MemoryMax=12G` и `OOMScoreAdjust=800` остаются.

## What not to touch

- не добавлять periodic task в `app/main.py`, `_collect_usage_snapshot` или другой uvicorn
  event loop;
- не читать/писать SQLite и не вызывать Orchestra/TG из guard;
- не использовать `comm`, `pgrep -x`, `pkill -f`, shell regex по полной command line;
- не сигналить parent shell/Claude agent и не перезапускать `orchestra` автоматически;
- не добавлять `bfs` в armed policy без отдельного измерения;
- не менять `OOMScoreAdjust=800`, `tinyproxy` или чужие systemd units;
- не отключать временный watcher до положительной kill-приёмки OS guard;
- не включать `CLAUDE_ENV_FILE` для живых агентов без отдельного окна reconnect/restart.

## Tickets

### T1 — Селективный process guard как тестируемый tracked artifact

- Files: `scripts/orchestra_process_guard.py`, `deploy/orchestra-process-guard.service`,
  `deploy/orchestra-process-guard.conf`, `deploy/manage-process-guard.sh`,
  `tests/test_process_guard.py`
- AC:
  - parser принимает policy из отдельного EnvironmentFile; отсутствие обязательного поля или
    нечисловой/неположительный threshold завершает службу с ненулевым кодом и записью в journal;
  - matcher требует одновременное точное совпадение cgroup, resolved exe и NUL `argv0`;
  - fixture embedded ugrep проходит identity matcher, обычный Claude CLI, uvicorn и процессы
    вне cgroup — не проходят;
  - один только `comm=ugrep` не влияет на результат теста;
  - age/RSS связаны `OR`, identity и thresholds — `AND`;
  - guard выполняет только `cgroup.freeze=1` → `cgroup.events frozen=1` → повторная проверка
    starttime/cgroup/exe/argv0 → pidfd `SIGKILL`; несовпадение/исчезновение получает no kill;
  - thaw (`cgroup.freeze=0`) находится в `finally`; startup recovery и `ExecStopPost` также
    thaw'ят policy cgroup после crash/stop guard;
  - freeze, не достигший `frozen=1` за `FREEZE_TIMEOUT_SEC`, заканчивается thaw + alert + no
    kill; armed mode fail-closed;
  - конкурентный тест заставляет candidate пытаться сделать same-PID `exec` и шлёт внешний
    `SIGCONT` после `frozen=1`: image не меняется до thaw, kill получает только original pidfd;
  - `DRY_RUN=true` пишет то же decision event, но signal API не вызывается;
  - kill log содержит PID/PPID/start/cgroup/exe/argv0/age/RSS/threshold/result, но не полную
    cmdline и не environment;
  - unit запускается отдельной службой, не имеет dependency на активность `orchestra.service`,
    пишет stdout/stderr в journal и рестартует только сам guard;
  - tracked `manage-process-guard.sh install|disable|rollback` атомарно устанавливает файлы,
    проверяет SHA установленного script/unit/config, делает `daemon-reload`, сохраняет только
    реально существовавшие файлы с owner/mode и полностью восстанавливает их по `rollback`;
  - targeted pytest зелёный; мутация `argv0` и мутация cgroup делают positive fixture красной.
- blocked-by: none

### T2 — Установка в observe-only и калибровка на одном суточном цикле

- Files/objects: `/usr/local/libexec/orchestra-process-guard`,
  `/etc/orchestra-process-guard.conf`,
  `/etc/systemd/system/orchestra-process-guard.service`, journal
- AC:
  - перед записью сохранены owner/mode целевых каталогов; установка не меняет mode соседних
    файлов;
  - `systemd-analyze verify` unit проходит;
  - `DRY_RUN=true`; tracked install entry point не рестартует и
    не reload-ит `orchestra.service`;
  - live controlled process с executable Claude и `argv0=ugrep` распознаётся; ordinary Claude
    и uvicorn появляются в диагностическом счётчике как non-match и не получают signal;
  - calibration scan записывает direct `(pid,starttime,age,VmRSS,VmHWM)` exact-match
    процессов; косвенные Bash tool durations не используются как lifetime;
  - до чтения результата зафиксирована age-формула: geometric mean между max завершённого
    legitimate lifetime и минимальным аварийным endpoint 720 с;
  - armed age + armed poll interval <720 с; если условие не выполнено, T3 заблокирован и
    threshold не подгоняется;
  - `RSS_ACTION=log` остаётся в T3: sampled RSS/VmHWM не может убить. Отдельный будущий гейт
    на `RSS_ACTION=kill` требует VmHWM dry-run плюс controlled worst-case peak через wait4/time;
  - full `/proc` scan p99 остаётся <1 с; сам guard RSS <32 MiB;
  - emergency disable проверен `sudo deploy/manage-process-guard.sh disable`; full rollback
    проверен `sudo deploy/manage-process-guard.sh rollback`, после чего сохранённые файлы и
    enable-state совпадают с pre-install snapshot; затем dry-run установлен заново;
  - временный bg-сторож всё это время остаётся активным.
- blocked-by: T1

### T3 — Armed guard и удаление только вредного `MemoryHigh`

- Files/objects: `/etc/orchestra-process-guard.conf`,
  `/etc/systemd/system/orchestra.service.d/oom.conf`, runtime systemd properties,
  journal
- AC:
  - перед переключением manager сохраняет `oom.conf`, runtime properties, enable-state и
    owner/mode для полного однокомандного rollback;
  - `DRY_RUN=false`; controlled exact-match process, превышающий тестовый policy, получает
    signal через cgroup-freeze + pidfd; ordinary Claude, uvicorn и процесс вне cgroup
    переживают ту же пробу; freeze duration `/login` записана;
  - kill в T3 срабатывает только по calibrated age; `RSS_ACTION=log` подтверждён в effective
    config и oversized controlled candidate по одному RSS не получает signal;
  - journal до и после signal однозначно отвечает «кого, почему, каким сигналом и с каким
    результатом»;
  - только после положительной kill-пробы из permanent drop-in удалён `MemoryHigh`, а runtime
    `MemoryHigh` очищен до `infinity`; `MemoryMax=12G` и `OOMScoreAdjust=800` не изменены;
  - `systemctl show orchestra` показывает `MemoryHigh=infinity`, `MemoryMax=12G`,
    `OOMScoreAdjust=800`; активные агенты и `/login` продолжают работать, `orchestra` не
    рестартован;
  - полный rollback — одна команда `sudo deploy/manage-process-guard.sh rollback`; она
    отключает guard, восстанавливает установленные файлы/enable-state и возвращает прежний
    `oom.conf` + runtime `MemoryHigh=8G`, не меняя `MemoryMax=12G`; команда rehearsed;
  - временный bg-сторож отменяется владельцем только после всех предыдущих AC.
- blocked-by: T2

### T4 — Доставить durable OS-event владельцу после восстановления Orchestra

- Files: `app/process_guard_events.py`, `app/main.py`, `app/tg_bridge.py`,
  `tests/test_process_guard_events.py`; object:
  `/var/lib/orchestra-process-guard/events/`
- AC:
  - OS stopper атомарно публикует immutable JSON event после каждого dry-run decision,
    freeze timeout и kill result; тот же event ID присутствует в journal;
  - event содержит только allowlist: event ID/time, PID/PPID/starttime, cwd, cgroup,
    basename exe, argv0, age/VmRSS/VmHWM, reason, freeze duration, signal/result; cmdline и
    environment отсутствуют;
  - reporter не читает process policy и `/proc`, не имеет права signal/cgroup-write; его
    единственный вход — event directory;
  - reporter сопоставляет сохранённый cwd с текущим worktree session; если однозначного match
    нет, TG честно пишет `worker неизвестен`, а не угадывает;
  - событие уходит в TG как `important=True` после восстановления bridge; при недоступном TG
    остаётся pending и повторяется, delivery dedupe хранится по event ID;
  - crash между TG send и ack допускает дубль с тем же event ID, но не потерю; тест покрывает
    fail-before-send и fail-after-send;
  - reporter startup/loop не находится на HTTP startup critical path и не может задержать
    сам OS stopper; остановка reporter не влияет на kill-policy;
  - journal alone остаётся достаточным утренним audit даже при постоянном отказе TG.
- blocked-by: T1

### T5 — Убрать vendor shadowing для новых Bash-команд через документированный hook

- Files/objects: `/etc/orchestra/claude-env.sh`, отдельный systemd environment drop-in для
  `CLAUDE_ENV_FILE`
- AC:
  - env script содержит только `unset -f grep find 2>/dev/null || true` и не подменяет команды
    второй функцией/wrapper;
  - fresh controlled Claude Bash probe после подключения показывает `type -t grep/find = file`
    и GNU `/usr/bin/grep`/`/usr/bin/find`;
  - probe с hook доказывает обычный нерекурсивный `grep` на каталоге и явный `grep -r` на
    bounded fixture;
  - изменение не применяется через незапрошенный restart: reconnect/restart живых агентов —
    отдельный явный maintenance gate;
  - rollback — одна команда, отключающая только dedicated environment drop-in и делающая
    `daemon-reload`; после разрешённого fresh reconnect snapshot снова даёт embedded ugrep;
  - OS guard остаётся активен: hook не считается стабильным vendor opt-out и не заменяет
    независимый safety boundary.
- blocked-by: T1

## Order and gates

1. T1 — код/тесты, без системных изменений.
2. Отдельный системный гейт → T2 dry-run.
3. Один суточный цикл и review direct measurements → отдельный гейт → T3 armed + снять
   `MemoryHigh`.
4. T4 подключается в согласованное окно загрузки нового Python-кода; он не блокирует T3 и
   не является safety boundary.
5. T5 только в согласованное окно reconnect/restart; он не блокирует T3.

## Rollback decision

Экстренное отключение и полный откат — разные операции и так названы в CLI manager. `disable`
только останавливает guard; `rollback` одной командой возвращает файлы, enable-state и
`MemoryHigh=8G`. `MemoryHigh` снимается после armed guard, потому что измерен его вред.
`MemoryMax=12G` остаётся как последний неселективный fail-safe: данных для безопасного снятия
или нового значения нет, и он не участвовал в наблюдённом инциденте (`max=0`, `oom=0`).

## Codex disposition

Раунд 1 (`codex-review-research.md`) отклонил direct pidfd kill, снятие `MemoryMax`, indirect
thresholds и неполный rollback. `MemoryMax` и rollback исправлены и приняты раундом 2;
thresholds переведены в direct calibration.

Финальный разрешённый раунд 2 остался `Request changes`: `SIGSTOP` допускает внешний
`SIGCONT`, а sampled `VmRSS` не доказывает peak. После него план заменён на kernel-confirmed
cgroup freeze, а RSS переведён в log-only до отдельного peak-evidence gate. По потолку
`codex-debate` третьего раунда нет, поэтому эти две post-review правки не имеют независимого
вердикта. Это явно вынесено на текущий гейт; реализация не должна начинаться молча.
