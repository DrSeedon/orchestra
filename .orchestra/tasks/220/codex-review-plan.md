## Summary

План правильно ограничивает scope и верно ставит drain до `SIGINT`. Однако спецификация T2 теряет исходные сообщения, T3/T4 не определяет способ доставки результата пользователю, а admission gate недостаточно атомарен относительно старта хода.

## Findings

blocking: `docs/tasks/220/plan.md:57` — `enqueue_fact()` хранит только факт недоставки, а `_attach_pending_facts()` добавляет этот факт к какому-то будущему сообщению; исходное сообщение не переигрывается и само не запускает следующий ход. Поэтому команда вроде «исправь баг» будет фактически потеряна, вопреки названию T2 и AC «не теряется» → нужна durable-очередь реальных входящих сообщений с автоматической доставкой после рестарта либо честный контракт отказа, при котором отправитель получает ошибку и повторяет запрос; `enqueue_fact` для этого контракта недостаточен.

blocking: `docs/tasks/220/plan.md:79` — проверка `draining` описана лишь как условие «до `IDLE → RUNNING`», но `send()` удерживает собственный `_lifecycle_lock`, тогда как `begin_drain()` меняет состояние `SessionManager`; без общей атомарной границы возможен interleaving: `send()` видит `draining=False`, затем `begin_drain()` закрывает gate и начинает опрос, после чего `send()` выставляет `RUNNING` → специфицировать синхронизацию: gate должен закрыться атомарно со всеми разрешениями на старт, а тест обязан воспроизвести паузу между admission-check и присвоением `RUNNING`.

blocking: `docs/tasks/220/plan.md:81` — результат `{"cut_turns": N}` возвращается из фоновой `_restart_service_after_response()`, но `restart_server()` уже вернул клиенту `{"ok": True, "scheduled": True}` и callback фоновой задачи результат не читает. После `SIGINT` процесс исчезает, поэтому T4 физически не может показать этот результат ни в HTTP-ответе, ни в TG → определить сохраняемый до сигнала канал результата: например, request/job ID + durable status, отдельное уведомление до `SIGINT` либо синхронное ожидание drain с последующим планированием сигнала после отправки ответа.

blocking: `docs/tasks/220/plan.md:100` — текущий TG `/restart` напрямую запускает `sudo systemctl restart orchestra`, полностью обходя `/api/restart` и будущий drain; формулировка «обе точки ходят через дренаж» не задаёт новый конкретный маршрут, а ручной oracle не защищает от сохранения bypass → явно потребовать заменить прямой `subprocess.Popen` на единственный серверный restart workflow и добавить тест, что TG больше не вызывает `systemctl` напрямую.

suggestion: `tests/test_hot_apply.py:102` — T2-тест проверяет только факт любого вызова `enqueue_fact`; он не проверяет точный payload, dedupe key, последующую доставку исходной команды или отсутствие старта в гонке с `begin_drain()` → AC должен включать restart/resume-сценарий и подтверждать, что агент получает именно исходное сообщение ровно один раз.

suggestion: `docs/tasks/220/plan.md:94` — требование сохранить зелёным `tests/test_system_restart.py` противоречит обязательной смене поведения: существующий тест требует ровно один `sleep(0.5)`, тогда как T3 вводит polling и deadline; «назвать в отчёте» не является AC → заранее определить новый контракт и обновить тест на поведение «ответ отправлен до ожидания, сигнал после drain/deadline», не сохраняя дословный старый sleep.

suggestion: `docs/tasks/220/plan.md:32` — описание T1 неполно относительно `_load_from_db`: текущая сборка включает legacy-восстановление overlay, `_ownership_prompt`, различие orchestrator/worker, форматирование с `branch`/именем оркестратора и обработку `prompt_overlay is None`. Сигнатура `assemble_prompt(session_or_row)` также оставляет две неявные формы входа → перечислить обязательные ветви и задать один явный тип/контракт результата, иначе «байт-в-байт эквивалентно» трудно реализовать и проверить.

suggestion: `docs/tasks/220/plan.md:139` — заявленный порядок безопасен: drain выполняется до `os.kill(SIGINT)`, а только после сигнала lifespan последовательно вызывает `shutdown_merge_operations()` на `app/main.py:114`, `bg_manager.shutdown()` на строке 126 и `manager.shutdown_all()` на строке 127. Но это должно стать явным AC; также после закрытия gate фоновые producer’ы остаются живы до своих shutdown, поэтому их новые IDLE-сообщения должны попадать в корректную durable-очередь, а не в нынешний `enqueue_fact`.

suggestion: `docs/tasks/220/plan.md:101` — изменение `app/static/js/app.js` ради самого маршрута через drain избыточно: кнопка уже вызывает `/api/restart`, поэтому T3 автоматически меняет её restart path. JS нужен только если будет определён новый observable status/result protocol → отделить обязательную маршрутизацию от опционального отображения прогресса и добавить проверяемый AC для последнего.

## Verdict

Есть blocking findings. План нельзя передавать в реализацию до исправления durable-delivery контракта T2, атомарности admission gate и канала результата T3/T4. Порядок drain → `SIGINT` → lifespan shutdown сам по себе безопасен.

## Round (2026-08-12T10:10:46Z)

## Round 2

### Re-review status

- FIXED — B1: план больше не выдаёт `enqueue_fact` за очередь сообщений; внешний `send()` теперь имеет громкий отказ.
- FIXED — B2: синхронный `begin_drain()` и отсутствие `await` между последней проверкой gate и `RUNNING` закрывают гонку в кооперативном event loop. Пока `_lifecycle_lock` удерживается, другого interleaving без `await` нет.
- STILL BROKEN — B3: результат теперь сохраняется до `SIGINT`, но план всё ещё не определяет конкретный механизм, которым новый процесс доставит его в TG/dashboard; особенно не объяснено, как текущий TG handler после уничтожения процесса покажет `waited_s/cut_turns`.
- FIXED — B4: прямой `systemctl` удаляется, задан единый restart workflow и появился тест против bypass.
- FIXED — прежнее противоречие с `tests/test_system_restart.py`: тест теперь явно должен быть переписан под новый контракт.
- FIXED — T1 теперь перечисляет существенные ветви сборки и задаёт явную keyword-only сигнатуру.
- FIXED — `app/static/js/app.js` убран из необязательного scope.
- FIXED — порядок shutdown проверен: drain → `SIGINT` → `shutdown_merge_operations()` / `bg_manager.shutdown()` / `manager.shutdown_all()` безопасен.

### New findings

blocking: `docs/tasks/220/plan.md:T2 contract — утверждение «отправитель у нас всегда живой и способен повторить» неверно для внутренних вызовов `AgentSession.send()`: `_rate_limit_retry()` (`app/session.py:2182`), `_retry_after_server_error()` (`:2200`) и `_auto_continue()` (`:2215`) ловят общий `Exception`, только пишут warning и прекращают повтор; auto-report в `app/manager.py:1599` превращается лишь в факт недоставки. Это не crash loop, но это silent loss автоматического continuation/retry → отдельно специфицировать поведение `DrainingRefused` для каждого внутреннего caller: не начинать ход и не считать продолжение доставленным; сохранить намерение либо явно признать его срезанным в restart outcome.

blocking: `tests/test_hot_apply.py:303` — T4-тест ложнозелёный: `restart_server` является `async def`, но заменён обычным `MagicMock`. Неверный handler, который просто вызывает `restart_server()` без `await`, ничего не запустит в production, однако тест увидит `drained.called` и пройдёт → использовать `AsyncMock`, требовать `assert_awaited_once_with()` и проверять, что handler не завершается с необработанной ошибкой.

suggestion: `docs/tasks/220/plan.md:T3 result channel — фраза «после рестарта его читают дашборд и TG» не задаёт owner, момент чтения, очистку записи и адресата TG-уведомления; T4 при этом обещает ответ с `waited_s/cut_turns`, хотя старый процесс погибает во время workflow → закрепить один проверяемый post-start consumer либо убрать обещание TG/dashboard из текущего scope.

suggestion: `tests/test_hot_apply.py:269` — тест порядка позволяет `_record_restart_outcome()` исключением отменить `os.kill`, нарушив «безусловный дедлайн» из цели T3 → определить fail-soft семантику учёта и добавить случай, где запись результата падает, но сигнал всё равно отправляется.

### Verdict

NOT APPROVED. Атомарность admission gate исправлена, но остаются два blocking-дефекта спецификации/тестов: внутренние producer’ы теряют continuation при `DrainingRefused`, а T4 допускает реализацию, которая вообще не запускает restart coroutine.

Подтверждение чтения текущего артефакта: «`Тикетов 4, красных тестов 8 (`oracle: none` — 0, был 1).`»
