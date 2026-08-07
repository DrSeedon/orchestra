# #167 — Три молчащих сбоя: исследование

**Дата:** 06.08.2026
**Внешнее ревью:** ОТСУТСТВУЕТ. Codex недоступен до 08.08 (квота исчерпана терминально).
Всё ниже — self-review, за вердикт внешнего ревьюера НЕ выдаётся.

## Вопрос

- **Контекст:** пробуждение `Orchestra-orchestrator` из гибернации 06.08, 14:52–14:59 CEST.
- **Что проверяется:** три записи журнала, в которых система знала причину и промолчала.
- **База сравнения:** правило проекта из `CLAUDE.md` — «каждая ветка ошибки обязана
  показать класс исключения или ответ сервера».
- **Измеримый исход:** фактическая строка, уходящая в журнал и в TG, при исключении
  с пустым `str(e)`; факт наличия/отсутствия скилл-файлов на диске; поведение `add_log`
  при отсутствующей сессии.

## Ground truth — журнал (первоисточник, tier 1)

`journalctl -u orchestra --since "2026-08-06 14:50" --until "2026-08-06 15:05"`:

```
Aug 06 14:52:49 Future exception was never retrieved
Aug 06 14:52:49 future: <Future finished exception=IntegrityError('FOREIGN KEY constraint failed')>
Aug 06 14:52:49 sqlite3.IntegrityError: FOREIGN KEY constraint failed
Aug 06 14:57:25 [Orchestra-orchestrator] skill refresh failed: pipeline name is empty
Aug 06 14:58:30 ClaudeBackend connect failed:
Aug 06 14:58:30 [Orchestra-orchestrator] backend connect failed:
Aug 06 14:58:54 TG incoming: chat=-1003760207564 thread=813 from=Maxim text=❌ connect failed:
Aug 06 14:58:59 [Orchestra-orchestrator] skill refresh failed: pipeline name is empty
```

Строка 14:58:54 — это и есть повод задачи: юзер переслал в чат то, что получил.

---

## Дефект 1 — пустые сообщения об ошибке

### Механизм (CONFIRMED — измерено)

Целое семейство исключений стрингуется в пустоту:

```
ReadTimeout              str()='' empty=True
ConnectTimeout           str()='' empty=True
PoolTimeout              str()='' empty=True
TimeoutError             str()='' empty=True   ← этот и сработал
asyncio.CancelledError   str()='' empty=True
ConnectionResetError     str()='' empty=True
BrokenPipeError          str()='' empty=True
KeyboardInterrupt        str()='' empty=True
```

### ПОПРАВКА К ПОСТАНОВКЕ ЗАДАЧИ

Задача says: «во всех трёх местах печатать `type(e).__name__` когда `str(e)` пуст».
Это верно для двух мест из трёх. Под одним симптомом сидят **два разных дефекта**, и
чинятся они по-разному. Воспроизведение (`TimeoutError()`, дословный рендер текущего кода):

| Место | Текущий код | Фактическая строка |
|---|---|---|
| `app/backend_claude.py:232` | `"ClaudeBackend connect failed: %s%s" % (e, "")` | `'ClaudeBackend connect failed: '` |
| `app/session.py:875-876` | `f"connect failed: {e}"` | `'connect failed: '` |
| `app/tg_bridge.py:393` | `f"{type(error).__name__}: {error}"` | `'TimeoutError: '` |

- Первые два — класс исключения **действительно отсутствует**. Диагноза нет вообще.
- Третье — класс **уже печатается**. Дефект другой: разделитель `": "` выводится
  при пустом сообщении, и строка обрывается висячим двоеточием. Информация есть,
  но выглядит как обрезанная передача.

Вывод: `type(e).__name__` во всех трёх местах чинит два случая и НЕ чинит третий —
`tg_bridge` продолжит печатать `TimeoutError: `. Нужен один хелпер, который решает и
про класс, и про разделитель.

### Сколько копий правила существует (CONFIRMED — grep)

Правило «покажи класс» реализовано в кодовой базе **минимум четырежды, независимо**:

1. `app/mcp_stdio.py:88` — `_exception_text(exc)`, каноничная форма:
   `f"{type(exc).__name__}: {message}" if message else type(exc).__name__`
2. `app/routes/system.py:1085` — `_bug_error(exc)`, тот же алгоритм, другое имя.
   Отличие: `str(exc)` без `.strip()` → строка из одних пробелов проходит как непустая.
3. `app/merge_operations.py:35` — `_text(value, fallback)` + ручная передача
   `type(exc).__name__` фолбэком, 8 вызовов.
4. `app/limit_wake.py:428,631` — инлайн `str(error) or type(error).__name__`.

Плюс ~25 мест с `f"{type(e).__name__}: {e}"` вручную (`notify.py`, `backend_codex.py`,
`session_turns.py`, `session_hibernate.py`, `bg_jobs.py`, `main.py`) — все они
воспроизводят баг висячего двоеточия из `tg_bridge`.

Это ровно грабля «одна мысль = один owner»: правило записано в `CLAUDE.md`, владельца
в коде нет, четыре копии тихо разошлись.

### Объём

Широкий grep по `app/` даёт **223** сайта форматирования исключений. Механически
переписать все 223 — диффа на пол-проекта против правила хирургических правок, и
большая часть из них форматирует исключения, у которых `str()` никогда не пуст
(`ValueError`, `RuntimeError`, `subprocess.CalledProcessError`).

Предлагаемый объём: один общий хелпер + перевод на него мест, где (а) исключение
может быть таймаутом/отменой/обрывом сети, или (б) текст виден ЮЗЕРУ, а не только
журналу. Остальные 4 копии хелпера удалить в пользу общего.

**Confidence: CONFIRMED** — измерено дословным рендером кода и подтверждено журналом.

---

## Дефект 2 — потерянная запись лога

### Воспроизведение (CONFIRMED)

```
ORCHESTRA_DB_PATH=/mnt/data/tmp167/repro.db uv run python ./repro167.py
→ RAISED: IntegrityError 'FOREIGN KEY constraint failed'
```
(лог для `session_id`, которого нет в `sessions`)

### Где теряется исключение

`app/session.py:1781-1793`, `_log()`:

```python
future = asyncio.get_event_loop().run_in_executor(_db_executor(), add_log, ...)
self._log_futures.add(future)
future.add_done_callback(self._log_futures.discard)   # ← result() не вызывается
```

`discard` снимает future из набора и всё. Исключение внутри future никем не
забирается → asyncio печатает своё `Future exception was never retrieved`. Это
сообщение самого рантайма, а не наша обработка: оно не говорит НИ имени агента,
НИ типа лога, НИ содержимого потерянной записи.

**Ключевое наблюдение:** в ЭТОМ ЖЕ классе, на 20 строк выше (`session.py:1770-1779`),
близнец-писатель телеметрии сделан правильно:

```python
def completed(done) -> None:
    self._log_futures.discard(done)
    try:
        done.result()
    except Exception as error:
        logger.error(f"[{self.name}] telemetry write failed: {error}")
```

Один файл, один класс, два способа. Опять «одна мысль = один owner».

### Ответ на вопрос «гасить или логировать» — обосновано

**Гасить запись тихо нельзя, логировать факт потери — да.** Обоснование из схемы, а
не из вкуса:

```sql
session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
```

`ON DELETE CASCADE` — это уже принятое проектное решение: логи не переживают свою
сессию. Значит запись лога для несуществующей сессии **не имеет дома by design**, и
её потеря — не авария, а следствие каскада. Хранить её негде.

Но «потерять запись» и «промолчать о потере» — разные вещи. Тихое гашение даст
проверку, которая одинаково выглядит при успехе и при провале (грабля проекта:
«проверка, дающая одинаковый вывод при успехе и провале, — не проверка»), и следующий
раз, когда FK упадёт по ДРУГОЙ причине (битая миграция, гонка при архивации), никто
не узнает.

Решение: ловить исключение записи лога и печатать одну строку с именем агента, типом
записи и классом ошибки. Fail loud — но в журнал, а не в неизвлечённый future.

**Confidence: CONFIRMED** — воспроизведено, схема прочитана, близнец найден в том же файле.

---

## Дефект 3 — `skill refresh failed: pipeline name is empty`

### Ответ: ЭТО ПОЛОМКА, а не шум. Корневой оркестратор реально теряет скиллы.

Задача допускала, что пустой `pipeline` у оркестратора — норма, и тогда чинить надо
ложную тревогу. Проверено по коду и по живой конфигурации — **не норма**.

### Доказательство 1 — код сам объявляет пустой pipeline легаси-значением

- `app/pipeline.py:465-478`, docstring `get_active_pipeline`:
  «2) пусто/корневой оркестратор → `DEFAULT_PIPELINE`».
- `app/manager.py:1354-1357`, `_load_from_db`:
  ```python
  # Old rows (migrated) store pipeline='' → normalize to DEFAULT_PIPELINE.
  pipeline = db_row.get("pipeline") or DEFAULT_PIPELINE
  ```

То есть нормализация `'' → default` УЖЕ описана как обязательная.

### Доказательство 2 — нормализация не доезжает до сессии (root cause)

`app/manager.py:1408`, конструктор `AgentSession` в том же `_load_from_db`:

```python
pipeline = db_row.get("pipeline") or DEFAULT_PIPELINE   # строка 1357 — нормализовано
...
session = AgentSession(
    ...
    pipeline=db_row.get("pipeline", ""),                # строка 1408 — СЫРОЕ ''
)
```

Локальная переменная `pipeline` нормализована и уходит в промпт
(`ROLE_SYSTEM_PROMPT(pipeline, role)` — поэтому промпт у оркестратора правильный), а
в объект сессии кладётся ненормализованный `db_row`. Дальше
`_refresh_skills` (`app/session.py:847`) читает `self.pipeline`, получает `''` и падает.

Это тот же класс, что и дефекты 1-2: одна мысль (нормализация) — два владельца,
которые разошлись.

### Доказательство 3 — измеренная цена

```
uv run python -c "get_role('', 'orchestrator')"
→ RAISED: FileNotFoundError 'pipeline name is empty'
uv run python -c "get_role('default', 'orchestrator').skills"
→ ['codex-debate', 'grill-me', 'html-artifacts', 'orchestra-agents', 'vps-deploy']
```

Должно инъектиться 5 скиллов, инъектится 0.

### Доказательство 4 — подтверждено на диске живой системы

```
ls -la /mnt/data/Projects/Python/orchestra/.claude/skills/
drwxr-xr-x  codex-debate      Jun  5 14:00
-rw-r--r--  SKILL.md          Jun  5 14:00
```

Один каталог от 5 июня (остался с более раннего механизма), четырёх остальных
скиллов — `grill-me`, `html-artifacts`, `orchestra-agents`, `vps-deploy` — НЕТ.
Оркестратор работает без них с момента введения пайплайнов.

### Кого затрагивает (живая БД, read-only копия)

```sql
SELECT CASE WHEN pipeline IS NULL OR pipeline='' THEN 'EMPTY' ELSE pipeline END, status, COUNT(*)
EMPTY|archived|26      EMPTY|running|1      ← Orchestra-orchestrator
default|archived|309   default|idle|67      default|running|3   default|waiting|1
```

Единственная ЖИВАЯ сессия с пустым pipeline — корневой `Orchestra-orchestrator`.
Остальные 26 — архив. Спавн новых сессий не затронут: `manager.py:684` использует
уже нормализованную переменную. Ломается только загрузка легаси-строки из БД.

**Confidence: CONFIRMED** — код, измерение, состояние диска и живая БД сходятся.

---

## Контр-доводы (что говорит против)

1. **«Пустой pipeline — легитимный маркер ad-hoc сессии»** — `pipeline.py:303-305`
   явно комментирует пустое имя как «legacy/ad-hoc session with no pipeline → treat as
   not found, чтобы ветка FileNotFoundError у вызывающих отработала (role=None), а не
   крэш». То есть `load_pipeline('')` бросает FileNotFoundError НАМЕРЕННО.
   *Ответ:* это не противоречит выводу. Намеренно бросать умеет `load_pipeline`;
   дефект в том, что `_refresh_skills` ловит это как ошибку и печатает `warning`,
   тогда как `_load_from_db` для этого же значения уже решил, что оно означает
   `default`. Правильное место фикса — нормализация на входе, а не подавление warning
   на выходе. Чинить надо расхождение двух владельцев, а не сам FileNotFoundError.
2. **Против массовой правки дефекта 1:** 223 сайта — соблазн переписать всё разом.
   Против этого работает правило хирургических правок и цена отката. Ограничиваюсь
   местами с сетевыми/таймаутными исключениями и user-facing текстом.
3. **Не проверено:** влияние отсутствия 4 скиллов на КАЧЕСТВО работы оркестратора
   не измерялось — только факт отсутствия файлов. Утверждать «поэтому оркестратор
   работал хуже» я не могу, это была бы гипотеза без замера.

## Затронутые файлы

| Дефект | Файлы |
|---|---|
| 1 | новый общий хелпер; `app/tg_bridge.py:393`, `app/session.py:875-876,943-944`, `app/backend_claude.py:232,301,330`, `app/session_hibernate.py:182-183`; удаление копий из `mcp_stdio.py:88`, `routes/system.py:1085`, `merge_operations.py`, `limit_wake.py` |
| 2 | `app/session.py:1781-1793` (`_log`) |
| 3 | `app/manager.py:1408` (`_load_from_db`) |

## Риски

- **Дефект 1:** хелпер трогает `tg_bridge` — shared runtime доставки. Грабля проекта:
  `app/routes/` живёт в памяти до рестарта, `app/mcp_stdio.py` подхватывается сразу →
  контракт между ними не меняю, хелпер чисто форматирующий, без смены сигнатур.
- **Дефект 2:** `_log` — горячий путь, вызывается на каждое событие. Добавляемый
  колбэк не должен ничего блокировать и не должен рекурсивно звать `_log`
  (иначе цикл при мёртвой БД) — только `logger`.
- **Дефект 3:** нормализация меняет `self.pipeline` у легаси-сессий с `''` на
  `default` → значение попадёт в `_persist` (`session.py:564`) и перезапишет колонку
  в БД. Это делает миграцию де-факто необратимой для этой строки. Приемлемо: значение
  и так уже трактуется как `default` везде, кроме сломанного места.

## Источники

1. `journalctl -u orchestra --since "2026-08-06 14:50"` — живой журнал, tier 1.
2. Исходники: `app/session.py`, `app/manager.py`, `app/pipeline.py`, `app/db.py`,
   `app/tg_bridge.py`, `app/backend_claude.py`, `app/mcp_stdio.py`,
   `app/routes/system.py`, `app/merge_operations.py`, `app/prompting.py` — tier 2.
3. Измерения: рендер строк ошибок, `get_role`, репро FK, `ls .claude/skills/`,
   SQL по read-only копии `data/orchestra.db` — tier 1.
4. `CLAUDE.md`, секция «Грабли» — правило про класс исключения.
