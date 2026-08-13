# #237 — независимое ревью реализации «первого поезда». Вердикт: CHANGES REQUESTED

**Ревьюер — Opus, не Codex.** Раунд Codex платформа отклонила до старта
(`weekly_quota_blocked: Codex weekly quota is 97% (threshold 95%)`, сброс 20.08), дословный
ответ — в `docs/tasks/237/codex-review-impl.md`. Оркестратор заменил внешний раунд на ревью
другой моделью того же класса. Это НЕ кросс-рантаймное ревью: ревьюер и часть контура
постановки — одна модель, петля усиления разорвана только по роли (исполнитель — Sol), не по
рантайму.

Предмет: `adhoc-1786604282-19/feat-hot-reload` против `main`, точка ветвления `0500f99b`,
коммиты `9fb1fc47` (T1), `2f1b438b` (T2), `a11f7671` (T3), `f902e004` (T4).

**Как проверял.** Дерево ветки выгружено `git archive` в `/tmp/rev237-<pid>` (вне репозитория,
чтобы ничего не править и не трогать worktree автора), прогоны — репозиторным
`.venv/bin/python`. Живой сервис не трогал, ветку не чекаутил, код не правил. Полный сьют не
гонял — принял прогон автора (`2787 passed, 42 skipped`, exit 0). Три дефекта ниже
воспроизведены пробами, не выведены рассуждением; исходники проб — в приложении.

---

## Блокеры

### B1. Отказавшая передача оставляет агента ЖИВЫМ, но ГЛУХИМ навсегда

`app/manager.py:2249` (сброс флага) + `app/manager.py:2306` (гейт возобновления по этому же
флагу).

**Сценарий отказа.** Codex-агент занят ходом. Оператор жмёт restart. `_do_restart_service` →
`prepare_restart_handover([...])` → `_hand_over_backend(session)`:

1. `quiesce_for_handover()` проходит: `_handover_quiescing = True`, читатель отменён, пайп
   поставлен на `pause_reading()`.
2. `fdstore.store_fds(...)` падает — store исчерпан (`FileDescriptorStoreMax=256`), либо
   systemd отвечает `OSError`, либо падает `save_handover_state` (заблокированная SQLite).
3. Ветка `except` (`manager.py:2240-2258`) откатывает имена и зовёт `abort()`, а
   `abort_handover()` (`backend_jsonrpc.py:209-217`) выставляет `_handover_quiescing = False`
   и **стирает `_quiesced_prefix`**.
4. `prepare_restart_handover` зовёт `_rollback_handover(prepared, also_resume=[session])`.
5. `_rollback_handover` пропускает сессию: `if resume is None or not
   getattr(backend, "_handover_quiescing", False): continue`. Флаг уже снят шагом 3.

Итог: рестарт отменён, CLI жив, `is_alive` True, `_reader_task is None`, транспорт на паузе.
Всё, что CLI пишет дальше, оседает в пайпе; `_process/exited` не придёт никогда (флаг снят, но
читателя нет вовсе); следующий `_request` («turn/start») ждёт future без таймаута — агент
висит молча. Ровно тот исход, против которого заведена задача.

**Проба (приложение A).** Настоящий `CodexBackend` на настоящих пайпах, `store_fds` бросает:

```
reader_task: None      quiescing: False      queue size after new frame: 0
AssertionError: agent went deaf: the frame its CLI sent after the aborted restart never arrived
```

**Оракул это НЕ ловит, и вот почему.** `tests/test_seamless_restart.py:590`
(`test_t3_fleet_handover_rolls_back_an_earlier_success`) подменяет `_hand_over_backend`
моком и РУКАМИ выставляет `second_backend._handover_quiescing = True` — состояние, которое
настоящий код на этом пути не производит никогда (он его как раз снимает). Оракул зелен на
двойнике, противоречащем реализации. Это класс «тест зовёт примитив вместо пути прода» из
`CLAUDE.md`.

**Мутация, которая различает** (моя, не из таблицы автора). Отключить `abort()` в ветке отказа
(`abort is not None` → `abort is not None and False`):

```
маркер до: 1
tests/test_seamless_restart.py + проба → 16 passed     # 15 оракулов ЗЕЛЕНЫ, проба ПОЗЕЛЕНЕЛА
маркер после отката: 0   (+ touch)
повтор после отката → 1 failed, 15 passed              # проба снова красная
```

То есть: строка не покрыта ни одним из 15 замороженных оракулов, и она же — точка дефекта.
Прямое отключение `abort()` фиксом не является: на пути `shutdown_all` флаг снимать НАДО,
иначе настоящая смерть станет беззвучной (это и было причиной появления `abort_handover`).
Правильно — разорвать двойное назначение флага: `_rollback_handover` должен решать по факту
«эта сессия была квиесцирована», а не по флагу (например, `_hand_over_backend` возвращает
кортеж `(handed, was_quiesced)` или принимает `resume_on_failure=True` от транзакционного
вызывающего).

Severity: **blocking** (потеря агента: живой, неубиваемый штатно, не отвечающий).

---

### B2. Сторож на 120 с открывает ОБА гейта посреди рестарта, который ждёт до 900 с

`app/routes/system.py:1760` (`_ADMISSION_WATCHDOG_S = 120.0`) против
`app/routes/system.py:1702` (`_DRAIN_DEADLINE_S = 900`); сторож заводится в
`restart_server` (`system.py:1905`) и **никогда не отменяется** — в файле нет ни одного
`.cancel()`, привязки к попытке рестарта тоже нет.

**Сценарий отказа.** T3 добавил ПОД закрытые гейты новое ожидание длиной до 900 с
(цикл `_blocking_runtimes()` — живой ход Claude/Grok блокирует рестарт). Сторож же по-прежнему
рассчитан на старую границу: его комментарий дословно — «> the 90.2s slowest mutating call, so
no false reopen», то есть он обосновывает 120 с через дренаж мутирующего HTTP и ничего не знает
про 900 с. Как только дренаж ходов длится дольше ~120 с (замер #220: p50 1.2 мин, но в 20%
случаев не сходится и за 15 мин — то есть случай штатный, а не экзотический), сторож
срабатывает и делает `_abort_restart(...)`: `rollback_restart_handover()`, `end_drain()`,
`open_mutating_admission()`. При этом `_do_restart_service` продолжает работать как ни в чём не
бывало и в конце ШЛЁТ СИГНАЛ.

**Проба (приложение B),** `_ADMISSION_WATCHDOG_S=0.3`, `_DRAIN_DEADLINE_S=5`, занятый
claude-ход, который освобождается позже:

```
early http allowed: False
mid-restart: draining = False   http allowed = True   kill called = False
after: kill called = True
```

То есть между срабатыванием сторожа и сигналом обе двери открыты настежь: принимаются новые
ходы и новые мутирующие вызовы, а потом приходит SIGINT. Заявленный инвариант T3 («оба гейта
закрыты синхронно от preflight до сигнала») на этом отрезке не держится вовсе.

Два следствия, оба плохие:

1. **Рестарт становится недостижим.** Гейт ходов открылся → агенты (в первую очередь
   Claude-оркестратор) начинают ходы → `_blocking_runtimes()` больше не пустеет → цикл
   досиживает до 900 с → `blocked` непуст → `_abort_restart` → отказ. Чем дольше ждём, тем
   меньше шансов дождаться: сторож кормит то, чего ждёт цикл.
2. **Узкое окно потери.** Между поздней проверкой (`late or inflight_mutating_count()`,
   `system.py:1863`) и `os.kill` (`system.py:1892`) лежит `_record_restart_outcome` (запись в
   SQLite). Мутирующий вызов, допущенный в это окно, режется с неизвестным исходом — ровно то,
   ради чего существует preflight. А `turn/steer`, допущенный после квиесцирования флота,
   уходит в CLI, чей ответ читать уже некому: новое поколение получит фрейм с неизвестным id и
   выбросит его.
3. **Гонка с откатом.** Если сторож попадёт в промежуток между присвоением
   `self._prepared_restart` (`manager.py:2284`) и сигналом, он снимет дескрипторы из store и
   вернёт читателей — а сигнал всё равно уйдёт. Окно миллисекундное, но при второй попытке
   рестарта сторож ПЕРВОЙ попытки жив и целится в чужую транзакцию.

Оракул `test_guard_watchdog_gives_a_prepared_fleet_its_readers_back`
(`tests/test_hot_apply.py:456`) проверяет только, что сторож зовёт откат; безусловность
сторожа и его несвязанность с попыткой не проверяет никто.

Минимально: сторож обязан отменяться по завершении `_restart_service_after_response`
(и по факту отказа), а его бюджет — быть не меньше `_DRAIN_DEADLINE_S` плюс время подготовки
флота, либо считаться от момента, когда рестарт реально дошёл до точки невозврата.

Severity: **blocking** (невозможность рестарта + узкое окно потери работы).

---

### B3. Откат передачи скармливает перенесённые события в НЕВЕРНЫЙ конец буфера — кадры уничтожаются

`app/backend_jsonrpc.py:201` (`reader.feed_data(prefix)` в
`resume_after_aborted_handover`), в паре с `app/backend_jsonrpc.py:182`
(`self._quiesced_prefix = b"".join(frames)`).

**Сценарий отказа.** На момент квиесцирования у транспорта одновременно бывают:
уже разобранные события в очереди (становятся `_quiesced_prefix`) и **хвост неполного кадра**
в `StreamReader._buffer`. Разобранные события пришли РАНЬШЕ этих байт. При усыновлении порядок
восстанавливается верно: `adopt_pipes` кладёт `leftover = prefix + buffer` в ПУСТОЙ ридер. А на
откате ридер тот же самый, и `feed_data(prefix)` дописывает префикс ПОСЛЕ недописанного кадра.
Поток склеивается в мусор.

**Проба (приложение C):** одно целое событие в очереди + половина следующего кадра в буфере,
`quiesce(drain_budget_s=0)`, затем `resume_after_aborted_handover()`, затем дописан хвост:

```
prefix: b'{"method": "item/completed", "params": {"seq": 1}}\n'
buffer at quiesce: b'{"method": "turn/complete'
delivered after resume: []
WARNING app.backend_codex:925 Codex app-server emitted invalid JSONL
WARNING app.backend_codex:925 Codex app-server emitted invalid JSONL
```

Потеряны ОБА события, включая `turn/completed`, и потеряны тихо — `_read_stdout` на невалидном
JSONL делает `continue` (`backend_codex.py:925`). Агент досидит до heartbeat-таймаута с ходом,
который на самом деле завершился. Это прямое нарушение zero-loss именно на аварийном пути,
который B2 делает частым.

Оракул `test_t3_aborted_handover_replays_prefix_and_resumes_reader`
(`tests/test_seamless_restart.py:621`) зелен, потому что проверяет случай с ПУСТЫМ буфером —
достаточное условие для замера «префикс не потерян», недостаточное для «порядок сохранён».

Фикс, который не требует приватного API: на откате возвращать разобранные события ОБРАТНО В
ОЧЕРЕДЬ `_notifications` (в исходном порядке, до возобновления чтения), а не перекодировать их
в байты. Байтовая форма нужна только для передачи через БД следующему поколению.

Severity: **blocking** (тихая потеря терминального события хода).

---

## Suggestions

### S1. Оракул отката построен на двойнике, противоречащем реализации
`tests/test_seamless_restart.py:590`. Подробности — в B1. Пока двойник сам выставляет
`_handover_quiescing = True`, он не отличит исправную реализацию от той, где `abort()`
съедает возобновление. Достаточно строить тест на настоящем `_hand_over_backend`, как это
делает проба A.

### S2. Там, где systemd-scope доступен, «первый поезд» выключается целиком, и рестарт встаёт
`app/backend_codex.py:509-517`. При `scope_ok=True` спавн идёт через `systemd-run --scope`,
дескрипторы остаются `PIPE`, `fd_in`/`fd_out` — `None`. Дальше цепочка не деградирует в
«старое поведение», а ЖЁСТКО ЛОМАЕТ рестарт: `_hand_over_backend` вернёт False →
`prepare_restart_handover` вернёт `ok: False` → `_abort_restart`. То есть на такой машине
`/api/restart` не сможет отработать НИКОГДА, пока хоть один Codex-агент занят (а до T3 он бы
просто отработал, отрезав ход).

На этом VPS проверено — путь неактивен, так что здесь дефект спящий:
```
loginctl show-user 1001 -p Linger --value → Failed to get user: ... not logged in or lingering
ls /run/user/1001/bus                     → No such file or directory
```
`scope_ok` считается один раз и кешируется (`_scope_support_cache`), warning печатается на
каждый коннект — деградация громкая. Но последствие для рестарта в отчёте не названо, а
ноутбучный контур (`docs/HANDOFF-from-laptop.md`) — ровно та машина, где linger обычно есть.
Просьба: либо явная запись в `report.md`, либо трактовать «занятый непередаваемый Codex» так же,
как Claude/Grok, — то есть блокировать рестарт ПО ИМЕНИ агента, а не отказом транзакции без
объяснения.

### S3. T4 репетирует НЕ тот путь, который реализует T3
`scripts/rehearse-seamless-restart.py:39,118` — разрушительный прогон делает
`sudo systemctl restart orchestra-237.service`, то есть SIGTERM → lifespan → `shutdown_all` →
`_hand_over_backend`. Это путь #230. Путь #237 T3 (`/api/restart` → оба гейта →
`prepare_restart_handover` → `SIGINT`) единственной живой репетицией не покрывается вовсе, и
именно его новые швы (транзакция, `_prepared_restart`, поздняя проверка, откат) остаются
проверенными только двойниками — что автор честно перечисляет в п.3 своего списка
непроверенного, но раннер этот пробел не закрывает.

Там же — противоречие в тексте: раздел `## Operational limitation` в `report.md` утверждает, что
при ручном `systemctl restart` «активные Codex-ходы рвутся, потому что дескрипторы никто не
передал». Это неверно: `shutdown_all` передаёт их, и сам раннер это проверяет
(`descriptors_were_stored`, `cli_survived`, `terminal_event_delivered`). Настоящая цена ручного
рестарта другая и меньше: нет дренажа мутирующего HTTP, нет атомарности и поздней проверки, а
агент с in-flight запросом будет остановлен по-старому. Одно из двух утверждений надо поправить,
иначе оператор будет принимать решение по неверной модели.

### S4. Частичный отказ `attach_owned_pipes` закрывает чужой дескриптор
`app/backend_codex.py:600-606` в паре с `app/backend_jsonrpc.py:259-272`. Если
`connect_read_pipe` уже отдал `fd_out` транспорту, а `connect_write_pipe` следом упал (или
`connect()` отменён между ними), то `_owned_*` не выставлены, а `except BaseException` в
`connect()` делает `os.close(our_stdout)` — по дескриптору, которым владеет живой read-транспорт.
Дальше номер переиспользуется (автор сам замерил, что uvloop переиспользует номера немедленно), и
транспорт читает чужой файл. Узко и маловероятно, но лечится одной строкой: выставлять
`self._owned_read_transport`/`_owned_fds` сразу после `connect_read_pipe`, а очистку в
`connect()` вести только через `teardown_owned_pipes()`.

### S5. Инвентарь перед первой активацией — только текст
`report.md`, раздел `## First activation`, требует снять `(pid, starttime, argv)` каждого живого
CLI ДО сигнала и после старта сверить, что все reaped. Требование верное (и трактовка «совпавшая
живая identity = провал активации» тоже верная — после #258 неопознанный сирота действительно не
убивается, `manager.py:2435-2439` сигналит только по доказанной identity). Но в коде и в
`scripts/` этой процедуры нет: снимать инвентарь оператору предлагается руками, а вручную
собранный список — единственный источник для последующей сверки. Прошу одну команду в отчёте
(`ps -eo pid,lstart,args` + фильтр), чтобы шаг был воспроизводим, а не описан.

---

## Что проверено и претензий не имеет

- **T1 на настоящем uvloop и настоящем процессе** (приложение D — не двойник, как в оракуле):
  пайпы созданы правильными сторонами (`us→CLI` write-конец у нас), после спавна родительские
  копии детских концов остаются открытыми и штатно закрываются вручную (`os.close` не падает —
  uvloop их не закрывает сам), round-trip через `_in`/`_out` работает, `teardown_owned_pipes`
  закрывает ОБА наших конца, и ребёнок видит EOF и выходит с кодом 0. Висящих детских концов
  нет; «закрытие планируется, но не происходит» — не подтвердилось, `await asyncio.sleep(0)`
  своё дело делает.
- **Гейт `_handover_quiescing` над `proc.wait()`** (`backend_codex.py:965-990`): логика «вся
  история про смерть процесса под одним флагом» верна, и оракул на живом процессе её держит.
- **T2, имена дескрипторов.** `_check_fdname` + `fd_store_name`/`parse_fd_store_name` — один
  владелец формата, оба парсера ходят через него. Проверено по живой БД (read-only): все 211
  session id — UUID, ни одного символа вне `[A-Za-z0-9_.-]`, ни одной точки внутри id, то есть
  трёхчастный разбор по `.` однозначен.
- **T2, `adoption_filter`.** Полная унаследованная пара делает строку resumable даже при
  `session_id IS NULL`; параметры уходят через placeholders, инъекции нет. Взаимодействие с
  подметалкой сирот корректное: загруженная сессия перестаёт выглядеть сиротой
  (`manager.py:2037-2046`).
- **Фикстуры-ренеймы.** Проверил механически: в `test_fd_adopt.py`, `test_fdstore.py`,
  `test_orphan_pid_identity.py`, `test_system_restart.py` все изменённые строки, кроме двух,
  содержат имя дескриптора. Две оставшиеся — `endswith(":stdout")→endswith(".stdout")` (тот же
  ренейм) и починка изоляции фикстуры `test_system_restart.py` (возврат приёма мутирующего
  HTTP). Скрытых правок поведения нет.
- **Переписанные контракты #220 — переписаны, а не подогнаны.** В
  `test_t3_drain_deadline_is_unconditional_and_names_the_blocking_turns` исход инвертирован
  осознанно и назван в docstring (`kill` не зовётся вовсе; `cut_turns == 0` при непустом
  `cut_names`). В двух других тестах проверяемое свойство прежнее (запись до сигнала; сбой
  учёта не отменяет сигнал), сменилась только фикстура — занятая сессия на свободную, иначе
  сигнала не будет вовсе и проверять станет нечего. Это законная адаптация, не ослабление:
  подгонкой было бы сохранить старый ассерт, ослабив его до `>= 0`.
- **T4 как артефакт.** Юнит захардкожен, CLI-поверхности для смены цели нет, `--dry-run` и
  `--execute` строят команду одним билдером, `--execute` без `--agent/--marker/--expect` честно
  докладывает `"measured": false` вместо того, чтобы выдать рестарт за доказательство.

## Не проверено (законный результат, не одобрение)

- Настоящий `systemctl restart` с настоящим Codex: репетиция не запускалась (мне запрещено, и
  правильно). SCM_RIGHTS, `NFileDescriptorStore > 0` и выживание CLI подтверждены только
  замерами #230, приведёнными автором.
- Поведение флота из нескольких Codex-сессий под нагрузкой: у меня, как и у автора, только
  двойники.
- Симметричность `pause_reading`/`resume_reading` на потоке (а не на одном кадре).
- Полный сьют: принят прогон автора, свой не гонял (глобальный лок не брал).

## Мелочь, не влияющая на вердикт

`tests/test_hot_apply.py:406` — дублирующийся `from app.session import AgentStatus` внутри
функции, где импорт уже есть строкой выше.

---

# ВЕРДИКТ: CHANGES REQUESTED

Блокеры, каждый воспроизведён пробой:

1. **B1** `app/manager.py:2249` + `:2306` — отказ передачи оставляет агента живым и глухим
   навсегда; ни один из 15 замороженных оракулов эту строку не покрывает (доказано мутацией).
2. **B2** `app/routes/system.py:1760` против `:1702` — неотменяемый сторож на 120 с открывает
   оба гейта посреди рестарта, который вправе ждать 900 с; рестарт перестаёт достигаться, плюс
   окно потери мутирующего вызова и `turn/steer` перед самым сигналом.
3. **B3** `app/backend_jsonrpc.py:201` — на откате перенесённые события дописываются ПОСЛЕ
   неполного кадра; оба кадра уничтожаются молча, включая `turn/completed`.

Направление правок общее и небольшое: B1 — не смешивать «снять флаг» и «отдать читателя»;
B2 — связать сторожа с попыткой рестарта и с её реальным бюджетом; B3 — возвращать разобранные
события в очередь, а не в байтовый поток.

Всё остальное, включая самое опасное место (T1 под настоящим uvloop с настоящим процессом),
проверку выдержало.

---

# Приложение. Пробы

Прогон: дерево ветки выгружено `git archive <branch> | tar -x -C /tmp/rev237-<pid>`, команда —
`/home/kesha/orchestra/.venv/bin/python -m pytest <файл> -q -s` из этого каталога.

## A. Глухой агент после отказавшей передачи (B1)

```python
@pytest.mark.asyncio
async def test_probe_store_failure_leaves_backend_deaf(monkeypatch, tmp_path):
    from app.backend_codex import CodexBackend
    from app.manager import SessionManager
    from types import SimpleNamespace

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp")
    try:
        await backend.adopt(cli_in_w, cli_out_r, "thread-p", "turn-p")
        os.write(cli_out_w, (json.dumps({"method": "item/completed",
                                         "params": {"seq": 1}}) + "\n").encode())
        await _wait_until(lambda: backend._notifications.qsize() == 1,
                          message="reader never entered its body")
        backend._notifications.get_nowait()   # очередь пуста: префиксу неоткуда взяться

        session = SimpleNamespace(id="probe-237", name="probe-237",
                                  backend_type="codex", _backend=backend)
        mgr = SessionManager()

        def boom(name, fds):
            raise RuntimeError("systemd refused: store is full")

        monkeypatch.setattr("app.fdstore.store_fds", boom)
        monkeypatch.setattr("app.fdstore.remove_fds", lambda name: None)

        result = await mgr.prepare_restart_handover([session])
        assert result["ok"] is False

        os.write(cli_out_w, (json.dumps({"method": "turn/completed",
                                         "params": {"seq": 2}}) + "\n").encode())
        await asyncio.sleep(0.4)
        assert backend._notifications.qsize() == 1, "agent went deaf"
    finally:
        backend._disconnecting = True
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass
```

Вывод: `reader_task: None`, `quiescing: False`, `queue size after new frame: 0`, красный.

## B. Сторож открывает гейты посреди рестарта (B2)

```python
@pytest.mark.asyncio
async def test_probe_watchdog_reopens_gates_mid_restart(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    busy = {"v": True}

    class _Sess:
        id = "c"; name = "c"; backend_type = "claude"
        @property
        def is_busy(self):
            return busy["v"]

    kill = MagicMock()
    monkeypatch.setattr(system, "_drain_sessions", lambda: [_Sess()])
    monkeypatch.setattr(system, "_DRAIN_DEADLINE_S", 5.0)
    monkeypatch.setattr(system, "_ADMISSION_WATCHDOG_S", 0.3)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr(manager, "prepare_restart_handover",
                        AsyncMock(return_value={"ok": True, "handed_over": []}),
                        raising=False)

    await system.restart_server()
    await asyncio.sleep(0.1)
    assert manager.draining is True
    await asyncio.sleep(0.6)                     # сторож отработал, рестарт ещё ждёт
    mid_draining = manager.draining
    mid_http = app_main.mutating_admission_verdict(
        "POST", "/api/sessions/worker/send")["allowed"]
    busy["v"] = False
    await asyncio.sleep(1.5)                     # ход кончился → сигнал уходит
    assert mid_draining is True and mid_http is False
```

Вывод: `mid-restart: draining = False  http allowed = True  kill called = False`, затем
`after: kill called = True`. Красный.

## C. Порядок префикса на откате (B3)

Ключевая часть: одно целое событие уходит в очередь, половина следующего кадра — в
`StreamReader._buffer`, затем `quiesce_for_handover(drain_budget_s=0)` (префикс непуст),
`resume_after_aborted_handover()`, дописан хвост кадра. Ожидание `[1, 2]`, факт — `[]` и два
`invalid JSONL`.

## D. T1 на настоящем uvloop и настоящем subprocess (претензий нет)

```python
t = T()                                        # голый JsonRpcStdioTransport
child_in, child_out, our_in, our_out = t.new_child_pipes()
proc = await asyncio.create_subprocess_exec(
    sys.executable, "-c", CHILD,               # ребёнок: upper() построчно
    stdin=child_in, stdout=child_out, stderr=asyncio.subprocess.PIPE, limit=1024*1024)
await t.attach_owned_pipes(our_in, our_out, limit=1024*1024)
os.close(child_in); os.close(child_out)        # не падает: uvloop их не закрыл сам
t._in.write(b'{"hello": "world"}\n'); await t._in.drain()
assert await t._out.readline() == b'{"HELLO": "WORLD"}\n'
await t.teardown_owned_pipes()
assert await asyncio.wait_for(proc.wait(), timeout=5) == 0   # ребёнок увидел EOF
```

Вывод:
```
pipes: 13 16 14 15
after spawn: child ends still open in parent? True True
child ends closed by us without error: True
round trip: b'{"HELLO": "WORLD"}\n'
owned fds still open after teardown? False False
child exited with 0
PROBE OK
```

## Мутация к B1 (три клаузы + маркер до и после)

```
cp app/manager.py app/manager.py.bak
# 'abort is not None' -> 'abort is not None and False'
grep -c "abort is not None and False" app/manager.py   →  1     (до прогона)
pytest tests/test_seamless_restart.py + проба A        →  16 passed
mv app/manager.py.bak app/manager.py && touch app/manager.py
grep -c "abort is not None and False" app/manager.py   →  0     (после отката)
pytest tests/test_seamless_restart.py + проба A        →  1 failed, 15 passed
```
