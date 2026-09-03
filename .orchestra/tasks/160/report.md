# #160 — отчёт: воркеры не просыпаются после рестарта

Починен ПЕРВЫЙ дефект (потеря признака прерванности). `_pending_messages` (F4 из
research.md) намеренно не тронут — отдельная задача.

## Что было

`session.stop()` вызывается **ровно из одного места** — `shutdown_all()`
(`manager.py:1759`); пользовательский стоп идёт другим путём, через `interrupt()`
(`routes/sessions.py:549` → `manager.stop_worker` → `session.interrupt()`). При этом
`stop()` безусловно писал в БД `idle`. Следующий старт читал
`WHERE status='running'` по пустому месту → `was_running` пуст → `_inject_restart_notice`
не вызывался ни для кого.

Инверсия, которая и объясняет, почему баг дожил: пробуждение выживало ТОЛЬКО когда
`stop()` не успевал отработать (SIGKILL/OOM при `TimeoutStopSec=30`). Чем чище
остановка, тем гарантированнее терялась работа. `systemctl restart` — штатный сценарий
обновления VPS — попадал ровно в ломающийся путь.

## Что стало

Новый статус `AgentStatus.INTERRUPTED = "interrupted"` (`session_state.py`).

- `session.py stop()`: агент, застигнутый в `RUNNING`, помечается `INTERRUPTED`;
  бывший `IDLE`/`WAITING` остаётся `IDLE`. Это fail-closed в обе стороны на уровне записи.
- `manager.py auto_resume_all()`: `was_running` читает `('running','interrupted')` —
  `running` сохранён ради hard-kill (арм B), ломать работающий путь нельзя. `resumable`
  и строка нормализации в `idle` расширены тем же значением.

Почему `status`, а не новая колонка: `status` уже персистится, читается стартом и
мигрируется. Новая колонка = миграция + второй источник правды о состоянии агента
(грабля «одна мысль = один owner»).

`interrupted` живёт в БД от shutdown до `auto_resume_all`, который тут же нормализует его
в `idle`. Фронтенд не трогал: `_orchState` (`app.js:1265`) сводит незнакомый статус к
`idle`, что для остановленного агента корректно; SQL-запросы фильтруют по `archived`, а не
по списку разрешённых, так что значение проходит без ошибок.

## Приёмка (арм A ДО и ПОСЛЕ, один вывод)

`docs/tasks/160/repro_restart.py`, продовый код на временной БД.

**ДО фикса:**
```
A graceful restart (systemctl restart)
  status seen by auto_resume : idle
  restart notices sent       : 0  -> FAIL — sits idle, nobody wakes it
B hard kill (SIGKILL/OOM)
  status seen by auto_resume : running
  restart notices sent       : 1  -> PASS — woken
```
**ПОСЛЕ фикса:**
```
A graceful restart (systemctl restart)
  status seen by auto_resume : interrupted
  restart notices sent       : 1  -> PASS — woken
B hard kill (SIGKILL/OOM)
  status seen by auto_resume : running
  restart notices sent       : 1  -> PASS — woken
```
Арм A `0 → 1`, арм B без регрессии.

## Тесты

`tests/test_manager.py::TestRestartWake` (новый класс, 4 теста):
- `test_graceful_restart_wakes_interrupted_worker` — арм A
- `test_hard_kill_restart_still_wakes_worker` — арм B, защита от регрессии
- `test_idle_worker_not_woken_after_restart` — fail-closed, обратная сторона
- `test_stop_preserves_interrupted_status_in_db` — признак на уровне БД

`tests/test_session.py::TestStop`: `test_stop_sets_idle` → переименован в
`test_stop_marks_running_session_interrupted` (тест кодировал СТАРЫЙ контракт, который
задача меняет намеренно — правка поведенческая, не подгонка строки). Добавлен
`test_stop_leaves_finished_session_idle` — обратная сторона.

Порядок соблюдён: RED (2 failed) → фикс → GREEN (4 passed).

**Мутация** (откат через `git show`, НЕ `git stash`):
```
git show 480ba58^:app/session.py > app/session.py
grep -c "INTERRUPTED" app/session.py  → 0   (маркер подтверждает откат)
pytest tests/test_manager.py::TestRestartWake
  → 2 failed, 2 passed
```
Тесты привязаны к поведению, а не к форме: без фикса краснеют.

**Асинхрон:** 4 прогона подряд — `4 passed` каждый (1.48/1.47/1.46/1.45 s).

**Соседние модули:** `tests/test_manager.py` + `tests/test_session.py` → **287 passed**.
Полный сьют не гонялся (нужен глобальный лок и разрешение).

## Файлы

- `app/session_state.py` (+6/-0) — статус `INTERRUPTED`
- `app/session.py` (+8/-3) — `stop()` различает оборванный ход и завершённый
- `app/manager.py` (+10/-4) — `auto_resume_all` будит по обоим признакам
- `tests/test_manager.py` (+104/-0) — `TestRestartWake`
- `tests/test_session.py` (+22/-3) — обновлённый контракт `stop()`
- `docs/tasks/160/` — research.md, plan.md, repro_restart.py, report.md

## Breaking

`stop()` больше не оставляет работавшую сессию в `IDLE` — она проходит через
`INTERRUPTED`. Значение транзиентное (нормализуется на старте), но если появится код,
сверяющий статус со списком разрешённых, `interrupted` придётся учесть.

## Не сделано намеренно

- `_pending_messages` (F4) — очередь сообщений по-прежнему не переживает рестарт.
  Отдельная задача по указанию оркестратора: смешивать в один коммит нельзя, иначе
  не откатить одно без другого.
- Фильтр `session_id IS NOT NULL` (`manager.py:1656`) — отдельный известный риск
  для сессии, пойманной посреди `compact()`. К #160 отношения не имеет (в обоих армах
  сессия восстанавливалась), но остаётся незакрытым.
- Ветка `was_waiting` читает статус из того же источника; отдельно не воспроизводил.
