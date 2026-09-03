# #379 — почему socket-activated Orchestra осталась `active`, но перестала принимать HTTP

Дата исследования: 2026-08-23. Фаза: 1, research + локальный эксперимент. На живом
`orchestra.service` не выполнялись `systemctl`, сигналы, рестарты, deploy или запись в `.env`.
Живой контур использован только как read-only источник: `/proc`, `ss`, journal и SQLite в
`mode=ro`.

## Вопрос

**Context.** Один Uvicorn-процесс принимает системный TCP listener `:8888` через
`orchestra.socket` (`Accept=no`, `--fd 3`). Codex CLI переживают смену Python-супервизора через
`KillMode=process` и systemd FD store (#230/#237).

**Change under test.** Здесь нет заранее выбранной правки. Проверяется причинное объяснение
инцидента 23.08: (а) сама сохранённая accept queue, (б) утечка listener FD в CLI-процессы,
(в) незавершившееся старое поколение или (г) отказ handover/admission.

**Baseline.** Исправный service-only restart обязан оставить socket открытым, запустить новый
acceptor и отдать ему уже установленные соединения. Полный stop socket/service — аварийная
операция, которая освобождает FD store и не обязана сохранять ходы.

**Outcome.** Объяснение принято только если оно одновременно объясняет: `POST /api/restart`
вернул 200; Uvicorn перестал принимать; systemd продолжал показывать service active; `Recv-Q`
рос; новый MainPID долго не появился; service-only и полный socket→service cycle наблюдались
по-разному; listener был виден у дочерних процессов. Нужен воспроизводимый локальный конечный
эффект, а не только совпадение конфигурации.

## Гипотезы и фальсификаторы

| ID | Гипотеза | Что её опровергает | Итог |
|---|---|---|---|
| H1 | Сохранённая очередь сама делает следующий Uvicorn непригодным | Новый Uvicorn на том же listener обслуживает свежий HTTP при `Recv-Q=350` | **REFUTED**: 3/3 раза 200, очередь 350→0 |
| H2 | Listener FD в Codex-детях не даёт запустить следующее поколение service | Новый acceptor обслуживает тот же open socket при других живых дубликатах; systemd допускает оставшиеся процессы при `KillMode=process` | **REFUTED для service-only**, **CONFIRMED для настоящего rebind** |
| H3 | Старый Python уже перестал accept, но не завершился; `Restart=always` не получил exit и не запустил новый MainPID | Новый PID в `RestartSec=5`, отсутствие событий старого PID после `Finished server process` | **CONFIRMED**: старый PID логировал через +600 с, новый PID появился только в 16:53 |
| H4 | Preflight/handover отказался, поэтому рестарт не был начат | 200 от endpoint, успешный outcome и `handed 10 live agent(s)` | **REFUTED** для инцидента |
| H5 | Обычный restart service вообще не восстановил HTTP из-за старой очереди | Новый PID после service-only обслуживает реальные запросы до полного recycle | **REFUTED**: journal содержит 200 и 302 |

## Метод и предрегистрация стенда

Стенд — `docs/tasks/379/socket_stand.py`. Он использует тот же production-интерпретатор,
Python 3.12.3, Uvicorn 0.48.0 и uvloop 0.22.1, но только `127.0.0.1` и случайные порты.[4][5]

До запуска заданы критерии:

1. **FD leak:** один inode listener должен открыться в дочернем процессе при uvloop +
   inheritable FD и не открыться при stdlib asyncio либо `FD_CLOEXEC`.
2. **Queue-cause:** 350 полностью установленных, но ещё не принятых TCP-соединений считаются
   причиной только если новый Uvicorn на том же listener не отдаст свежий HTTP 200 за 5 с.
3. **True recycle:** после закрытия owner-копии повторный `bind()` обязан дать `EADDRINUSE`,
   пока leaked child держит listener, и пройти после смерти ребёнка. Контроль с non-inheritable
   FD обязан позволить bind при живом ребёнке.
4. **uvloop shutdown timeout:** запрос `shutdown_default_executor(0.05)` считается соблюдённым,
   только если возвращается существенно раньше, чем worker освободится через 0.5 с.

Команда, три независимых запуска:

```bash
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python \
  docs/tasks/379/socket_stand.py
```

## Что произошло в production

### Наблюдаемая шкала

Read-only команда:

```bash
journalctl -u orchestra.service \
  --since '2026-08-23 15:55:45' --until '2026-08-23 17:00:35' \
  --no-pager -o short-iso
```

| Время CEST | Наблюдение |
|---|---|
| 15:56:02 | PID 1092440 вернул `POST /api/restart` → 200 |
| 15:56:03 | outcome: `дренаж 0.2 с, разорвано ходов: 0`; Uvicorn `Shutting down` |
| 15:56:04 | `handed 10 live agent(s) to systemd`; `Application shutdown complete`; `Finished server process [1092440]` |
| 16:06:04 | **тот же PID 1092440** исполнил таймер: `[Orchestra-orchestrator] automatic hibernate unavailable…` |
| 16:53:28 | только теперь появился новый Uvicorn PID 1191988 |
| 16:53:39 | PID 1191988: `Uvicorn running on socket ('0.0.0.0', 8888)` |
| 16:54:06 | PID 1191988 обслужил `GET /api/usage/readiness` → 200 |
| 16:54:10 | PID 1191988 обслужил `GET /` → 302 |
| 16:54:46–47 | операторский следующий stop: PID 1191988 штатно завершил lifespan и handover |
| 17:00:17–26 | после полного socket→service cycle стартовал PID 1202690 и начал принимать HTTP |

Это direct measurement, evidence tier 1.[1] В той же сохранённой сессии диагностический
`sleep 10; systemctl show ...; curl ...` ещё показывал MainPID 1092440 и таймаут curl; запись
tool-result попала в SQLite только после восстановления, поэтому её DB timestamp нельзя
использовать как время события. Journal даёт независимый положительный контроль: PID 1092440
точно выполнял asyncio-код через десять минут после собственного `Finished server process`.[2]

### Почему `active`, но HTTP висит

`os.kill(os.getpid(), SIGINT)` в `app/routes/system.py:2375-2378` просит Uvicorn завершиться,
но endpoint заранее отвечает только `{"scheduled": true}` (`:2400-2425`). Он не проверяет ни
exit старого PID, ни появление нового PID, ни первый обслуженный байт.[6]

Uvicorn закрыл acceptor и завершил ASGI lifespan. Однако `Finished server process` оказался
не равен смерти процесса: старый PID продолжил выполнять loop как минимум 600 с. По контракту
systemd `Restart=always` срабатывает после выхода service process, а не после строки Uvicorn.
Пока exit не состоялся, unit законно оставался active, новый acceptor не запускался, а
`orchestra.socket` продолжал завершать TCP handshakes и складывать их в accept queue.[9][10]

Конкретный post-Uvicorn waiter посмертно не снят: thread/task dump PID 1092440 до принудительного
restart не делался. Но граница установлена:

- `app/main.py:348-367` завершил lifespan;
- handed-over sessions обходят `session.stop()` в `manager.shutdown_all()`
  (`app/manager.py:2285-2308`), поэтому их session-owned task teardown там отсутствует;
- отменённый Codex turn в `app/session.py:1921-1933` способен в `finally` поставить новый
  hibernate task; `HibernateManager.schedule()` создаёт его отдельно (`session_hibernate.py:45-68`);
- ровно такой hibernate task старого PID реально проснулся через 600 с;
- production uvloop игнорирует timeout `shutdown_default_executor`: локальный вызов с бюджетом
  50 мс ждал фактического освобождения worker 500.7/521.2/522.7 мс (3/3). Это объясняет, как
  loop **может** продолжать исполнять поздние задачи уже после Uvicorn
  `Finished server process`; проба не приписывает инцидент конкретному executor work item.[4]

**Confidence:** CONFIRMED для класса причины «старый supervisor не вышел после завершения
Uvicorn»; LIKELY для комбинации late session task + uvloop executor shutdown; UNCERTAIN для
точного blocking work item, потому что его stack не был сохранён.

## Результаты локального стенда

### E1 — listener действительно наследуется через production uvloop

Матрица 3/3 совпала побайтно по исходу:

| loop | parent FD inheritable | child видит тот же inode listener |
|---|---:|---:|
| stdlib asyncio | true | нет, `EBADF` |
| stdlib asyncio | false | нет, `EBADF` |
| uvloop 0.22.1 | true | **да** |
| uvloop 0.22.1 | false | нет, `EBADF` |

Uvicorn 0.48.0 при `--fd` делает `socket.fromfd(self.fd, ...)` и затем
`sock.set_inheritable(True)`.[11] Наша программа при этом не вызывает
`sd_listen_fds[_with_names]`; `app/fdstore.py:79-115` лишь читает env и номера. Официальный
`sd_listen_fds()` как раз ставит `FD_CLOEXEC` на все принятые дескрипторы — защиты, которую
мы обошли прямым `--fd 3`.[12]

Read-only production-снимок сопоставлял **inode**, а не просто номер `fd=3`:

```text
listener inode 30218350
python PID 1202690: fd 3 flags 04002, fd 14 flags 02004002
12 × node: fd 3, тот же inode, flags 02004002
1 × sh: fd 3, тот же inode
native codex owners: 0
```

Инцидентный сохранённый `ss` показывал 11 `node`-обёрток + Python на одном LISTEN `:8888`.[2]
Значит обязательное наблюдение **подтверждено для Node launcher**, но формулировка
«node/native» была шире данных: native Codex binary в owner list не было ни тогда, ни в текущем
inode-снимке. Node после наследования сам ставит CLOEXEC, поэтому следующий native exec уже не
получает listener. Утечка также не Codex-специфична: текущий `sh` доказывает общий класс всех
uvloop-spawned direct children.[3][4]

**Confidence: CONFIRMED** — incident snapshot + текущий inode census + controlled A/B.

### E2 — `Recv-Q=350` не мешает новому Uvicorn принимать

Стенд сначала создаёт 350 успешных TCP connect без acceptor, проверяет `/proc/net/tcp`
(`rx_queue=350`), затем запускает новый Uvicorn на **том же listener** и делает свежий HTTP.

| Run | queue до acceptor | свежий HTTP | latency | queue после |
|---:|---:|---|---:|---:|
| 1 | 350 | `HTTP/1.1 200 OK` | 600.2 мс | 0 |
| 2 | 350 | `HTTP/1.1 200 OK` | 443.3 мс | 0 |
| 3 | 350 | `HTTP/1.1 200 OK` | 451.2 мс | 0 |

Systemd прямо документирует это как нормальное поведение `FlushPending=no`: pending connections
сохраняются, чтобы следующее поколение обслужило их после restart.[9] Увеличение очереди —
измеритель отсутствия acceptor, не объяснение, почему acceptor не появился.

**Confidence: REFUTED H1** — direct production-shaped Uvicorn measurement, 3/3.

### E3 — leaked FD блокирует rebind, но не service-only handoff того же socket

| FD в child | `bind()` после закрытия owner, child жив | после exit child |
|---|---|---|
| inheritable, реально получен через uvloop | `EADDRINUSE` | `bind-ok` |
| non-inheritable, child получил `EBADF` | `bind-ok` | `bind-ok` |

Все 3 запуска дали тот же результат.[4] Это важное разделение:

- новый service получает от активного `.socket` **тот же open socket** и может accept;
- настоящий stop/start `.socket` должен создать **новый socket** и не может bind, пока хоть
  один leaked launcher держит старый inode.

Официальное описание `KillMode=process` отдельно говорит, что дочерние процессы могут остаться
в cgroup даже когда service уже считается stopped; поэтому один факт их существования не
блокирует новый service main.[10]

**Confidence:** CONFIRMED для rebind barrier; REFUTED как причина отсутствия service-only
acceptor.

Два вывода получены отдельными arms стенда: queue+новый Uvicorn и leaked holder+rebind.
Production 200/302 связывает их на реальном service-only переходе, но механический Phase 2
oracle обязан объединить условия в одном прогоне: leaked child держит дополнительный дубликат,
`Recv-Q=350`, новый Uvicorn на том же listener отвечает 200 и сводит queue в 0.

## Причинная цепочка

1. `/api/restart` корректно закрыл admission, дождался mutating HTTP и подготовил десять
   Codex handover. Инварианты #237 до сигнала выполнились.
2. Endpoint вернул 200 **до** необратимого результата и послал себе SIGINT. Это сегодня
   означает «workflow запланирован», а не «новое поколение принимает».
3. Uvicorn прекратил accept и закончил ASGI lifespan, но Python PID 1092440 не вышел. Поэтому
   `Restart=always` не стартовал новый main; service оставался active с процессом, который уже
   не обслуживал listener.
4. Systemd-owned listener продолжил принимать TCP handshakes. Retry браузеров/MCP превратился
   в `Recv-Q 350→361`. Queue здесь следствие правильного `FlushPending=no` при неправильной
   длительности окна без acceptor.
5. Listener fd 3 параллельно утёк в Node-лаунчеры из-за комбинации «activation FD без
   CLOEXEC в Python» + uvloop subprocess inheritance. Это **не мешало** следующему service
   принять тот же socket, но мешало действительно пересоздать порт.
6. Операторский service-only restart всё же принудил переход к PID 1191988. Вопреки первому
   диагнозу, новый PID обслужил локальные 200/302 до полного recycle. Сохранённая очередь сама
   его не парализовала.
7. Полный stop socket→service убрал activation source, освободил FD store на полном stop и
   позволил старым CLI launchers уйти/освободить leaked inode; затем новый socket стартовал с
   пустой очередью. Это объясняет чистое восстановление и разовый bind/start failure, но
   конкретный `EADDRINUSE` в system manager journal недоступен текущему пользователю, поэтому
   связь с тем самым `Input/output error` — **LIKELY, не CONFIRMED**.

## Сопоставление с #230/#237: что нельзя сломать

| Существующий инвариант | Что установил #379 | Ограничение для будущего плана |
|---|---|---|
| Socket activation держит новые MCP/HTTP connect в окно рестарта; #230 A/B 90/90 | сохранение queue работает и на 350 connect | не объявлять pending queue дефектом само по себе |
| `FlushPending=no` позволяет следующему поколению принять очередь | `FlushPending=yes` отвергает pending connections по документации systemd | нельзя использовать как «чистку» без явного отказа от availability-инварианта |
| `KillMode=process` + FD store сохраняют CLI PID/turn | полный service stop освобождает store (#230 F2) | normal restart нельзя превращать в stop socket/service: это ломает seamless handoff |
| #237 требует all-or-none prepare, точный event order, тот же CLI PID | incident handover был успешен; отказ произошёл после него | оракул обязан проверять новый acceptor/end effect, а не только `handed_over`/FD count |
| Failure до сигнала откатывает handover/admission | этот failure наступает после сигнала и сейчас endpoint уже ответил 200 | нужен отдельный наблюдаемый post-signal lifecycle, не ослабление preflight |

Источник #230 отдельно предупреждает, что socket activation не сохраняет уже принятый HTTP
handler; #237 закрепляет дренаж mutating requests. #379 это не опровергает: стенд проверяет
только ещё не принятые connections, а не in-flight side effects.[7][8]

## Findings с confidence

1. **CONFIRMED:** непосредственная причина `active, но HTTP висит` — старое поколение перестало
   accept, но не вышло; новый main не появился. Tier 1: journal, старый PID +600 с.[1]
2. **REFUTED:** «service-only не помог, потому что socket сохранил забитую queue». Tier 1:
   новый PID обслужил 200/302; локальный Uvicorn 3/3 обслужил запрос при queue=350.[1][4]
3. **CONFIRMED:** activation listener утекал в прямых uvloop children. Tier 1: incident `ss`,
   current inode census, A/B loop×CLOEXEC.[2][3][4]
4. **CONFIRMED:** leak блокирует только настоящий socket rebind до ухода последнего holder; он
   не блокирует accept новым процессом на том же socket. Tier 1: bind A/B и queue stand.[4]
5. **LIKELY:** зависание post-Uvicorn связано с неполным teardown handed-over session tasks и
   uvloop shutdown wait. Tier 1 подтверждает границу и механизм; точный blocking work item не
   снят, поэтому уверенность не повышена до CONFIRMED.[1][4][6]
6. **REFUTED:** «listener был у node и native Codex процессов». Подтверждена node-часть;
   native owners = 0 в двух снимках. Tier 1: owner lists.[2][3]

## Counter-evidence и ограничения

- Полный system-manager journal (`systemd[1]`) недоступен этому агенту: `sudo` запрещён
  `NoNewPrivileges`. Поэтому нет точного SubState и текста первого socket start failure.
- PID/thread stack не был снят во время зависания. Конкретную coroutine/thread нельзя назвать
  установленным фактом; будущий failure должен сам сохранить этот census до hard recovery.
- Два локальных 200/302 нового PID доказывают, что service-only **начал принимать**, но не
  доказывают, что desktop dashboard и каждый SSE/MCP consumer уже восстановились. Широкая
  пользовательская доступность подтверждена только после полного cycle.
- Stand использует 350 idle TCP connects, не точный mix браузер/SSE/MCP инцидента. Он отвечает
  на причинный вопрос «может ли queue этого размера сама блокировать новый Uvicorn», но не
  измеряет UX очистки старых клиентских таймаутов.
- Production owner census динамический: текущие 12 node + 1 sh — снимок, не постоянное число.
  Нагрузочный вывод опирается на inode/механизм, а не на это количество.

## Затронутые файлы, риски и edge cases будущей работы

- `app/routes/system.py`: post-signal success сейчас не наблюдается; watchdog проверяет лишь
  «мы ещё живы» через большой таймер и уже не может вернуть HTTP-ответ первоначальному caller.
- `app/main.py`: порядок lifespan shutdown; нужен bounded end effect без потери уже оплаченного
  handover.
- `app/manager.py`, `app/session.py`, `app/session_hibernate.py`: handed-over sessions обходят
  обычный stop; session-owned tasks/late finalizers не должны удерживать поколение, но нельзя
  disconnect/kill adopted CLI.
- `app/backend_codex.py` и общий subprocess seam: listener FD нельзя передавать CLI/MCP, при
  этом parent-owned stdin/stdout FD #237 обязаны остаться передаваемыми.
- `deploy/orchestra.service`, `deploy/orchestra.socket`: `KillMode=process`, FD store и
  сохранение listener — load-bearing; менять их как единый «recycle» опасно. `FlushPending`
  конфликтует с #230 по контракту.
- `tests/test_seamless_restart.py`, `tests/test_instant_restart.py`, `tests/test_hot_apply.py`:
  будущий oracle должен различать «Uvicorn написал Finished» и «старый PID реально исчез,
  новый acceptor ответил», а FD oracle — сверять inode/тип, не наличие номера 3. Отдельный
  named oracle обязан доказать, что cleanup supervisor-owned session tasks не закрывает adopted
  stdin/stdout: CLI PID/starttime и active turn остаются теми же, terminal event и side effect
  доезжают ровно один раз после teardown старого поколения.
- Edge cases: несколько leaked holder; late-created task во время cancellation; default-executor
  syscall, который не возвращается; очередь с SSE/partial HTTP; отказ нового поколения после
  успешного handover; полный stop освобождает FD store и принципиально не является seamless.

## Вывод Phase 1

Инцидент был не «забитым socket», а **незавершившейся сменой поколения**: старый Uvicorn уже
закрыл acceptor, старый Python всё ещё жил, поэтому systemd не поставил нового читателя на
нормально сохраняемый listener. `Recv-Q` лишь сделал отсутствие acceptor видимым.

Независимый второй дефект реален: uvloop раздаёт не-CLOEXEC activation fd прямым детям.
Он не объясняет service-only hang, зато делает аварийное пересоздание socket зависимым от ухода
всех holder и расширяет blast radius. Следующая фаза должна закрывать эти seams раздельно и
сохранить #230/#237; решения Phase 2 здесь намеренно не выбраны.

## Review decision gate

- Artifact/consumers: `research.md`, локальный `socket_stand.py`, будущие lifecycle/socket/CLI
  consumers перечислены выше.
- Author metadata: `gpt-5.6-sol`, Codex runtime, full-cycle role (DB `sessions.id` текущей
  сессии).
- AC: причинная цепочка объясняет все наблюдения; queue и FD наследование воспроизводятся без
  live mutations; #230/#237 ограничения названы явно.
- Named check: production Python запускает `docs/tasks/379/socket_stand.py`; 3/3 — queue 350,
  fresh 200, queue 0; uvloop-only FD inheritance; rebind `EADDRINUSE` только при leaked holder.
- Risk floor: shared process/session/lifecycle + socket/queue; strong oracle отсутствует для
  точного postmortem blocking task. Route: targeted Sol research review.

## Проверки артефакта

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python \
  docs/tasks/379/socket_stand.py
→ queue 350→0, fresh HTTP/1.1 200 OK; uvloop inherited only inheritable listener;
  leaked holder → EADDRINUSE; final verification latency 929.1 ms

timeout 60s uv run python -m pytest -q tests/test_seamless_restart.py
→ 16 passed in 14.43s, exit 0

systemd-analyze verify deploy/orchestra.service deploy/orchestra.socket
→ exit 0 (printed only an unrelated existing xray.service warning)

python3 -m py_compile docs/tasks/379/socket_stand.py
git diff --check
→ exit 0
```

`uv.lock` после прогонов не изменён; `git status --short` содержит только артефакты #379 и
append в `docs/kb/repo-ops.md`.

## Независимое второе мнение

Route: targeted Sol (`gpt-5.6-sol`), один раунд; артефакт
`docs/tasks/379/codex-review-research.md`.[13]

Reviewer независимо запустил тот же stand и получил queue `350→0`, свежий 200,
uvloop-only inheritance, `EADDRINUSE` до ухода holder и executor wait 504.1 мс. Verdict:
**Completed — no blocking causal hole**. Две suggestions приняты выше: executor probe назван
возможным механизмом, а не идентификацией production waiter; для Phase 2 записаны combined
queue+holder oracle и запрет cleanup закрывать adopted pipes/менять CLI lifecycle. Второй раунд
не запускался: blocking findings нет, suggestions сами по себе его не открывают.

## Источники

1. `journalctl -u orchestra.service --since ... --until ...` — production timeline,
   2026-08-23; direct measurement, tier 1.
2. `/home/kesha/orchestra/data/orchestra.db` в `mode=ro`, logs session
   `75285d62-...`: incident `ss`, recovery transcript; direct measurement, tier 1.
3. `/proc/net/tcp*` + `/proc/<pid>/fd{,info}` inode census на живом сервисе без сигналов;
   direct measurement, tier 1.
4. `docs/tasks/379/socket_stand.py`, три запуска production Python; direct measurement, tier 1.
5. Production interpreter metadata: Python 3.12.3, Uvicorn 0.48.0, uvloop 0.22.1;
   direct measurement, tier 1.
6. Текущий код: `app/routes/system.py`, `app/main.py`, `app/manager.py`, `app/session.py`,
   `app/session_hibernate.py`, `app/fdstore.py`; primary source, tier 2.
7. `docs/tasks/230/research.md` и `report.md`: socket activation, FD store, stop boundary;
   project primary measurements, tier 1.
8. `docs/tasks/237/research.md`, `plan.md`, `report.md`: transactional Codex handover invariants;
   project primary measurements, tier 1.
9. systemd `systemd.socket` primary manual source, `FlushPending=`:
   https://github.com/systemd/systemd/blob/main/man/systemd.socket.xml
10. systemd `systemd.kill` primary manual source, `KillMode=process`:
    https://github.com/systemd/systemd/blob/main/man/systemd.kill.xml
11. Uvicorn 0.48.0 primary source, `Config.bind_socket()`:
    https://github.com/encode/uvicorn/blob/0.48.0/uvicorn/config.py
12. systemd primary API/source, `sd_listen_fds()` sets `FD_CLOEXEC`:
    https://github.com/systemd/systemd/blob/main/src/systemd/sd-daemon.h and
    https://github.com/systemd/systemd/blob/main/src/libsystemd/sd-daemon/sd-daemon.c
13. `docs/tasks/379/codex-review-research.md` — targeted Sol adversarial review; completed,
    no blockers, stand rerun attached.
