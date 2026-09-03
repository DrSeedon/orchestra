## Summary

Исследование хорошо обосновывает внешний systemd-guard, отказ от in-process watcher как основной границы и статус `CLAUDE_ENV_FILE` как generic workaround, а не vendor opt-out.

Но заявленная жёсткая гарантия не достигнута: pidfd закрывает переиспользование PID, однако не гонку `exec` внутри того же процесса. Также снятие `MemoryMax` и точные пороги пока не следуют из измерений.

## Findings

- **blocking:** `docs/tasks/211/research.md:114` — pidfd + повторная проверка не гарантируют, что сигнал получит всё ещё `ugrep`. После проверки `/proc/PID/{exe,cmdline,starttime}` тот же процесс может выполнить `exec` и превратиться в обычный Claude-процесс до `pidfd_send_signal`; PID и start time не изменятся, а pidfd продолжит ссылаться на него. Поэтому точное утверждение документа — «Обычный агент совпадёт по cgroup/exe, но не по `argv[0]`» — верно только в момент чтения, не в момент доставки сигнала. T1 AC (`plan.md:59`) проверяет PID reuse, но пропускает same-PID exec race. Нужен протокол, исключающий изменение image между финальной проверкой и kill, например остановка через pidfd, подтверждение фактического stopped-state, повторная identity-проверка и лишь затем kill; при несовпадении — resume. Этот протокол и тест конкурентного `exec` должны быть в AC до реализации.

- **blocking:** `docs/tasks/211/research.md:252` — доказан вред `MemoryHigh=8G` в данном инциденте, но не безопасность удаления `MemoryMax=12G`. `memory.events max=0, oom=0` показывает, что `MemoryMax` не участвовал в наблюдённом отказе. Selective guard покрывает только `argv0=ugrep` и прямо не покрывает `bfs`, изменение vendor-механизма, отказ guard или другой runaway. При этом нет измеренного пика легитимной суммарной памяти, физического аварийного потолка или сравнения альтернативных `MemoryMax`/`MemorySwapMax`. Решение снять `MemoryMax` нарушает собственное требование «values must come from measurements» и убирает последнюю fail-safe границу. Снять `MemoryHigh` обоснованно; судьбу `MemoryMax` следует вынести в отдельное измеряемое решение после наблюдения armed guard, а не связывать с T3 автоматически.

- **suggestion:** `docs/tasks/211/research.md:184` — `MAX_AGE_SEC=181` и `POLL_SEC=60` смешивают две независимые величины. Интервал сканирования определяет задержку срабатывания, но не допустимый возраст легитимного процесса; формула `ceil(max) + poll interval` не является статистическим обоснованием. Кроме того, измерены длительности завершённых Bash tool calls, содержащих `grep`, а не lifetime embedded `ugrep`; четыре верхних значения около 120 секунд похожи на censoring/timeout boundary. `MAX_RSS_KIB=528578` получен делением аварийного RSS на произвольные четыре, а 12 bounded-проб не покрывают тяжёлый легитимный recursive search. Эти значения годятся как dry-run hypotheses, но не как заранее принятые armed thresholds. T2 должен требовать построить thresholds из распределения непосредственно измеренных `ugrep` age/RSS с заранее заданным запасом и отдельно подтвердить worst-case detection latency относительно начала деградации.

- **suggestion:** `docs/tasks/211/plan.md:69` — deployment/rollback AC не обеспечивают воспроизводимую установку как единое действие. Есть tracked unit/config/script и перечень host paths, но нет tracked install/uninstall-команды, проверки соответствия установленных файлов конкретной версии, атомарной замены, `daemon-reload` в пути установки и восстановления уже существовавших файлов при полном rollback. `disable --now` лишь выключает процесс и оставляет unit/config/script на хосте; после T3 он также не возвращает memory limits. Добавьте один tracked deploy entry point и один полный rollback entry point либо явно переименуйте существующую команду в “disable guard”, не “rollback”.

- **question:** `docs/tasks/211/research.md:51` — отрицательная проверка opt-out выглядит достаточно сильной в рамках Phase 1: официальные env/settings/schema, строки установленного бинарника и поведенческие пробы нескольких правдоподобных флагов согласуются. Документ корректно не превращает отсутствие находки в универсальное доказательство и честно пишет, что `CLAUDE_ENV_FILE` — документированный общий hook с недокументированным порядком относительно snapshot. Что именно ещё могло бы фальсифицировать вывод: подтверждение Anthropic о dedicated switch либо новый documented setting/version. Сейчас менять этот вывод не требуется.

- **question:** `docs/tasks/211/research.md:127` — D-state evidence не доказывает, что coroutine фактически не исполнялась весь период, и документ это признаёт. Но оно действительно исключает её как гарантированную primary safety boundary: coroutine разделяет event loop, I/O и ресурсную судьбу uvicorn. Формулировка “CONFIRMED по механизму, LIKELY по конкретной задержке” откалибрована корректно.

## Verdict

**Request changes.** Блокируют переход к реализации две вещи: незакрытая same-PID `exec` race перед kill и необоснованное автоматическое удаление `MemoryMax`. Пороги и systemd rollback также нужно уточнить в плане до системного гейта.

## Round (2026-08-12T05:50:38Z)

## Summary

`MemoryMax` and rollback findings are resolved. Thresholds are correctly demoted to hypotheses, but two safety blockers remain: the SIGSTOP protocol cannot provide the claimed hard guarantee, and sampled dry-run peaks can underestimate legitimate usage.

## Findings

- **blocking:** The same-PID `exec` race is narrowed but not closed. The document explicitly says: “Остаточный внешний race — посторонний процесс с правом послать `SIGCONT` между проверкой и kill.” After the final `/proc` check, `SIGCONT` can resume the candidate, allow same-PID `exec` into an ordinary Claude agent, and then the pending `SIGKILL` still targets it. Rechecking `T/t` immediately before kill merely moves the race window; a concurrent test cannot prove its absence. Since the requirement is a hard guarantee, armed mode needs a kernel-enforced stop that `SIGCONT` cannot release—such as a verified ptrace-stop—or it must remain fail-closed and never arm.

- **blocking:** T2’s 10-second polling records sampled RSS, not actual process peaks. A legitimate embedded `ugrep` can peak and fall between scans, so “RSS threshold выше каждого завершённого легитимного peak” is not established by the proposed data. The geometric-mean threshold could consequently kill legitimate pytest/database searches. Calibration needs real per-process peak accounting or controlled coverage of the legitimate worst cases before RSS-based killing is armed.

- **suggestion:** The prior `MemoryMax` finding is resolved: keeping `MemoryMax=12G` unchanged is appropriately conservative because `max=0/oom=0` provides no evidence for removing or retuning it. Removing only measured-harmful `MemoryHigh` is justified.

- **suggestion:** The deployment finding is resolved. The tracked manager now distinguishes emergency disable from full rollback and covers atomic installation, hashes, preserved files, enable-state, `daemon-reload`, and restoration of `MemoryHigh`.

## Verdict

**Request changes.** One prior blocker remains unresolved—the same-PID kill guarantee—and direct RSS calibration still has a blocking measurement gap. The cgroup and rollback changes are satisfactory.
