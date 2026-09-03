# #120 — безопасное завершение SSH-туннелей и background process groups

Дата замеров: 2026-08-01, локальная рабочая машина.

## Вопрос

- **Контекст:** Orchestra запускается как `orchestra.service`; SSH-туннели обслуживают
  общий прокси, а background jobs запускают shell/CLI с `setsid()`.
- **Изменение под проверкой:** убрать поиск процессов по командной строке из
  `ssh_tunnel.py` и убрать PID/PGID TOCTOU из `_kill_proc()`.
- **Baseline:** `pkill -f <regex>` для старых SSH-процессов и
  `getpgid(proc.pid) -> killpg()` для background jobs.
- **Решающие исходы:** cleanup по текстовому поиску больше не способен послать сигнал
  чужому процессу с похожей командной строкой; штатный SSH-туннель
  стартует/останавливается; timeout/cancel background job завершает всю его process
  group, а не только лидера. Числовая гонка внутри `terminate()/kill()` по живому
  SSH process handle явно исключена постановкой как другой класс.

## Гипотезы и falsifiers

1. **H1:** широкий `_kill_stale()` необходим, потому что после падения Orchestra
   старый `ssh` переживает сервис и мешает новому bind.
   **Falsifier:** production supervisor уже гарантированно убирает descendants, а
   `_kill_stale()` не демонстрирует полезных срабатываний при реальных конфликтах.
2. **H2:** точный forward+host regex делает `pkill -f` безопасным.
   **Falsifier:** процесс вне Orchestra с совпадающей либо лишь regex-похожей строкой
   попадает в выборку.
3. **H3:** `_kill_proc()` можно заменить `proc.terminate()/kill()`.
   **Falsifier:** после завершения process handle его descendant остаётся жив.
4. **H4:** на production-host можно безопасно получить стабильный kernel handle и
   сигнализировать всю process group без числового PID/PGID.
   **Falsifier:** host/kernel/libc не поддерживают pidfd group signal, pidfd нельзя
   связать с child identity без post-spawn race, либо сигнал задевает посторонний
   процесс/не завершает потомка.

## Findings

### 1. Зачем появился `pkill -f`

**CONFIRMED — git history + сохранённый прямой замер исходного инцидента.**

`_kill_stale()` добавлен коммитом `266bf7e6` 2026-07-01. В тот день были измерены
три процесса для `:12340` и по два для `:12341`/`:12342`: старые SSH оставались
после смены сети/неграциозного завершения, новый SSH не мог занять порт. Поэтому
cleanup поставили один раз в `start_tunnel()`, до reconnect loop [1][2]. Это был
реальный сценарий, а не случайная перестраховка.

Однако контракт запуска изменился 2026-07-18: если local port уже слушает, Orchestra
теперь помечает туннель `externally_managed` и не вызывает `_kill_stale()` для него.
Cleanup вызывается только для порта, который оказался свободен во время единственной
startup-пробы [3].

### 2. Текущий `pkill` опасен и уже не решает исходный сценарий

**CONFIRMED — direct process-selection experiment + live `/proc`/journal.**

`pkill -f` сопоставляет Extended Regular Expression со всей командной строкой и
посылает сигнал каждому совпавшему процессу [4]. Текущие patterns не ограничены
cgroup, parent PID или сохранённой identity; точки в IP не экранированы и потому
являются regex wildcard.

Изолированный `/tmp`-эксперимент создал три безвредных Python sleeper-процесса с
подменённым `argv[0]`:

```text
pattern=ssh -N -L 23456:127.0.0.1:34567 .*root@198.51.100.42
exact_foreign_matched=True
regex_dot_false_positive_matched=True
different_local_port_matched=False
```

То есть текущий matcher выбирает и посторонний процесс с тем же forward spec, и
процесс с `root@198X51X100X42`. В эксперименте использован `pgrep -f` с тем же
matcher, сигналы не посылались [M1].

Live snapshot в 2026-08-01 17:27 +07 показал:

```text
current_ssh_processes=8
orchestra_cgroup_ssh=2
other_cgroup_matching_config=3
```

Три exact-match процесса принадлежат отдельным user units
`ssh-tunnel-{ezhik,fornex,timeweb}.service`, а не Orchestra. Два процесса
(`contabo`, `contabo-socks`) принадлежат `/system.slice/orchestra.service` [M2].
При одновременном boot user units стартовали примерно на 0.8 s раньше внутренних
SSH. Одноразовая port-проба Orchestra успела увидеть порты свободными, после чего
user units заняли их первыми. Результат: с 2026-07-01 journal содержит
`3513` сообщений `Address already in use`, но `0` сообщений
`killed stale ssh` [M3].

Следствие: broad cleanup не устраняет существующую startup race и способен убить
туннель другого менеджера в коротком окне, когда его процесс уже запущен, а listener
ещё не поднят.

### 3. Для поддерживаемого production lifecycle замена `pkill` не нужна

**CONFIRMED для текущего systemd deployment; UNCERTAIN для ручного запуска вне
systemd.**

Live unit properties:

```text
ControlGroup=/system.slice/orchestra.service
KillMode=control-group
SendSIGKILL=yes
Restart=always
```

Установленная документация systemd 257 определяет `KillMode=control-group` так:
при остановке unit уничтожаются все оставшиеся процессы его cgroup; после
`TimeoutStopSec` оставшиеся процессы получают final `SIGKILL`. Она отдельно
предупреждает, что `KillMode=process/none` позволяют процессам сбежать из lifecycle
service manager [5][M4]. Live `/proc` подтверждает, что два внутренних SSH находятся
именно в cgroup Orchestra [M2].

Текущий `stop_tunnel()` и cancellation path дополнительно завершают текущий
`t.proc` по живому process handle. Поэтому для production systemd lifecycle
`_kill_stale()` дублирует supervisor без ownership proof. Безопасная минимальная
замена — удалить cross-process search; current-run cleanup оставить по `t.proc`,
cross-restart cleanup оставить systemd cgroup.

Codex верно указал, что POSIX-реализация `asyncio Process.terminate()/kill()` внутри
всё равно заканчивается числовым `os.kill()` и CPython признаёт остаточную гонку
между финальным poll и signal [M10]. Но постановка #120 прямо запрещает расширять
задачу на `terminate/kill` по живым handles: это другой, уже инвентаризированный
класс. Поэтому гарантия этого тикета намеренно уже — удалить **broad command-line
selection**, а не объявить весь SSH lifecycle pidfd-safe.

Что при этом теряется: если разработчик запустил Orchestra вручную вне systemd и
убил только Python PID через `SIGKILL`, дочерний SSH может сохраниться. Это реальная,
но другая модель запуска. Без сохранённой kernel-backed identity приложение после
рестарта не может безопасно отличить свой такой SSH от личного SSH пользователя.
В этом режиме лучше fail visible на bind/listener, а не автоматический broad kill.

### 4. В `_kill_proc()` group semantics обязательна

**CONFIRMED — source audit + direct process experiment.**

Все шесть subprocess creation sites, которые обслуживает `_kill_proc()`, создают
новую session через `preexec_fn=os.setsid`; shell-based jobs могут иметь потомков.
Текущий `killpg` поэтому намеренно завершает дерево, а не только shell leader [6].

Изолированный эксперимент создал session leader `/bin/sh` и его `sleep` child,
затем вызвал `terminate()` только на leader handle:

```text
leader_handle_terminated=true child_survived=True
child_pgid=1440686 original_group=1440686
```

Следовательно, простая замена `killpg` на `proc.terminate()/kill()` регрессирует
timeout/cancel: CLI/MCP descendants останутся жить [M5].

Текущий `getpgid(proc.pid) -> killpg(pgid)` остаётся numeric TOCTOU. Если watcher
уже reap-нул exited child, а `proc.returncode` ещё не обновлён в event loop, PID
может быть переиспользован; `getpgid()` тогда вернёт группу нового процесса, после
чего `killpg()` пошлёт сигнал всей чужой группе. Простая замена на
`killpg(proc.pid, ...)` уменьшает окно, но не устраняет reuse числового PGID.

### 5. Kernel primitive есть; наивный post-spawn capture недостаточен

**CONFIRMED для kernel primitive; REFUTED для простого `pidfd_open(proc.pid)` после
spawn — primary API semantics + adversarial counterexample analysis.**

Linux `pidfd_send_signal()` использует стабильную ссылку на процесс: после смерти
исходного процесса возвращает `ESRCH`, а не сигнализирует новый процесс с
переиспользованным PID. С Linux 6.9 флаг `PIDFD_SIGNAL_PROCESS_GROUP` направляет
сигнал всей группе, если pidfd указывает на group leader [7]. Это ровно необходимый
контракт для leader, созданного через `setsid()`.

Production host:

```text
kernel=6.17.0-41-generic
glibc=2.42
/usr/include/.../sys/pidfd.h: PIDFD_SIGNAL_PROCESS_GROUP=(1UL << 2)
libc exports: pidfd_open@@GLIBC_2.36, pidfd_send_signal@@GLIBC_2.36
venv Python 3.12.12: os.pidfd_open=False, signal.pidfd_send_signal=False
```

Первый raw-syscall прогон и второй прогон через exported libc functions дали один
результат. Во втором:

```text
glibc_pidfd_group_signal_rc=0
target_group_exists=False
unrelated_survived=True
```

В первом были два target group members; после group signal выжило `0/2`, unrelated
process выжил [M6]. Значит kernel primitive для этой машины подходит.

Но `asyncio.create_subprocess_*()` возвращает только числовой PID. Открыть pidfd
после возврата недостаточно для строгого доказательства identity: child watcher
может успеть reap-нуть мгновенно завершившийся child, а PID — переиспользоваться до
`pidfd_open()`. Локальные `100/100` запусков `/bin/true` успели открыть pidfd при
`proc.returncode is None`, но это измеряет частоту, а не устраняет гонку [M7]. Именно
эту дыру нашёл незавершившийся первый Codex review; вывод про «маленький adapter» без
изменения spawn contract был слишком сильным.

### 6. Race-free handoff возможен без долгоживущего supervisor

**CONFIRMED на host — self-opened pidfd + `SCM_RIGHTS` + `exec`, 100 fast runs и
process-group experiment.**

Проверенный прототип запускает короткий exec shim в новой session. Shim, пока он
гарантированно жив, открывает pidfd на **самого себя**, передаёт fd родителю через
Unix `SOCK_SEQPACKET`/`SCM_RIGHTS`, ждёт один-byte ACK и делает `execvp()` исходной
команды. После `exec` PID, session/process group и pidfd сохраняют identity; лишнего
долгоживущего процесса не остаётся.

```text
pidfd_handoff_fast_success=100/100
group_members=2
target_survivors=0
unrelated_survived=True
```

Это устраняет post-spawn identity gap: pidfd создаёт сам child до того, как ему
разрешено исполнить и завершить исходную команду [M8]. Контрвариант с
`kill -STOP $$` внутри shell завис внутри `asyncio.create_subprocess_exec()` до
возврата `Process`, поэтому как handshake непригоден и отброшен [M9].

Retained pidfd остаётся пригоден для group signal и после exit/reap leader, пока в
исходной process group есть потомок. Это проверено отдельным сценарием: leader
породил TERM-ignoring child и был reap-нут до cleanup; group TERM через pidfd вернул
`0`, child остался; group KILL вернул `0`, child исчез; unrelated process выжил
[M11]. Следовательно, будущий `_kill_proc()` не должен сохранять нынешний early
`return` при `proc.returncode is not None`: stable pidfd позволяет безопасно убрать
ровно тот orphan tree, который numeric PGID в #113 трогать было нельзя.

Цена решения уже не «две замены signal call»: меняется общий spawn contract шести
background-job call sites и появляется короткий fd-handoff/exec shim. Это меньше
supervisor-wrapper (shim исчезает через `exec`, нового runtime process нет), но всё
равно shared-runtime change. Phase 2 должен отдельно зафиксировать fail-closed
поведение при отсутствии pidfd group support и cleanup fd/socket при cancel/error;
unsafe numeric fallback запрещён.

## Контр-улики и ограничения

- Исторический `pkill` был реакцией на измеренные дубли, поэтому удалить строку без
  проверки supervisor lifecycle было бы неверно. Проверка показала, что именно
  **текущий production lifecycle** уже закрывает crash cleanup; ручной запуск вне
  systemd остаётся отдельным исключением.
- `0` success-логов не доказывает абсолютное отсутствие прошлых срабатываний за всю
  жизнь проекта: journal retention ограничен. Но в доступном окне с 2026-07-01 есть
  3513 bind conflicts и много boot boundaries, то есть полезный эффект на наблюдаемом
  сценарии не проявился.
- Pidfd group flag появился только в Linux 6.9. На текущей машине он измеренно
  работает; совместимость старых Linux/VPS до Phase 2 не заявляется.
- Наивный `pidfd_open(proc.pid)` после обычного asyncio spawn не закрывает identity
  race. Только child-originated fd handoff (измеренный), atomic `pidfd_spawn/clone3`
  или отдельный supervisor дают строгую привязку. В исследовании выбран первый
  кандидат как единственный проверенный без долгоживущего extra process.
- `asyncio Process.terminate()/kill()` не является kernel-backed handle. Этот риск
  подтверждён, но оставлен вне #120 по явной границе постановки; итоговая гарантия
  SSH-части относится только к удаляемому `pkill -f` cross-process search.

## Вывод для гейта

1. В `ssh_tunnel.py` убрать `_kill_stale()` и его startup-вызов. Замена broad search
   не нужна: current-run owned process завершается по handle, cross-restart owned
   processes — через systemd `KillMode=control-group`. Не менять external-listener
   adoption и reconnect-loop в #120.
2. В `bg_jobs.py` сохранить завершение всей process group, но не делать наивный
   post-spawn `pidfd_open(proc.pid)`. Проверенный race-free кандидат — transient
   self-pidfd exec shim с fd handoff, затем `PIDFD_SIGNAL_PROCESS_GROUP`; unsafe
   numeric fallback запрещён. Retained pidfd используется и после leader exit для
   TERM->KILL всей оставшейся группы. Это отдельный shared-runtime ticket, не «две
   строки».
3. Phase 3 обязан проверить реальным subprocess-прогоном: owned SSH стартовал и
   остановился; похожий foreign process пережил stop/cleanup; background leader и
   descendant завершились, включая leader-already-reaped + TERM-ignoring child;
   unrelated process выжил.

## Затрагиваемые файлы и риски

- `app/ssh_tunnel.py`: удалить `_kill_stale()`/startup call; не менять
  `manager.py`, `workspace.py`, routes, TG, RAG и pipelines.
- `tests/test_proxy.py`: foreign similar-cmdline survival + owned handle lifecycle.
- `app/bg_jobs.py`: stable process-group signal lifecycle; все шесть spawn sites и
  все cancel/timeout callers должны пользоваться одним контрактом.
- `tests/test_bg_jobs.py`: leader+descendant termination, unrelated survival,
  unsupported pidfd fail-closed, TERM->KILL escalation.
- Максимальный риск — несовместимый kernel/libc path или потеря descendants при
  fallback. Поэтому Codex review реализации обязателен до merge.

## Источники и измерения

1. **Primary source:** git commit `266bf7e6`, `app/ssh_tunnel.py` diff; исходная
   причина и точное место добавления `_kill_stale()`.
2. **Recorded measurement:** `docs/tasks/proxy-fix/research.md:87-101,138-151,
   199-211`; PID/cardinality исходных дублей и approved fix.
3. **Primary source:** git commit `4cc8c32`, `app/ssh_tunnel.py` diff; добавление
   `externally_managed` и port-probe before cleanup.
4. **Primary upstream manual:** procps-ng `pgrep/pkill(1)`, full command line and ERE
   semantics: <https://www.man7.org/linux/man-pages/man1/pkill.1.html>.
5. **Primary installed manual:** systemd 257 `systemd.kill(5)`, строки `KillMode=`;
   сверено с live `systemctl show orchestra`.
6. **Primary source:** `app/bg_jobs.py:114-132,517-524,587-691`; `_kill_proc()` and
   six `setsid()` spawn sites.
7. **Primary upstream manual:** Linux `pidfd_send_signal(2)`, stable identity and
   `PIDFD_SIGNAL_PROCESS_GROUP`: <https://man7.org/linux/man-pages/man2/pidfd_send_signal.2.html>.
8. **Primary upstream docs:** Python asyncio subprocess `Process` methods affect the
   child process handle: <https://docs.python.org/3/library/asyncio-subprocess.html>.
9. **M1 — direct measurement:** three fake-argv sleeper processes + `pgrep -f`,
   sequential under `nice -n 15`; output quoted in Finding 2.
10. **M2 — direct measurement:** `/proc/<pid>/{cmdline,cgroup}`, `pgrep -x ssh`,
    `ss -ltnp`, snapshot 2026-08-01 17:27 +07.
11. **M3 — direct measurement:** `journalctl -q -u orchestra --since 2026-07-01
    --grep=...`; `0` cleanup successes, `3513` bind conflicts.
12. **M4 — direct measurement:** `systemctl show/cat orchestra`; cgroup and kill
    policy quoted in Finding 3.
13. **M5 — direct measurement:** temporary shell session + child, leader-only
    `terminate()`, sequential under `nice -n 15`; output quoted in Finding 4.
14. **M6 — direct measurement:** two temporary process groups, raw syscall and libc
    `pidfd_*`, sequential under `nice -n 15`; all target members exited, unrelated
    process survived.
15. **M7 — direct measurement:** 100 sequential `/bin/true` asyncio spawns;
    immediate post-spawn `pidfd_open` succeeded 100/100 while returncode was `None`.
    This is frequency evidence, not a race-freedom proof.
16. **M8 — direct measurement:** child self-opened pidfd, `SCM_RIGHTS` handoff, ACK,
    then `execvp`; 100/100 fast commands completed, 2/2 target group members exited,
    unrelated process survived.
17. **M9 — counterexperiment:** shell self-`SIGSTOP` before parent capture blocked
    `asyncio.create_subprocess_exec()` itself; exact owned temp PIDs were verified and
    removed after the bounded probe.
18. **Primary upstream manual:** glibc lists `pidfd_spawn` as an atomic process
    creation primitive, but integrating its file actions/pipes with asyncio was not
    measured and is not the selected candidate:
    <https://sourceware.org/glibc/manual/latest/html_node/Process-Creation-Concepts.html>.
19. **M10 — primary installed source:** CPython 3.12 `subprocess.Popen.send_signal()`
    explicitly says PID reuse can still occur between its returncode test and
    `os.kill()`; `asyncio` delegates through that method.
20. **M11 — direct measurement:** retained leader pidfd after `wait()`/reap;
    `PIDFD_SIGNAL_PROCESS_GROUP` TERM left the TERM-ignoring child alive, KILL removed
    it, unrelated process survived; sequential under `nice -n 15`.
