## Summary

План хорошо фиксирует целевой UX, но пока не готов к реализации: его ключевая предпосылка для T3 неверна, а предлагаемое коалесцирование правок не поддерживается текущей очередью.

Доказательство чтения плана — строка 96: «`правки просто не находят message_id и молча ничего не делают; ход всё равно заканчивается надёжным якорем`».

## Findings

1. **blocking — [docs/tasks/189/plan.md:14](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:14)**  
   Утверждение, что `logs.tool_use_id` и `logs.tool_name` уже записываются, неверно. Таблица `logs` содержит только `id/session_id/ts/type/content/event_id` ([app/db.py:88](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/app/db.py:88)); `add_log()` также принимает и вставляет только `event_id` ([app/db.py:1010](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/app/db.py:1010)). В `session.py` события `tool_use` и `tool_result` вызывают `_log()` без metadata ([app/session.py:1309](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/app/session.py:1309)). Указанная «миграция `app/db.py:613`» на самом деле добавляет `usage_snapshots.provider_usage`, а не поля журнала.  
   **Предложение:** расширить T3 изменениями `app/db.py`, `Session._log`/обработчика событий и чтения журнала; добавить миграцию обеих колонок и тест сохранения metadata для `tool` и `tool_result`. Утверждение о состоянии живой БД из разрешённых файлов проверить невозможно, но миграции для неё в текущем коде точно нет.

2. **blocking — [docs/tasks/189/plan.md:83](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:83)**  
   План требует коалесцировать правки `⚙️`, одновременно обещая не менять очередь. Текущий `_tg_edit_message_safe()` не принимает `telemetry_key`; каждый edit попадает под уникальный ключ ([app/tg_bridge.py:1764](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/app/tg_bridge.py:1764), [app/tg_bridge.py:1787](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/app/tg_bridge.py:1787)). Значит, AC про схлопывание правок технически не обеспечен. Передача одного ключа первоначальной отправке и правкам тоже опасна: очередь заменяет `call_factory` существующего элемента, а edit может начать ждать `Future` той самой заменённой отправки.  
   **Предложение:** отдельно спроектировать безопасный edit-item с ключом последней версии и уже разрешённым `message_id`; добавить AC на бурст правок, ограниченный размер очереди и отсутствие блокировки reliable lane.

3. **blocking — [docs/tasks/189/plan.md:48](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:48)**  
   Локальное состояние мутируется до надёжной доставки якоря. При `_TgDeliveryOverloaded` курсор откатывается на предыдущую строку ([app/tg_bridge.py:3281](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/app/tg_bridge.py:3281)), поэтому `turn ended` либо последняя строка действия будет проиграна повторно поверх уже изменённых `_turn_actions` и индексов. Возможны дубли действий, повторная финализация и несколько якорей.  
   **Предложение:** хранить checkpoint состояния вместе с `last_id` либо делать обработку каждой строки идемпотентной по `log.id`; добавить мутационный тест: первый reliable anchor вызывает overload, повтор строки создаёт ровно один логический anchor и не дублирует actions.

4. **suggestion — [docs/tasks/189/plan.md:48](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:48)**  
   «По одному потоку на агента, гонок нет» не покрывает рестарт самого `stream_logs`. При новом запуске он выставляет `last_id` в последнюю существующую строку ([app/tg_bridge.py:3012](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/app/tg_bridge.py:3012)), поэтому середина активного хода до рестарта не восстанавливается. Следующие результаты не найдут вызовы, а итоговый якорь покажет неполный ход.  
   **Предложение:** определить восстановление от последнего `turn ended` либо явно принять частичный ход и закрепить это тестом. Риск на строке 98 описывает только отсутствие якоря при рестарте, но не продолжение уже начатого хода после восстановления потока.

5. **suggestion — [docs/tasks/189/plan.md:44](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:44)**  
   Подавление всех прочих `status` скрывает полезное подтверждение steered-сообщения: сейчас пользователь видит `⚡ message steered into active Codex turn`; после изменения он не узнает, вошло ли новое сообщение в текущий ход или осталось в очереди. Аналогично исчезнет `waiting for bg jobs`, и тишина будет выглядеть как зависание.  
   **Предложение:** сохранить короткий пользовательский статус для `message steered…` и ожидания фоновой работы либо отразить их в `⚙️`; добавить конкретные AC для обоих случаев.

6. **suggestion — [docs/tasks/189/plan.md:120](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:120)**  
   AC проверяет «ровно одно надёжное сообщение» на `turn ended`, но не ограничивает общее давление десяти агентов и не проверяет перегруженную reliable lane — именно главный инцидент задачи. Потолок 300 символов гарантирует один chunk, но не гарантирует admission или отсутствие повторов после rollback.  
   **Предложение:** добавить тест заполненной reliable queue и одновременных завершений нескольких потоков: очередь не стопорится, cursor корректно переигрывается, на ход остаётся один якорь.

7. **suggestion — [docs/tasks/189/plan.md:133](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:133)**  
   «При пустом `tool_use_id` поведение прежнее — по соседству» неоднозначно для параллельных legacy-вызовов: последовательность `tool, tool, result, result` не позволяет надёжно определить пары. «Последняя незакрытая» даст LIFO, хотя результаты могут идти в другом порядке.  
   **Предложение:** сформулировать честную детерминированную деградацию и тест точного порядка; для неизвестной пары лучше пометить результат как unmatched внутри `⚙️`, чем приписать его неправильному действию.

8. **suggestion — [docs/tasks/189/plan.md:146](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:146)**  
   T5 действительно можно вынести отдельно, но его AC не доказывает заявленное удаление: grep не проверяет `_edit_tool_with_result`, `_fmt_worker_info`, `_send_png_to_tg`, `_diff_images_enabled` и `_result_images_enabled`. Кроме того, `blocked-by: T4` не обоснован: удаление старого renderer зависит от прекращения его вызовов в T1/T2, а не от нового diffstat-форматтера.  
   **Предложение:** либо исключить T5 из этой задачи как необязательный cleanup, либо перечислить все удаляемые символы в AC и убрать лишнюю зависимость от T4.

9. **question — [docs/tasks/189/plan.md:68](/home/kesha/orchestra/worktrees/home-kesha-orchestra/tg-readability/docs/tasks/189/plan.md:68)**  
   «Зеркала получают те же компактные строки» не согласуется с правилом «очередь доставки не трогаем»: текущая `_mirror_send` — отдельная доставка, а план не описывает, где хранится её собственный `message_id` для последующих правок.  
   **Предложение:** уточнить контракт: зеркало тоже редактирует одно сообщение и имеет отдельный handle либо получает только финальный статический summary. Добавить AC, чтобы зеркало не продолжило слать отдельный поток действий.

## Verdict

**Changes required.** Блокируют реализацию неверная схема T3 и отсутствие безопасного механизма коалесцированных edits. До начала кода плану также нужен явный контракт идемпотентности при rollback `_TgDeliveryOverloaded`.
