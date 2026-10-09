# V-796 — Quota-held workers on the laptop Orchestra

Исследование выполнено только чтением ноутбука через reverse SSH tunnel. `ss` подтвердил listener `127.0.0.1:2222`; ноутбук ответил `maxim-911aird`, часовой пояс — UTC+07. Активный процесс Orchestra (PID 1531) использует `ORCHESTRA_DB_PATH=/mnt/data/Projects/Python/orchestra/data/storage-recovery-local-20260908/orchestra.db`. Это БД активного сервиса, а не `data/orchestra.db` из checkout. Все запросы SQLite открывали эту БД с `mode=ro`; файлы и сервисы ноутбука не изменялись.

## 1. Что вернул `spawn_worker`

Обе квитанции сохранены в `logs` для сессии `media-orchestrator` (`4b46d1ef-d7e4-4853-892c-64f945f58784`). Время в таблице ниже переведено из UTC в локальный UTC+07. `state=QUEUED` — точный state в квитанции при возврате вызова; отдельной оценки времени текст не содержит. В активной БД строки `initial_deliveries` сейчас уже имеют итоговый `SUBMITTED`, а не историю промежуточных переходов.

| Воркер | Вызов / результат в журнале | Строка `initial_deliveries` в активной БД | ETA в ответе |
|---|---|---|---|
| `cs-optimize` | `logs.id=631025`, 08.10 18:39:21.220; tool result says `state=QUEUED`; полный текст ниже. | `delivery_id=d11bc8e9-39f4-4b14-93b1-aee8a14ad8a1`, `state=SUBMITTED`; created `2026-10-08T11:39:21.202279+00:00`, updated `2026-10-08T11:58:43.311344+00:00` (локально 18:39:21 → 18:58:43, **19m22s**). | В квитанции ETA нет. У финальной строки `error_json=NULL`, поэтому прежняя ETA в текущем состоянии БД не сохранилась. |
| `cs-balance` | `logs.id=631582`, 09.10 11:40:40.887; tool result says `state=QUEUED`; полный текст ниже. | `delivery_id=e3b00c37-099f-4bc3-9359-e1fdb2cc1fcb`, `state=SUBMITTED`; created `2026-10-09T04:40:40.871768+00:00`, updated `2026-10-09T05:48:24.652260+00:00` (локально 11:40:40 → 12:48:24, **1h07m44s**, округлённо 68 минут). | В квитанции ETA нет. У финальной строки `error_json=NULL`; ETA для ожидания по текущей записи восстановить нельзя. |

Дословные тексты результатов `spawn_worker` из `logs`:

```text
Worker 'cs-optimize' spawned. Model: opus. Task accepted. delivery_id=d11bc8e9-39f4-4b14-93b1-aee8a14ad8a1; state=QUEUED. Check delivery status with delivery_status('d11bc8e9-39f4-4b14-93b1-aee8a14ad8a1') or GET /api/initial-deliveries/d11bc8e9-39f4-4b14-93b1-aee8a14ad8a1.
Worktree: /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-media/cs-optimize
Repository: /mnt/data/media
Git common dir: /mnt/data/media/.git
Branch: task-27/cs-optimize
Task: #27 [in_progress]
```

```text
Worker 'cs-balance' spawned. Model: sonnet. Task accepted. delivery_id=e3b00c37-099f-4bc3-9359-e1fdb2cc1fcb; state=QUEUED. Check delivery status with delivery_status('e3b00c37-099f-4bc3-9359-e1fdb2cc1fcb') or GET /api/initial-deliveries/e3b00c37-099f-4bc3-9359-e1fdb2cc1fcb.
Worktree: /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-media/cs-balance
Repository: /mnt/data/media
Git common dir: /mnt/data/media/.git
Branch: task-29/cs-balance
Task: #29 [in_progress]
```

Таким образом, владелец видел состояние `QUEUED` и ссылку на проверку статуса, но не видел из самой квитанции `WAITING_QUOTA`, причину ожидания или время до выпуска. После отправки начальной квитанции явного `delivery_status` вызова в журнале до выпуска нет.

## 2. Сигналы после spawn

### `cs-optimize`, 08.10

Сразу после spawn (`logs.id=631026`, локально 18:39:37) владельцу написали: `Opus пошёл на глубокий ресёрч оптимизации — DXVK настройки, моды для VRAM, конкретные графические настройки для твоего GTX 1650 4GB. Сообщу когда будет результат.` Это представляло queued-доставку как начавшееся исследование.

В `logs.id=631029` (локально 18:53:07) владелец попросил: `[18:53] [from TG: Maxim Astrakhantsev] пни его он уснул`. Воркера нашли `idle`, после чего media-orchestrator повторно послал ему сообщение. Этот отдельный `send_message`, а не исходный `spawn_worker`, вернул в `logs.id=631040`:

```text
WAITING_QUOTA: Claude quota gate is closed (utilization 47% is above the line limit 38.65% (norm 31.49% + tolerance 7.166 pp)); the delivery is durably queued and goes out by itself when the gate opens.
```

На этом сигнале оркестратор сообщил владельцу (`logs.id=631041`, 18:53:54): `Квота Claude занята — сообщение в очереди, доставится автоматически когда откроется. Пока он ждёт квоту, могу сделать самое полезное прямо сейчас — создать `dxvk.conf` для ограничения VRAM.` В квитанции ошибки есть utilization и line limit, но нет ETA.

Владелец написал `снял гейт пинай его` в 18:58:54. После этого media-orchestrator вызвал `list_agents`; в 18:59:04 получил `cs-optimize | running` и ответил владельцу, что сообщение дошло и воркер работает. Журнал локальной Orchestra показывает два выпуска очереди: `18:58:39 quota gate open: released 1 waiting deliveries` и `18:58:52 quota gate open: released 1 waiting deliveries`. Первый согласуется с обновлением строки начальной доставки в 18:58:43; второй — с обновлением отдельного `message_deliveries` после отправки-повтора в 18:58:52.

### `cs-balance`, 09.10

Между spawn в 11:40:40 и выпуском в 12:48:22 в журнале родительской сессии ровно четыре строки: один вызов `spawn_worker`, его результат, одно пользовательское сообщение, одно текстовое сообщение media-orchestrator. Среди этих строк нет `WAITING_QUOTA`, `delivery_status`, `get_worker_info` или уведомления о выпуске. Текст владельцу сразу после spawn (`logs.id=631583`, дословно):

```text
Воркер `cs-balance` запущен на ресёрч (#29):

1. **FPS Booster** — что конкретно патчит, можно ли повторить своим модом
2. **Realistic Population 2** — пресеты, настройки баланса жителей, почему 1 человек на дом и как исправить

Сообщу когда будет результат.
```

Системный журнал активной Orchestra содержит `Oct 09 12:48:22 maxim-911aird python3[1531]: quota gate open: released 1 waiting deliveries`. Примерно через две секунды начальная доставка стала `SUBMITTED` в SQLite. Это согласуется с тем, что выпущенной строкой была доставка `cs-balance`; прямой журнал промежуточного состояния самой строки не хранит.

Первый следующий контакт — сообщение владельца в 12:48:30: `[12:48] ау а где воркеры то пинай их че та ходго то`. Только после этого вызова `list_agents` media-orchestrator увидел `cs-balance | running`; его ответ (`logs.id=631602`) был: `` `cs-balance` running, работает над #29. Он в процессе — просто ресёрч занимает время (поиск по форумам, чтение исходников RP2). Жду его отчёт. `` В ответе не сказано, что доставка только что вышла из квотной очереди.

Проверены также `attention_events`, `portfolio_attention_events` и `turn_signals` по parent session и обоим worker session ID: записей о quota wake/auto-report нет. В mailbox на scope `/mnt/data/media` нет сообщения с этими worker именами или от `media-orchestrator`; найденная там одна запись не связана с этими событиями. Покрытие `logs` для `cs-optimize` — 80 строк родителя с 18:39:00 до 19:14:00, для `cs-balance` — 34 строки с 11:40:00 до 12:57:00; проверены tool/tool_result и пользовательские/текстовые строки, quota marker, delivery status и worker info.

## 3. Версия laptop и сравнение с VPS main

Активный checkout ноутбука `/mnt/data/Projects/Python/orchestra` — ветка `main`, HEAD `b7e8b4e0363a510a784d7230e58d3740d680092e`, коммит от 05.10.2026 `V-724: #V-724: explain Claude quota gate with Manim`. Рабочее дерево чистое.

V-788 на ноутбуке **нет**: `git log --all --grep='V-788'` не возвращает коммитов, а объекта VPS-коммита `53006298` в laptop repo нет. Код `HEAD:app/manager.py::send_initial_delivery` делает только `self.sessions.get(session_id)` и сразу бросает `KeyError`, если сессия отсутствует в памяти. Это точная старая ветка из дефекта.

Базовая durable quota queue уже есть на ноутбуке (V-678): `release_waiting()` переводит `WAITING_QUOTA` в `QUEUED` и вызывает `ensure_delivery_runner()`. Однако laptop blob `app/quota_queue.py` — `20528a6d…`, а VPS main — `3dfb0438…`: ноутбук не содержит добавленные на VPS в V-774 поля `billing_mode` и `reason` в `wait_error(...).details`. Последний laptop commit этого файла — `5222d6ef V-678`; в VPS соответствующая версия — `8511e801 V-774`.

Оба указанных VPS main SHA (`6bce34be` и `d63653e4`) содержат исправление V-788: `send_initial_delivery` вызывает `ensure_loaded_by_id()` при промахе в `self.sessions`, а identity check остаётся под lock. V-788 является предком обоих SHA. `app/quota_queue.py` не менялся между этими двумя VPS SHA; оба содержат поля V-774. Значит различия ноутбука по сути — **нет V-788 в manager.py; старая ревизия quota_queue без V-774 metadata**, при этом базовый V-678 release/runner путь присутствует.

## Вывод и рекомендация

Основной дефект — платформенный: для первоначального spawn квотная очередь была представлена владельцу как `state=QUEUED` с текстом «Task accepted» и без причины/ETA. Для `cs-balance` в родительских логах до выпуска нет ни WAITING_QUOTA, ни wake/auto-report/опроса; владелец первым поднял тему через 68 минут. Это не подтверждает, что Оркестратор получил сигнал и намеренно его скрыл.

`cs-optimize` показывает, что при явном ответе `WAITING_QUOTA` на отдельный повторный `send_message` media-orchestrator донёс причину владельцу. В `cs-balance` после его напоминания агент увидел уже `running` и объяснил задержку обычной длительностью ресёрча, но платформа до этого не дала ему понятного состояния начальной доставки или события о её выпуске. Поэтому поведение оркестратора вторично, а не первопричина.

Предлагаю без реализации: (1) возвращать из `spawn_worker` наблюдаемое состояние начальной доставки (`WAITING_QUOTA`, если уже известно; иначе явно queued/pending) и ETA или явное «ETA неизвестно», не формулировать это как уже доставленную задачу; (2) после `WAITING_QUOTA → QUEUED/SUBMITTED` отправлять родительской сессии durable wake с worker name и delivery ID, чтобы она могла сообщить владельцу; (3) в инструкции оркестратора закрепить, что при `QUEUED` нельзя называть воркера начавшим задачу до подтверждения доставки. Для этого анализа и рекомендаций изменений ноутбука не вносил.
