# Context for item-22

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/db.py b/app/db.py
index 446a4a5a3..44ca8786d 100644
--- a/app/db.py
+++ b/app/db.py
@@ -29,41 +29,43 @@ def _resolve_db_path() -> Path:
 
 DB_PATH = _resolve_db_path()
 
 
 def _conn() -> sqlite3.Connection:
     DB_PATH.parent.mkdir(exist_ok=True)
     conn = sqlite3.connect(str(DB_PATH))
     conn.row_factory = sqlite3.Row
     # WAL: readers don't block writers — essential when many agents log concurrently
     conn.execute("PRAGMA journal_mode=WAL")
     # 5s busy timeout: retry on locked DB instead of raising immediately
     conn.execute("PRAGMA busy_timeout=5000")
     conn.execute("PRAGMA foreign_keys=ON")
     return conn
 
 
 def init_db() -> None:
     with _conn() as c:
         c.executescript("""
             CREATE TABLE IF NOT EXISTS sessions (
-                id TEXT PRIMARY KEY,
+                -- NOT NULL для новых БД; существующие закрывает триггер в _guard_session_id:
+                -- ужесточить колонку без перестройки таблицы SQLite не даёт (#54)
+                id TEXT PRIMARY KEY NOT NULL,
                 name TEXT NOT NULL,
                 scope TEXT NOT NULL,
                 cwd TEXT NOT NULL,
                 model TEXT NOT NULL,
                 system_prompt TEXT DEFAULT '',
                 status TEXT DEFAULT 'starting',
                 session_id TEXT,
                 cost_usd REAL DEFAULT 0.0,
                 worktree_path TEXT,
                 branch TEXT,
                 base_branch TEXT DEFAULT '',
                 needs_switch INTEGER DEFAULT 0,
                 is_orchestrator INTEGER DEFAULT 0,
                 color TEXT DEFAULT '',
                 mcp_servers_custom TEXT DEFAULT '',
                 profile TEXT DEFAULT '',
                 runtime_handoff TEXT DEFAULT '',
                 last_summary TEXT DEFAULT '',
                 created_at TEXT NOT NULL,
                 finished_at TEXT,
@@ -353,43 +355,69 @@ def _reconstruct_costs(c) -> None:
             "AND (content LIKE 'turn ended%$%' OR content LIKE 'turn done%$%') ORDER BY id ASC",
             (s["id"],),
         ).fetchall()
         prev = 0.0
         real_cost = 0.0
         for l in logs:
             m = _re.search(r'\$(\d+\.?\d*)', l["content"])
             if not m:
                 continue
             val = float(m.group(1))
             if val == 0:
                 continue
             if val < prev:
                 real_cost += prev
             prev = val
         real_cost += prev
         c.execute("UPDATE sessions SET cost_usd=?, cost_usd_cached=0, cost_reset_v1=1 WHERE id=?",
                   (round(real_cost, 4), s["id"]))
 
 
+def _guard_session_id(c) -> None:
+    """Запретить строку-призрак: `sessions.id` не может быть NULL или пустым (#54).
+
+    `id TEXT PRIMARY KEY` в SQLite ПУСКАЕТ NULL — проверено вставкой на копии живой БД:
+    две строки с `id=NULL` прошли, а `UPDATE … WHERE id=?` по такой строке меняет ноль
+    строк молча. Сессия существует, но ни одно обновление до неё не доходит: статус, счётчик
+    ходов и `session_id` навсегда остаются теми, что были при вставке.
+
+    Триггер, а не `NOT NULL`, по двум причинам: колонку в SQLite нельзя ужесточить без
+    перестройки таблицы (а на неё завязан `logs … REFERENCES sessions(id) ON DELETE CASCADE`),
+    и `NOT NULL` не ловит пустую строку — а она даёт ровно тот же призрак.
+    """
+    c.executescript("""
+        CREATE TRIGGER IF NOT EXISTS sessions_id_required_insert
+        BEFORE INSERT ON sessions
+        WHEN NEW.id IS NULL OR TRIM(NEW.id) = ''
+        BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;
+
+        CREATE TRIGGER IF NOT EXISTS sessions_id_required_update
+        BEFORE UPDATE OF id ON sessions
+        WHEN NEW.id IS NULL OR TRIM(NEW.id) = ''
+        BEGIN SELECT RAISE(ABORT, 'sessions.id must be non-empty'); END;
+    """)
+
+
 def _migrate(c) -> None:
     # Additive ALTER TABLE migrations — safe to re-run (IF NOT EXISTS / column check).
     # Never drop columns: old Orchestra versions reading the same DB must still work.
+    _guard_session_id(c)
     cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
     if "color" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
     if "context_pct" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
     if "context_tokens" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
     if "progress_pct" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN progress_pct INTEGER DEFAULT 0")
     if "progress_status" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN progress_status TEXT DEFAULT ''")
     if "backend_type" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN backend_type TEXT DEFAULT 'claude'")
     if "task_id" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN task_id TEXT DEFAULT ''")
     if "description" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN description TEXT DEFAULT ''")
     if "cost_usd_cached" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN cost_usd_cached REAL DEFAULT 0.0")
     if "context_cost" not in cols:
@@ -606,40 +634,47 @@ def _migrate(c) -> None:
     # INSERT OR IGNORE: повторная миграция не падает и не перетирает существующую строку.
     c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")
     collector_started_at = datetime.now(timezone.utc).isoformat()
     c.execute(
         """INSERT OR IGNORE INTO kv(key, value)
            VALUES ('tool_error_collector_started_at', ?)""",
         (collector_started_at,),
     )
     c.execute(
         """INSERT OR IGNORE INTO kv(key, value)
            VALUES ('turn_usage_collector_started_at', ?)""",
         (collector_started_at,),
     )
 
 
 def save_session(
     s: dict,
     *,
     _connection: sqlite3.Connection | None = None,
 ) -> None:
+    # Пустой id — не «почти валидная» строка, а невидимка: все UPDATE … WHERE id=?
+    # по ней меняют ноль строк молча (#54). Падать здесь, а не позже и не в другом месте.
+    if not str(s.get("id") or "").strip():
+        raise ValueError(
+            f"session id is required and must be non-empty "
+            f"(name={s.get('name')!r}, scope={s.get('scope')!r})"
+        )
     s.setdefault("context_pct", 0)
     s.setdefault("context_tokens", 0)
     s.setdefault("progress_pct", 0)
     s.setdefault("progress_status", "")
     s.setdefault("backend_type", "claude")
     s.setdefault("task_id", "")
     s.setdefault("description", "")
     s.setdefault("cost_usd_cached", 0.0)
     s.setdefault("context_cost", 0.0)
     s.setdefault("total_turns", 0)
     s.setdefault("total_input_tokens", 0)
     s.setdefault("total_output_tokens", 0)
     s.setdefault("total_cache_read_tokens", 0)
     s.setdefault("total_cache_create_tokens", 0)
     s.setdefault("total_tool_calls", 0)
     s.setdefault("template_hash", "")
     s.setdefault("role", "worker")
     s.setdefault("parent_id", "")
     s.setdefault("parent_name", "")
     s.setdefault("pipeline", "")
@@ -737,40 +772,47 @@ def publish_ready_session(s: dict) -> None:
         )
         save_session(s, _connection=c)
 
 
 def update_session_lifecycle(
     session_id: str,
     *,
     branch: str,
     base_branch: str,
     task_id: str,
     needs_switch: bool,
 ) -> bool:
     """Persist the Git lifecycle snapshot for loaded and detached sessions alike."""
     with _conn() as c:
         cur = c.execute(
             """UPDATE sessions
                SET branch=?, base_branch=?, task_id=?, needs_switch=?
                WHERE id=? AND status != 'archived'""",
             (branch, base_branch, task_id, int(needs_switch), session_id),
         )
+        if cur.rowcount == 0:
+            # Ноль строк — это не «нечего менять», это промах по идентичности (#54):
+            # строка либо архивная, либо её id не совпадает ни с чем (пустой/призрак).
+            logger.warning(
+                "UPDATE sessions changed 0 rows: lifecycle for id=%r not persisted",
+                session_id,
+            )
         return cur.rowcount == 1
 
 
 def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str) -> dict:
     """Move an orchestrator's session to a new scope in one transaction.
 
     Migrates session.scope+cwd, and (best-effort) tm_projects.scope, active
     bg_jobs.target_scope, and test_lock.scope from old_scope to new_scope.
     session_id (Claude resume token) is left intact — context survives.
 
     Rejected if another session with the same name already lives in new_scope
     (UNIQUE(name, scope)). tm_projects/test_lock migration is skipped on UNIQUE
     collision (target already taken) but the session move still succeeds.
     """
     with _conn() as c:
         row = c.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
         if not row:
             return {"error": f"session not found: {session_id}"}
         name = row["name"]
         clash = c.execute(
@@ -886,44 +928,48 @@ def get_last_turn_map() -> dict[str, str]:
 def delete_session(session_id: str) -> None:
     with _conn() as c:
         c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
 
 
 def delete_archived_session(name: str, scope: str) -> None:
     """Free the UNIQUE(name, scope) slot held by an archived row before re-spawn.
 
     get_session_by_name filters archived out, so the archived row is invisible to
     callers — this deletes it explicitly (name+scope scoped, never name-only).
     """
     with _conn() as c:
         c.execute(
             "DELETE FROM sessions WHERE name=? AND scope=? AND status='archived'",
             (name, scope),
         )
 
 
 def archive_session(session_id: str) -> None:
     with _conn() as c:
-        c.execute(
+        cur = c.execute(
             "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
             (datetime.now(timezone.utc).isoformat(), session_id),
         )
+        if cur.rowcount == 0:
+            logger.warning(
+                "UPDATE sessions changed 0 rows: session id=%r not archived", session_id,
+            )
 
 
 def add_log(
     session_id: str,
     ts: datetime,
     type: str,
     content: str,
     event_id: str = "",
 ) -> int:
     """ИНВАРИАНТ: строки logs неизменяемы — только этот INSERT и оптовый DELETE по
     возрасту в cleanup_old_logs. Ни одного UPDATE. На этом стоит зеркало журнала в
     браузере (#8): сохранённая строка не может стать неверной, только исчезнуть.
     Появится первый UPDATE logs (например, редактирование сообщения) — зеркало начнёт
     врать МОЛЧА; чинить придётся get_logs_sync и клиентское хранилище вместе.
     """
     with _conn() as c:
         cur = c.execute(
             """INSERT INTO logs (session_id, ts, type, content, event_id)
                VALUES (?, ?, ?, ?, ?)""",
             (session_id, ts.isoformat(), type, content, event_id),
diff --git a/app/manager.py b/app/manager.py
index c1887da6b..e57598566 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1147,41 +1147,50 @@ class SessionManager:
     _UPDATABLE_FIELDS = frozenset({"description", "system_prompt", "tg_topic"})
 
     def update_session_fields(self, name: str, scope: str, **fields) -> AgentSession | None:
         """Update simple session fields atomically for the caller.
         Live session → setattr + _persist(); detached → direct DB UPDATE."""
         unknown = set(fields) - self._UPDATABLE_FIELDS
         if unknown:
             raise ValueError(f"non-updatable fields: {sorted(unknown)}")
         found = self.get_by_name(name, scope)
         if not found:
             return None
         if found.loaded:
             for k, v in fields.items():
                 setattr(found, k, v)
             found._persist()
         else:
             from app.db import _conn
             sets = ", ".join(f"{k}=?" for k in fields)
             vals = [int(v) if isinstance(v, bool) else v for v in fields.values()]
             with _conn() as c:
-                c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*vals, found.id))
+                cur = c.execute(
+                    f"UPDATE sessions SET {sets} WHERE id=?", (*vals, found.id),
+                )
+                if cur.rowcount == 0:
+                    # Молчаливый ноль здесь означал бы, что поля «сохранены» только
+                    # в памяти вызывающего, а в БД их нет (#54).
+                    logger.warning(
+                        "UPDATE sessions changed 0 rows: fields %s for id=%r not persisted",
+                        list(fields), found.id,
+                    )
         return found
 
     async def persist_lifecycle(
         self,
         session: AgentSession,
         *,
         branch: str,
         base_branch: str,
         task_id: str,
         needs_switch: bool,
     ) -> None:
         """Persist one Git lifecycle snapshot for loaded or detached sessions."""
         if session.loaded:
             await session._drain_persist()
         session.branch = branch
         session.base_branch = base_branch
         session.task_id = task_id
         session.needs_switch = needs_switch
         updated = await asyncio.to_thread(
             update_session_lifecycle,
diff --git a/app/routes/bg.py b/app/routes/bg.py
index e1e6afa23..7c2f2297c 100644
--- a/app/routes/bg.py
+++ b/app/routes/bg.py
@@ -13,40 +13,48 @@ class BgJobCreateRequest(BaseModel):
     type: str
     config: dict = {}
     message: str = ""
     target_name: str = ""
     target_scope: str = ""
     timeout_seconds: int = 3600
     created_by: str = ""
 
 
 @router.post("/jobs")
 async def bg_job_create(req: BgJobCreateRequest):
     from app.bg_jobs import bg_manager
     scope = req.target_scope.rstrip("/")
     name = req.target_name
     if not scope or not name:
         return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
     session = manager.get_by_name(name, scope)
     if not session:
         return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
     session_id = session.id
+    if not str(session_id or "").strip():
+        # Раньше пустой id уезжал в джоб и всплывал как 500 где-то ниже (#54).
+        # Отказ на границе: 400 с причиной, которую видно вызывающему агенту.
+        return JSONResponse(
+            {"error": f"session '{name}' has no id — it cannot be a background job target; "
+                      f"respawn the worker"},
+            status_code=400,
+        )
     result = await bg_manager.create(
         job_type=req.type, config=req.config, message=req.message,
         target_session_id=session_id, target_name=name, target_scope=scope,
         created_by=req.created_by, timeout_seconds=req.timeout_seconds,
     )
     if result.get("error"):
         return JSONResponse(result, status_code=400)
     return result
 
 
 @router.get("/jobs")
 async def bg_job_list(scope: str = "", session_id: str = ""):
     from app.db import bg_get_jobs
     return bg_get_jobs(scope=scope or None, session_id=session_id or None)
 
 
 @router.delete("/jobs/{job_id}")
 async def bg_job_cancel(job_id: str):
     from app.bg_jobs import bg_manager
     result = await bg_manager.cancel(job_id)
diff --git a/docs/orchestrator-vps-onboarding.md b/docs/orchestrator-vps-onboarding.md
index 43f6b4e95..96ff9f6cc 100644
--- a/docs/orchestrator-vps-onboarding.md
+++ b/docs/orchestrator-vps-onboarding.md
@@ -224,40 +224,52 @@ import sqlite3
 c = sqlite3.connect('/home/kesha/orchestra/data/orchestra.db')
 c.execute(\"update sessions set session_id='' where name='ТВОЁ-ИМЯ'\")
 c.execute(\"update sessions set model='claude-opus-5[1m]' where name='ТВОЁ-ИМЯ'\")
 c.commit()
 print('rows:', c.total_changes)
 "
 
 sudo systemctl start orchestra
 ```
 
 Три вещи, каждая из которых уже кого-то укусила:
 
 1. **`WHERE name='ТВОЁ-ИМЯ'`, никаких масок вроде `model LIKE 'claude-opus-4%'`** — заденешь
    чужие сессии. На живом сервере рядом с тобой работают другие.
 2. **Только при остановленном сервисе.** Живой сервер перезаписывает поля сессии из памяти,
    и твой `UPDATE` молча откатится. После рестарта — перепроверь `SELECT`.
 3. **Не `compact_worker`.** Компакт просит сессию законспектировать саму себя: устаревшие
    убеждения переезжают в конспект, но уже без исходника для перепроверки. Становится хуже,
    а выглядит как решение.
 
+**После каждого рестарта — одна строка проверки на строки-призраки:**
+
+```bash
+sqlite3 "file:/home/kesha/orchestra/data/orchestra.db?mode=ro" \
+  "SELECT COUNT(*) FROM sessions WHERE id IS NULL OR TRIM(COALESCE(id,''))='';"
+```
+
+Ответ обязан быть `0`. Не ноль — у такой сессии ВСЕ `UPDATE … WHERE id=?` меняют ноль строк
+молча: статус, `session_id` и счётчики навсегда остаются теми, что были при вставке, и
+резюмировать её после рестарта нечем. С #54 база такие строки больше не принимает (триггер
+`sessions_id_required_insert`), но уже лежащие она не чинит — это данные, и чинит их человек.
+
 **Модель пинить с `[1m]`.** Голый `claude-opus-5` даёт 200k контекста вместо 1M — теряешь
 800k молча.
 
 ### Если сессии нет вовсе, а скрипт применить нельзя
 
 Сюда попадаешь, только если у проекта нечего переносить (нет истории на ноуте) и нужна чистая
 сессия. **Руками `INSERT` в `sqlite` — нельзя**, по трём причинам:
 
 1. **Автосоздание не сработает.** `bootstrap.py:100 _ensure_orchestrator()` создаёт оркестратора
    только если в базе нет **ни одного** (`has_orch` → skip). На VPS он уже есть, так что
    бутстрап пройдёт мимо тебя, сколько ни рестартуй.
 2. **Живой сервер держит сессии в памяти** (`manager.py:1447 auto_resume_all`). Строка, вставленная
    в живую базу, серверу неизвестна, в дашборде не появится, а при следующей записи из памяти
    может быть затёрта — тот же механизм, из-за которого `UPDATE` при живом сервисе откатывается.
 3. **Полей больше, чем кажется.** `db.py:618 save_session()` проставляет около двадцати умолчаний
    (`context_pct`, `total_turns`, `template_hash`, `cost_usd_cached`, `backend_type`, `parent_id`,
    `pipeline`, `profile`…). Список из семи «очевидных» колонок пройдёт `INSERT` без ошибки и
    упадёт позже, в чужом месте и без связи с причиной.
 
 Правильно — вызвать тот же код, что создавал всех остальных:
diff --git a/docs/tasks/54/report.md b/docs/tasks/54/report.md
new file mode 100644
index 000000000..0e2e7533a
--- /dev/null
+++ b/docs/tasks/54/report.md
@@ -0,0 +1,102 @@
+# #54 — отчёт: строка-призрак в `sessions` больше не может появиться
+
+## Отрицательный результат, который важнее самого фикса
+
+**В живой БД чинить было нечего, и второго дефекта нет.** Проверено read-only до любых правок:
+
+```
+всего сессий: 23   |   id IS NULL: 0   |   id = '': 0   |   коротких id: 0
+seedon-orchestrator: id=09b75a6c-…(валидный uuid), session_id=1df2ba52-…,
+                     total_turns=121, cost_usd=19.01, status=idle
+```
+
+Строка из баг-репорта от 03.08 (`id=NULL`, `session_id=''`, `total_turns=0`, `cost 0.0`)
+сегодня не существует, а `seedon-orchestrator` живой и с контекстом — резюмировать его есть
+чем, рестарт ему ничем не грозил. Пункт «починить существующую строку» снят за отсутствием
+цели, оригинал живой БД не трогался вовсе.
+
+**Новые такие строки не появляются**: ноль на 23 сессии, включая созданные сегодня. Значит
+механизма, который продолжал бы писать пустой id, нет — искать его не надо.
+
+Разделение, которое это подсветило: **описание дефекта живёт дольше описания состояния.**
+Схемная дыра из того же репорта жива и подтверждена замером; данные из него мертвы через двое
+суток. Первое проверяется кодом, второе — базой, и обязательно сегодняшней.
+
+## Дыра подтверждена замером, а не чтением
+
+На копии живой БД:
+
+```
+INSERT (id=NULL) ×2       → вставлено строк с id=NULL: 2
+UPDATE … WHERE id=NULL    → изменено строк: 0
+```
+
+`id TEXT PRIMARY KEY` в SQLite пускает NULL. У такой сессии все `UPDATE … WHERE id=?`
+меняют ноль строк молча: статус, `session_id`, счётчики навсегда остаются теми, что были
+при вставке.
+
+## Что сделано — три уровня, потому что каждый по отдельности дырявый
+
+| уровень | что | зачем именно так |
+|---|---|---|
+| схема | `id TEXT PRIMARY KEY NOT NULL` | только для НОВЫХ БД: `CREATE TABLE IF NOT EXISTS` существующие не трогает |
+| база | триггеры `sessions_id_required_insert` / `…_update` | лечат УЖЕ СУЩЕСТВУЮЩИЕ БД (аддитивная миграция) и ловят то, что `NOT NULL` не ловит — **пустую строку**, дающую тот же призрак |
+| код | гард в `save_session` | падает громко с именем и scope: без него схема запретит вставку, а код получит ту же ошибку ниже и без объяснения |
+
+Почему триггер, а не перестройка таблицы: ужесточить колонку в SQLite можно только
+пересозданием, а на `sessions.id` завязан `logs … REFERENCES sessions(id) ON DELETE CASCADE` —
+перестройка на живой БД чужого проекта того не стоит.
+
+Плюс два пункта из задачи:
+- **громкий ноль строк**: `update_session_lifecycle`, `archive_session` и detached-ветка
+  `update_session_fields` пишут WARNING, если `rowcount == 0` — «ничего не изменилось» больше
+  не выглядит как «нечего менять»;
+- **400 вместо 500**: `app/routes/bg.py` отказывает на границе с внятным текстом
+  (`session 'X' has no id — it cannot be a background job target; respawn the worker`)
+  вместо падения где-то ниже.
+
+В `docs/orchestrator-vps-onboarding.md` добавлена строка проверки после рестарта
+(`SELECT COUNT(*) … WHERE id IS NULL OR TRIM(COALESCE(id,''))=''`, ответ обязан быть `0`)
+с оговоркой: триггер не чинит уже лежащие строки, это данные, их чинит человек.
+
+## Файлы
+
+| файл | ± |
+|---|---|
+| `app/db.py` | +40 (триггеры, `NOT NULL`, гард, два WARNING) |
+| `app/manager.py` | +8 (WARNING на detached-обновлении) |
+| `app/routes/bg.py` | +8 (400 на границе) |
+| `tests/test_session_id_guard.py` | +130 (новый, 12 тестов) |
+| `docs/orchestrator-vps-onboarding.md` | +14 (проверка после рестарта) |
+
+## Проверки
+
+```
+tests/test_session_id_guard.py                                   12 passed (3 прогона подряд)
+test_db + test_manager + test_bg_jobs + test_session_id_guard    257 passed, 1 skipped
+test_api + test_undelivered + test_auto_report_undelivered       123 passed
+```
+
+Мутация — откат `app/db.py` через `git show HEAD^:app/db.py > app/db.py`
+(`git checkout` не набирал): **10 failed, 2 passed**. Зелёными по обе стороны остались
+ровно два теста, которые и должны: «валидный id сохраняется» и «bg_create отвечает 400» —
+второй живёт в другом файле.
+
+Отдельный тест воспроизводит **дофиксовую БД**: схема откатывается к варианту без `NOT NULL`
+и без триггеров, в неё вставляется строка-призрак, затем `init_db()` (то есть рестарт сервиса)
+— после миграции новый призрак не вставляется, а уже лежащий остаётся нетронутым. Это и есть
+граница между «фикс схемы» и «фикс данных», проверенная, а не заявленная.
+
+## Вердикта Codex нет
+
+Codex недоступен до 08.08. Самокритика:
+
+1. **Триггер не проверялся на живой БД** — только на копии и на временных. Он аддитивный
+   (`CREATE TRIGGER IF NOT EXISTS` в `_migrate`), но применится он при ближайшем `init_db()`,
+   то есть при рестарте, и до этого момента живая база остаётся без него.
+2. **`TRIM(NEW.id) = ''` ловит пробельный id, но не «мусорный»** — строку из одного символа
+   или чужой формат он пропустит. Формат id (uuid) нигде не валидируется, и я этого не менял:
+   это уже не «призрак», а другая тема.
+3. **Почему id стал NULL в тот раз — неизвестно.** Я закрыл возможность, а не нашёл причину:
+   строки нет, аудита нет, воспроизвести не на чем. Если призрак появится снова — теперь он
+   упрётся в триггер и будет виден сразу, с именем и scope в тексте ошибки.
diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index ae88d97ea..56f3f8ffd 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -29,40 +29,48 @@
   uvicorn; одно и то же переключение даёт 64 мс или 1555 мс при НУЛЕ сетевых запросов.
   Печатать значение, но не судить — `check_perf` в `docs/tasks/8/verify-switch.py`.
 
 ## Браузерные прогоны на живом :8888
 
 - **Авторизация только заголовком**: `new_context(extra_http_headers={"Authorization":
   f"Bearer {INTERNAL_TOKEN}"})`. Логин формой не прилипает — `/api/*` отвечает 401.
 - **Подмена JS — только шаблоном со звёздочкой**: `page.route("**/static/js/app.js*")`.
   Статика едет как `?v=<mtime>`, и шаблон без `*` тихо не матчит — прогон зеленеет на коде
   из `main`. Страховка: первым делом ждать символ, которого в `main` нет
   (`wait_for_function("typeof <новая функция> === 'function'")`).
 - **Не звать `await response.body()` на SSE** — тело не кончается, скрипт виснет намертво.
   Фильтровать по `content-type: text/event-stream` до чтения.
 - **Байты SSE на проводе** — сырым TLS-сокетом с `settimeout(1.5)`; `curl` сам не завершится.
   Мерить на ПРОСТАИВАЮЩЕМ агенте, иначе в счёт попадут живые события.
 - **Скрытую вкладку в headless не сымитировать**: ни `bring_to_front()`, ни CDP
   `setWebLifecycleState: frozen` не меняют `visibilityState`. Либо машина юзера, либо UNCERTAIN.
 - **Обрыв соединения — только `Popen` + `kill()`.** `ThreadingHTTPServer.shutdown()`
   оставляет открытый SSE живым, и это выглядит как «поток пережил рестарт».
 
+## Баг-репорт = две разные части, и протухают они по-разному
+
+«В коде дыра» проверяется кодом и живёт долго. «В базе такая строка» проверяется базой и
+мертво уже через сутки. В #54 схемная дыра подтвердилась замером, а описанная строка
+исчезла за двое суток — и на ней стояла вся срочность. Сначала `SELECT` по текущему
+состоянию, потом планирование, и **отрицательный результат сообщать сразу**: он снимает
+чужие ложные доводы (у оркестратора это был довод про рестарт).
+
 ## Факты про этот проект, на которые я уже опирался
 
 - **Запись в `logs` видит ДАШБОРД, а не агент.** `get_logs` читается только для
   `_build_runtime_handoff` (`session.py:1519`) и берёт ТОЛЬКО `user_message` и `text`;
   `system` отфильтровывается. «Оставим строку в его истории — прочитает на следующем ходу»
   неверно: до агента доходит только доставленное сообщение.
 - **`tool_result` не создаёт своего узла в чате** — вливается в строку инструмента выше,
   а `data-chat-log-id` там от другой строки. Прежде чем вешать что-то на узел — проверь
   замером, что узел существует (в #8 вышла 1 пометка на 6 строк).
 - **Цифры КЛИЕНТА — из журнала, а не из своего браузера**: `journalctl -u orchestra
   -o short-precise` для таймингов старта, `/var/log/nginx/access.log` — что и когда просил
   ЕГО браузер. Тишина в access.log при открытой странице = клиент перестал слать запросы.
 - **Живая БД для замеров**: `sqlite3.connect("file:.../orchestra.db?mode=ro", uri=True)`.
   Бюджет истории считать в БАЙТАХ: p50=222 Б при max=651 КБ, 16 сообщений держат 67 % объёма.
 - **Новый Jinja-глобал в шаблоне кладёт прод в окне мерж→рестарт**: `UndefinedError` → `/`
   отдаёт 500. Писать `{{ x() if x is defined else '' }}` и покрывать тестом.
 
 ## Тесты: ловушки, на которых я уже терял время
 
 - **Константа в СИГНАТУРЕ не подменяется monkeypatch'ем** — значение по умолчанию считается
diff --git a/tests/test_session_id_guard.py b/tests/test_session_id_guard.py
new file mode 100644
index 000000000..1bf6a5e60
--- /dev/null
+++ b/tests/test_session_id_guard.py
@@ -0,0 +1,143 @@
+"""#54 — строка-призрак: сессия с пустым id существует, но ни один UPDATE до неё не доходит.
+
+Замер на копии живой БД (Phase 1): `id TEXT PRIMARY KEY` пустил ДВЕ строки с `id=NULL`,
+а `UPDATE … WHERE id=NULL` изменил ноль строк. Здесь это закрыто на трёх уровнях: схема,
+триггер (для уже существующих БД) и гард в коде.
+"""
+import logging
+import sqlite3
+import uuid
+from datetime import datetime, timezone
+
+import pytest
+
+
+@pytest.fixture
+def db(tmp_path, monkeypatch):
+    import app.db as dbmod
+
+    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
+    dbmod.init_db()
+    return dbmod
+
+
+def _row(sid="", name="worker"):
+    return {
+        "id": sid, "name": name, "scope": "/s", "cwd": "/s", "model": "claude-sonnet-5[1m]",
+        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
+        "worktree_path": "", "branch": "", "base_branch": "main",
+        "is_orchestrator": False, "color": "",
+        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
+        "task_id": "", "needs_switch": 0,
+    }
+
+
+class TestGuardInCode:
+    @pytest.mark.parametrize("bad", ["", "   ", None])
+    def test_save_session_refuses_empty_id_loudly(self, db, bad):
+        with pytest.raises(ValueError) as e:
+            db.save_session(_row(bad))
+        assert "session id is required" in str(e.value)
+        assert "worker" in str(e.value), "в тексте должно быть видно, о какой сессии речь"
+
+    def test_valid_id_still_saves(self, db):
+        sid = str(uuid.uuid4())
+        db.save_session(_row(sid))
+        assert db.get_session(sid)["name"] == "worker"
+
+
+class TestGuardInDatabase:
+    """Гард в коде обходится любым прямым INSERT — база обязана защищаться сама."""
+
+    @pytest.mark.parametrize("bad", [None, "", "   "])
+    def test_direct_insert_is_rejected_by_trigger(self, db, bad):
+        with pytest.raises(sqlite3.IntegrityError) as e:
+            with db._conn() as c:
+                c.execute(
+                    "INSERT INTO sessions (id, name, scope, cwd, model, created_at) "
+                    "VALUES (?, 'ghost', '/s', '/s', 'm', '2026-08-04')", (bad,),
+                )
+        assert "sessions.id must be non-empty" in str(e.value)
+
+    def test_update_cannot_blank_an_existing_id(self, db):
+        sid = str(uuid.uuid4())
+        db.save_session(_row(sid))
+        with pytest.raises(sqlite3.IntegrityError):
+            with db._conn() as c:
+                c.execute("UPDATE sessions SET id='' WHERE id=?", (sid,))
+        assert db.get_session(sid) is not None
+
+    def test_existing_database_gets_the_trigger_on_migration(self, tmp_path, monkeypatch):
+        """БД, созданная ДО фикса, чинится миграцией: та же схема, триггеров ещё нет."""
+        import app.db as dbmod
+
+        old = tmp_path / "old.db"
+        monkeypatch.setattr(dbmod, "DB_PATH", old)
+        dbmod.init_db()
+        # Откатываем схему к дофиксовой: тот же набор колонок, но без NOT NULL и без
+        # триггеров — ровно та БД, что лежит у нас в проде с мая.
+        with dbmod._conn() as c:
+            ddl = c.execute(
+                "SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'"
+            ).fetchone()[0]
+            c.executescript(f"""
+                PRAGMA foreign_keys=OFF;
+                DROP TRIGGER sessions_id_required_insert;
+                DROP TRIGGER sessions_id_required_update;
+                ALTER TABLE sessions RENAME TO sessions_pre_fix;
+                {ddl.replace("id TEXT PRIMARY KEY NOT NULL", "id TEXT PRIMARY KEY")};
+                INSERT INTO sessions SELECT * FROM sessions_pre_fix;
+                DROP TABLE sessions_pre_fix;
+            """)
+            c.execute("INSERT INTO sessions (id, name, scope, cwd, model, created_at) "
+                      "VALUES (NULL, 'ghost', '/s', '/s', 'm', '2026-08-03')")
+            ghosts = c.execute(
+                "SELECT COUNT(*) FROM sessions WHERE id IS NULL").fetchone()[0]
+        assert ghosts == 1, "предпосылка теста: до фикса строка-призрак вставляется"
+
+        dbmod.init_db()  # повторный запуск сервиса = миграция
+        with pytest.raises(sqlite3.IntegrityError):
+            with dbmod._conn() as c:
+                c.execute("INSERT INTO sessions (id, name, scope, cwd, model, created_at) "
+                          "VALUES (NULL, 'ghost2', '/s2', '/s', 'm', '2026-08-04')")
+        # уже лежащую строку триггер не трогает — это данные, их чинит человек
+        with dbmod._conn() as c:
+            assert c.execute(
+                "SELECT COUNT(*) FROM sessions WHERE id IS NULL").fetchone()[0] == 1
+
+
+class TestSilentZeroRowUpdateIsLoud:
+    def test_lifecycle_update_warns_when_nothing_changed(self, db, caplog):
+        with caplog.at_level(logging.WARNING):
+            ok = db.update_session_lifecycle(
+                "нет-такой-сессии", branch="b", base_branch="main",
+                task_id="", needs_switch=False,
+            )
+        assert ok is False
+        assert any("changed 0 rows" in r.getMessage() for r in caplog.records)
+
+    def test_archive_warns_when_nothing_changed(self, db, caplog):
+        with caplog.at_level(logging.WARNING):
+            db.archive_session("нет-такой-сессии")
+        assert any("changed 0 rows" in r.getMessage() for r in caplog.records)
+
+
+@pytest.mark.asyncio
+async def test_bg_create_answers_400_not_500_for_a_session_without_id(db, monkeypatch):
+    import json
+
+    import app.routes.bg as bgmod
+
+    class Ghost:
+        id = ""
+        name = "ghost"
+
+    monkeypatch.setattr(bgmod.manager, "get_by_name", lambda *_a: Ghost())
+    resp = await bgmod.bg_job_create(bgmod.BgJobCreateRequest(
+        type="timer", config={"delay_seconds": 5}, message="проверка",
+        target_name="ghost", target_scope="/s", created_by="test",
+    ))
+    body = json.loads(resp.body)
+    print("\nbg_create →", resp.status_code, body["error"])
+    assert resp.status_code == 400
+    assert "has no id" in body["error"]


## Later history of the touched files on main (after this commit)

165 later commits touch these paths; the first 40 (oldest first):
0d3975b02 2026-08-04 #56: #56: исследование — репорт пишется в стор и на этом всё; адресат вычислим, семь старых разобраны
10d1a858b 2026-08-04 #61: #61: исследование — конфликт только когда база доработала те же строки; критерий из git недоступен
ef9c8057b 2026-08-04 #62: #62: фаза 1 — рабочие копии сносит pytest в главном чекауте, воспроизведено
750d0d0b2 2026-08-04 #50: #50: исследование — точка врезки в send() измерена, очередь обязана быть durable
7a6f0ab75 2026-08-04 #69: #69: репозиторий воркера от git, слаг от repo root; strategy=parent через границу репо
84d58f6a0 2026-08-04 #52: #52: исследование — N-1 конфликт по построению, правило не выполняется 0 из 8, материал уже есть в отчётах
6c279201d 2026-08-04 #65: #65: system_prompt и last_summary убраны из списка сессий — 54.3 → 4.5 КБ по проводу
262b38b5b 2026-08-04 #71: #71: исследование — 92.8% провода даёт одно поле, второй вызов от нулевого дросселя
d1109cefc 2026-08-04 #72: #72: холодная синхронизация без предзагрузки, история порциями по байтам
b941a9558 2026-08-04 #74: #74: потолок на строку, видимый маркер обрезки и загрузка строки целиком
6f97d535a 2026-08-04 #78, #80: #78: исследование — оценка подтверждена своим замером, но retention логов не существует, а копировать надо не файл
9f777f912 2026-08-04 Squashed commits: - #82: исследование — имя как внешний ключ в трёх слоях, тихий путь не тот, что в репорте - #82: план — env чинится пересборкой, сохранённые ссылки предпочитают id, 4 тикета - #82: T1 — bg-джобы будят по неизменяемому id, а не по имени - WIP #82: T2 наполовину — в session.py есть флаг _identity_stale и его гашение на границе хода; НЕ сделано: manager.refresh_identity (пересборка mcp_servers) и вызов из rename_session, весь T3, T4 - #82: T2 — переименование пересобирает MCP-идентичность, перезапуск на границе хода - #82: T3 — держатель тест-лока по неизменяемому id, дети переименованного родителя - #82: T4 — живой прогон переименования, отчёт и личная память
991b246c7 2026-08-06 #137: #137: разбор Prime Agent — заявка 30.2→95.5 разложена по первоисточникам, механика по коду, что применимо к Orchestra
74376dac7 2026-08-06 #159: #159: research — инструкция по переезду уже существует, проверка фактов на VPS
beb777cb4 2026-08-06 Squashed commits: - #160: исследование — graceful shutdown затирает 'running', пробуждение не срабатывает - #160: сохранить признак прерванности через graceful-рестарт - #160: тесты пробуждения после рестарта, отчёт, личная память
ab4d0f209 2026-08-06 #165: #165: исследование — без рестарта переезжает всё, кроме истории диалога
36de7dd94 2026-08-06 #167: #167: ошибка обязана назвать себя — один владелец вместо четырёх копий
8ebed917e 2026-08-07 #150: #150: молчащий источник usage пишет NULL и строку в журнал вместо нуля
23aea94ca 2026-08-07 Merge remote-tracking branch 'origin/main'
bff96d941 2026-08-07 #162: #162: research — курс 5h→7d измерен, в недельный лимит влезает ~7 пятичасовых окон
647452c1c 2026-08-08 #168: #168: research centralized weekly quota gate
c1a635533 2026-08-09 #169: WIP #169: research awaiting Codex quota
afc99e2de 2026-08-10 #173: #173: fix prompt P0 defects
05e9a8062 2026-08-11 #174: #174: import DB history into Claude
3fbd7054f 2026-08-11 #186: #186: T2 — база недельного окна: последний монотонный отрезок, честный ноль сохранён
66ad6a69f 2026-08-11 #186: #186: T3 — храповик предупреждения на схеме и латч молчания
e18ea6b43 2026-08-11 #187: #187: add atomic quota-aware runtime router state
b6444aeeb 2026-08-11 #186: #186: T4 — доставка текста в TG и цикл предупреждения (без проводки в маршрут)
6b2249c59 2026-08-12 #214: #214: эффорт по модели — карта модель→ступень в манифесте
6dac7dcbf 2026-08-12 #220: #220: план фазы 2 — T1 пересборка промпта, T2/T3 дренаж, красные тесты тикетов
6712fdcf4 2026-08-12 #219, #223: #219 T2: контракт делегирования «таблица, а не область» в worker-lifecycle + тесты на происхождение якорей (первая редакция теста была ложно-зелёной на составной мутации)
9b1b48b54 2026-08-12 #219: #219 T1b: красные тесты проводки — два гейта, killed-токен, девять неприкосновенных путей
f5910ff9c 2026-08-12 #224: #224: plan + acceptance tests committed RED (T1-T7)
d986be3c1 2026-08-12 #193: #193: add red subrepo memory regression test
9fc4534e5 2026-08-12 #231: #231: предрегистрация эксперимента (стенд, критерий, все четыре исхода) — ДО спавна плеч
a01a4b2aa 2026-08-13 #230: #230: план фазы 2 + красные оракулы T1-T5 (заглушки, 8 failed)
21b46c82f 2026-08-13 #226: #226: freeze unpriced Codex turn oracle
7cb9b324e 2026-08-13 #230: #230: три находки независимой проверки — гейт на futures, оракул по leftover, start_time до сброса
5c346ffd5 2026-08-13 #227: #227: enforce worker model policy at spawn
59ee1b11c 2026-08-13 #227: #227: gate Opus by Claude weekly pace

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 0d3975b02 #56: #56: исследование — репорт пишется в стор и на этом всё; адресат вычислим, семь старых разобраны

diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 56f3f8ffd..d23966955 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -52,10 +52,18 @@
 мертво уже через сутки. В #54 схемная дыра подтвердилась замером, а описанная строка
 исчезла за двое суток — и на ней стояла вся срочность. Сначала `SELECT` по текущему
 состоянию, потом планирование, и **отрицательный результат сообщать сразу**: он снимает
 чужие ложные доводы (у оркестратора это был довод про рестарт).
 
+## «Живая проверка» на неразвёрнутом коде — это половина проверки
+
+`app/routes/` живёт в памяти systemd до рестарта, поэтому мой новый роут на живом сервере
+не исполняется. Подать настоящий запрос можно (он ляжет в стор), а увидеть новое поведение —
+нет. Говорить это ПРЯМО и называть, какая половина проверена: в #56 подача живая, приём —
+сквозным прогоном. `app/mcp_stdio.py` при этом подхватывается сразу — асимметрия видна
+только если про неё помнить.
+
 ## Факты про этот проект, на которые я уже опирался
 
 - **Запись в `logs` видит ДАШБОРД, а не агент.** `get_logs` читается только для
   `_build_runtime_handoff` (`session.py:1519`) и берёт ТОЛЬКО `user_message` и `text`;
   `system` отфильтровывается. «Оставим строку в его истории — прочитает на следующем ходу»
### 10d1a858b #61: #61: исследование — конфликт только когда база доработала те же строки; критерий из git недоступен

diff --git a/app/db.py b/app/db.py
index 44ca8786d..9adb60396 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1788,5 +1788,38 @@ def release_test_lock(scope: str, holder: str) -> bool:
 def get_test_lock(scope: str) -> dict | None:
     """Текущий держатель лока для scope или None."""
     with _conn() as c:
         row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
         return dict(row) if row else None
+
+
+def find_merge_proof(scope: str, branch: str) -> dict | None:
+    """Доказательство, что ветка УЖЕ слита в базу (#61).
+
+    После сквош-мержа git этого доказать не может: предок не сохраняется, а сравнение
+    деревьев (`branch_content_status`) даёт «конфликт», как только база правит те же
+    строки. Единственный надёжный источник — наша собственная запись об операции.
+
+    Возвращает {"heads": [...], "operation_id": ...} с головами, на которых мерж
+    состоялся: принятой при приёме операции и фактически слитой (они расходятся, когда
+    воркер дописал коммит во время ожидания хода — BENIGN_ADVANCE из #17).
+    """
+    scope = (scope or "").rstrip("/")
+    with _conn() as c:
+        row = c.execute(
+            """SELECT operation_id, accepted_worker_head, result_json
+                 FROM merge_operations
+                WHERE scope = ? AND accepted_worker_branch = ?
+                  AND state = 'SUCCEEDED' AND commit_point = 'REACHED'
+                ORDER BY rowid DESC LIMIT 1""",
+            (scope, branch),
+        ).fetchone()
+    if not row:
+        return None
+    heads = {row["accepted_worker_head"]}
+    try:
+        merged = (json.loads(row["result_json"]).get("git") or {}).get("worker_head")
+    except (ValueError, TypeError, AttributeError):
+        merged = None
+    if merged:
+        heads.add(merged)
+    return {"operation_id": row["operation_id"], "heads": sorted(h for h in heads if h)}
diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index d23966955..3ede954ef 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -60,10 +60,24 @@
 не исполняется. Подать настоящий запрос можно (он ляжет в стор), а увидеть новое поведение —
 нет. Говорить это ПРЯМО и называть, какая половина проверена: в #56 подача живая, приём —
 сквозным прогоном. `app/mcp_stdio.py` при этом подхватывается сразу — асимметрия видна
 только если про неё помнить.
 
+## После сквош-мержа git НЕ может доказать, что работа в базе
+
+Предка сквош не сохраняет (`--is-ancestor` → нет), а сравнение деревьев
+(`branch_content_status`) даёт `conflict`, как только база правит те же строки — то есть
+врёт ровно в том случае, который ломается. Доказательство брать из своей записи:
+`merge_operations` (`state='SUCCEEDED' AND commit_point='REACHED'`, `accepted_worker_branch`
++ голова). Готовый хелпер — `db.find_merge_proof()`; он же учитывает, что при
+`BENIGN_ADVANCE` из #17 слитая голова отличается от принятой.
+
+## `UV_CACHE_DIR` на этом VPS — `/home/kesha/.cache/uv`
+
+`/mnt/data` тут нет (это путь с ноутбука), а `/tmp` — часть корневого раздела, не tmpfs
+(`findmnt /tmp` пусто, 254 ГБ свободно). Кеш всё равно держать на своём диске, а не в `/tmp`.
+
 ## Факты про этот проект, на которые я уже опирался
 
 - **Запись в `logs` видит ДАШБОРД, а не агент.** `get_logs` читается только для
   `_build_runtime_handoff` (`session.py:1519`) и берёт ТОЛЬКО `user_message` и `text`;
   `system` отфильтровывается. «Оставим строку в его истории — прочитает на следующем ходу»
### ef9c8057b #62: #62: фаза 1 — рабочие копии сносит pytest в главном чекауте, воспроизведено

diff --git a/app/manager.py b/app/manager.py
index e57598566..7639f832e 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -408,10 +408,17 @@ class SessionManager:
 
     def start_background_tasks(self) -> None:
         # log retention REMOVED by owner decision: agent history is research data. The old
         # `_periodic_db_cleanup` dropped logs older than 7 days every 6h, silently destroying
         # every transcript past a week while `sessions` rows survived since May. Never restore
+        # Never under pytest: every TestClient(app) enters lifespan, and a test that points
+        # app.db at a temporary database while WORKTREE_ROOT still points at the real
+        # checkout deletes every clean working copy of every project (docs/tasks/62 —
+        # reproduced: one green `pytest tests/test_build_signal.py` erased both decoys).
+        if "pytest" in sys.modules:
+            logger.warning("worktree cleanup task not started: running under pytest")
+            return
         if not getattr(self, '_wt_cleanup_task', None) or self._wt_cleanup_task.done():
             self._wt_cleanup_task = asyncio.create_task(self._periodic_worktree_cleanup())
 
     @staticmethod
     def _ownership_prompt(owned_dirs: list[str]) -> str:
### 750d0d0b2 #50: #50: исследование — точка врезки в send() измерена, очередь обязана быть durable

diff --git a/app/db.py b/app/db.py
index 9adb60396..d774dc83d 100644
--- a/app/db.py
+++ b/app/db.py
@@ -69,10 +69,18 @@ def init_db() -> None:
                 last_summary TEXT DEFAULT '',
                 created_at TEXT NOT NULL,
                 finished_at TEXT,
                 UNIQUE(name, scope)
             );
+            CREATE TABLE IF NOT EXISTS undelivered_facts (
+                id INTEGER PRIMARY KEY AUTOINCREMENT,
+                session_id TEXT NOT NULL,
+                dedupe_key TEXT NOT NULL,
+                text TEXT NOT NULL,
+                created_at TEXT NOT NULL,
+                UNIQUE(session_id, dedupe_key)
+            );
             CREATE TABLE IF NOT EXISTS profiles (
                 name TEXT PRIMARY KEY,
                 config_dir TEXT NOT NULL DEFAULT '',
                 created_at TEXT DEFAULT CURRENT_TIMESTAMP
             );
@@ -1821,5 +1829,62 @@ def find_merge_proof(scope: str, branch: str) -> dict | None:
     except (ValueError, TypeError, AttributeError):
         merged = None
     if merged:
         heads.add(merged)
     return {"operation_id": row["operation_id"], "heads": sorted(h for h in heads if h)}
+
+
+# Потолок фактов на сессию. Цифра НЕ измерена: недоставки редки по построению, мерить
+# было бы не на чем. Переполнение не отбрасывается молча — оно сворачивается в видимую
+# строку, поэтому реальный масштаб станет виден на первом же инциденте (#50).
+FACTS_PER_SESSION = 20
+
+
+def enqueue_fact(session_id: str, dedupe_key: str, text: str) -> bool:
+    """Поставить в очередь ФАКТ недоставки для сессии. Повтор того же события — не дубль.
+
+    Очередь durable намеренно: недоставка и рестарт — один и тот же сценарий, и очередь
+    в памяти (`_pending_messages`, P1 из #35) терялась бы ровно тогда, когда нужна.
+    """
+    with _conn() as c:
+        cur = c.execute(
+            """INSERT INTO undelivered_facts (session_id, dedupe_key, text, created_at)
+               VALUES (?, ?, ?, ?)
+               ON CONFLICT(session_id, dedupe_key) DO NOTHING""",
+            (session_id, dedupe_key, text, datetime.now(timezone.utc).isoformat()),
+        )
+        return cur.rowcount == 1
+
+
+def peek_facts(session_id: str, limit: int = FACTS_PER_SESSION) -> dict:
+    """Факты для показа агенту: последние `limit` плюс число свёрнутых старых.
+
+    Ключи возвращаются ВСЕ, включая свёрнутые: их существование агенту сообщено, значит
+    гасить надо и их — иначе счётчик «и ещё N» рос бы вечно.
+    """
+    with _conn() as c:
+        rows = c.execute(
+            """SELECT dedupe_key, text, created_at FROM undelivered_facts
+                WHERE session_id = ? ORDER BY id""",
+            (session_id,),
+        ).fetchall()
+    if not rows:
+        return {"facts": [], "collapsed": 0, "keys": []}
+    shown = rows[-limit:] if limit > 0 else []
+    return {
+        "facts": [{"text": r["text"], "created_at": r["created_at"]} for r in shown],
+        "collapsed": len(rows) - len(shown),
+        "keys": [r["dedupe_key"] for r in rows],
+    }
+
+
+def ack_facts(session_id: str, keys: list[str]) -> int:
+    """Погасить факты, которые ДОШЛИ. Зовётся только после возврата из backend.send."""
+    if not keys:
+        return 0
+    with _conn() as c:
+        cur = c.execute(
+            f"DELETE FROM undelivered_facts WHERE session_id = ? AND dedupe_key IN "
+            f"({','.join('?' * len(keys))})",
+            (session_id, *keys),
+        )
+        return cur.rowcount
diff --git a/app/manager.py b/app/manager.py
index 7639f832e..a009a7f5d 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -103,10 +103,24 @@ async def wait_for_session_lock(lock, *, what: str, worker: str, limit: float |
         yield waited
     finally:
         lock.release()
 
 
+def _auto_report_key(worker_session, worker_name: str) -> str:
+    """Ключ дедупликации автоотчёта (#50).
+
+    Стабильного id хода в системе нет: `_turn_gen` — счётчик в памяти сессии, он
+    обнуляется рестартом. Поэтому ключ строится из id сессии и номера хода, а когда
+    сессия недоступна — из имени и времени, и это ВИДНО в самом ключе (`notrack`).
+    Два быстрых автоотчёта тогда дадут две записи; это лучше, чем невидимо склеить
+    два разных события в одно.
+    """
+    if worker_session is not None:
+        return f"autoreport:{worker_session.id}:{getattr(worker_session, '_turn_gen', 0)}"
+    return f"autoreport:{worker_name}:notrack:{datetime.now(timezone.utc).isoformat()}"
+
+
 def next_adhoc_branch(worker_name: str) -> str:
     """Имя ветки для авто-переключения перед доставкой сообщения.
 
     Секунды эпохи БЕЗ усечения. Прежняя форма `str(int(time.time()))[-6:]` замыкала
     пространство имён каждые 10**6 с = 11.57 суток, а ветки `adhoc-*` не удаляются —
@@ -1489,10 +1503,11 @@ class SessionManager:
             self,
             scope=worker_scope,
             worker=worker_name,
             what="автоотчёт",
             reason=detail,
+            dedupe_key=_auto_report_key(worker_session, worker_name),
         )
         # Причина не дублируется: в исходе попытки она чаще всего та же самая, и запись
         # раздувается вдвое ровно там, где её будет читать человек.
         if detail in attempt:
             attempt = attempt.replace(detail, "та же причина")
diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 3ede954ef..393b9b842 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -105,7 +105,13 @@
   выдуманные пути (`/wt`), на которых настоящий git падает.
 - **`/tmp/live_copy.db` делят три скрипта #8**: путь писать абсолютным
   (`/home/kesha/orchestra/data/orchestra.db`) и пересоздавать копию, если в ней нет таблицы
   `logs` — после промаха остаётся ПУСТОЙ файл, и прогон падает посреди страницы.
 - **Тестовые значения в HTTP-заголовках — только ASCII**: кириллица доезжает mojibake.
+- **Сессия, начавшая ход, вешает TEARDOWN**: мок `events()` ждёт вечно, слушающая задача
+  живёт после теста, и прогон висит МИНУТАМИ при зелёном тесте («1 passed, 1 error»).
+  В уборке фикстуры — `await session.stop()`, потом отмена задач.
+- **`make_backend_mock()` это `AsyncMock`**: любой `getattr(backend, "флаг", False)`
+  истинен. Из-за `resume_failed` сессия уходила в ветку восстановления транскрипта и молча
+  затирала `runtime_handoff`. Флаги, которые читает код, ставить в моке ЯВНО.
 - **Файл тестов внезапно висит минутами → `--timeout=30`.** Обычно чужой стаб разошёлся с
   сигнатурой, а выглядит как «мои правки всё сломали». Сначала timeout, потом паника.
### 7a6f0ab75 #69: #69: репозиторий воркера от git, слаг от repo root; strategy=parent через границу репо

diff --git a/app/manager.py b/app/manager.py
index a009a7f5d..58bb7b3e4 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -26,10 +26,11 @@ from app.prompting import (
 _TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
 from app.workspace import (
     create_worktree, discard_prepared_worktree, remove_worktree,
     parse_owned_dirs, dirs_overlap,
     validate_repo_root, resolve_base_branch as resolve_git_base_branch,
+    repo_root,
 )
 from app.models import (
     CONTEXT_LIMITS,
     available_models_block,
     backend_for_model,
@@ -405,10 +406,25 @@ def _make_mcp_config(name: str, scope: str, role: str = "worker",
                 continue
             cfg[k] = v
     return cfg
 
 
+def _crosses_repo_boundary(parent_dir: str, child_repo: str) -> bool:
+    """Родитель и ребёнок в РАЗНЫХ репозиториях? Спрашиваем git, а не сравниваем пути.
+
+    Каталог `seedon/site` лежит внутри `seedon`, но это другой репозиторий; префиксное
+    сравнение путей ответило бы «тот же» (#69). Не смогли определить — считаем, что
+    граница НЕ пересечена: тогда исходная ошибка о ненайденной ветке уйдёт наверх как есть,
+    без выдуманного объяснения.
+    """
+    try:
+        return repo_root(parent_dir) != repo_root(child_repo)
+    except Exception as exc:
+        logger.warning("не смог сравнить репозитории '%s' и '%s': %s", parent_dir, child_repo, exc)
+        return False
+
+
 class SessionManager:
     def __init__(self):
         self.sessions: dict[str, AgentSession] = {}
         self._session_locks: dict[str, asyncio.Lock] = {}
         self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
@@ -1268,21 +1284,39 @@ class SessionManager:
         except FileNotFoundError:
             rr = None
         if rr is None or rr.base_branch_strategy == "main":
             return resolve_git_base_branch(repo_path)
         parent_branch = ""
+        parent_dir = ""
         if parent_name:
             ps = self.get_by_name(parent_name, scope)
             if ps is not None:
                 parent_branch = ps.branch or ""
+                parent_dir = ps.worktree_path or ps.cwd or ""
         if not parent_branch:
             logger.warning(
                 "base_branch_strategy=parent, но у родителя '%s' нет ветки — "
                 "resolving repository mainline",
                 parent_name)
             return resolve_git_base_branch(repo_path)
-        return resolve_git_base_branch(repo_path, parent_branch)
+        try:
+            return resolve_git_base_branch(repo_path, parent_branch)
+        except ValueError:
+            # Ветка родителя может жить в ДРУГОМ репозитории: в одном scope их бывает
+            # несколько (у seedon `site/` и `infra/` — свои git root'ы со своими origin).
+            # «Ответвись от родителя» через границу репозитория не значит ничего — там
+            # другая история. Берём mainline репозитория РЕБЁНКА, но громко: молчаливая
+            # подмена базы хуже отказа. Если репозиторий ТОТ ЖЕ, отсутствие ветки —
+            # настоящая ошибка, и она летит дальше (#69).
+            if parent_dir and _crosses_repo_boundary(parent_dir, repo_path):
+                logger.warning(
+                    "base_branch_strategy=parent: ветка '%s' родителя '%s' живёт в другом "
+                    "репозитории (%s), воркер спавнится в %s — база взята из mainline его "
+                    "репозитория",
+                    parent_branch, parent_name, parent_dir, repo_path)
+                return resolve_git_base_branch(repo_path)
+            raise
 
     @staticmethod
     def _role_is_orchestrator(pipeline: str, role: str) -> bool:
         """R1: is_orchestrator из kind манифеста; fallback на frozenset апстрима.
 
### 84d58f6a0 #52: #52: исследование — N-1 конфликт по построению, правило не выполняется 0 из 8, материал уже есть в отчётах

diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 393b9b842..82b9025ea 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -12,10 +12,16 @@
   `git show <commit>:<файл> > <файл>`, возврат — тем же способом из своего коммита.
 - **Сервис `orchestra` не рестартую.** Замеры, требующие рестарта, — через оркестратора.
 
 ## Доказательства: чем зелёное отличается от проверенного
 
+- **Свежий `git init` даёт `master`, а не `main`.** `git checkout main` тихо падает, ветки
+  ложатся в одну цепочку, и стенд показывает «конфликтов нет» там, где их не могло быть.
+  В стенде — `git branch -M main` сразу после init, и проверять предпосылку, а не вывод.
+- **«Успешно» в выводе скрипта — не доказательство.** Мой же `--seed` печатал «отсечка
+  проставлена», пока узкий regex не матчил метку: сообщение было, эффекта нет. Проверять
+  СЛЕДУЮЩЕЙ командой, а не сообщением об успехе.
 - **Мутация — единственная улика.** Когда файл ветки совпадает с тем, что отдаёт сервер
   (после мержа — всегда), неприменившийся стаб выглядит как применившийся. Ломай нарочно:
   проверка ОБЯЗАНА покраснеть. Харнесс для браузерных прогонов — `docs/tasks/8/mutation-check.py`;
   для кода — откат файла через `git show`. Мутация должна падать сама, если её якорь исчез.
 - **`all([]) == True`.** Проверка, агрегирующая собранное на лету (DOM, файлы, логи), при
### 6c279201d #65: #65: system_prompt и last_summary убраны из списка сессий — 54.3 → 4.5 КБ по проводу

diff --git a/app/manager.py b/app/manager.py
index 58bb7b3e4..ccf0f7822 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1563,10 +1563,21 @@ class SessionManager:
                     session.name, type(log_error).__name__, log_error,
                 )
 
     # ── Listings ──
 
+    # Поля, которые НЕ едут в списке сессий. Список опрашивается раз в 3 секунды, и его вес —
+    # это не скорость, а ВЕРОЯТНОСТЬ ДОСТАВКИ: у юзера между нами и его машиной прозрачный
+    # посредник, на котором ответы до ~15 КБ доходят 10 из 10, а крупные — 17 из 33 (#65,
+    # замер perf). `system_prompt` — 86.4% веса ответа по проводу (46.9 КБ из 54.3),
+    # `last_summary` — ещё 5.9%. Ни одно из двух в списке не читается:
+    # промпт берётся отдельным роутом `GET /api/sessions/{name}/prompt` по кнопке 📜,
+    # а `last_summary` нужен только серверу (`runtime_handoff`).
+    # Понадобилось поле в списке — добавляй осознанно и перемеряй вес: tests/test_manager.py::TestListSessions
+    # держит потолок.
+    _LIST_OMIT = ("system_prompt", "last_summary")
+
     def list_sessions(self, scope: str | None = None) -> list[dict]:
         from app.db import get_last_turn_map
         result = []
         seen = set()
         for s in self.sessions.values():
@@ -1579,10 +1590,12 @@ class SessionManager:
         # Cache-timer metadata is runtime-derived; Codex exposes only an approximate window.
         turn_map = get_last_turn_map()
         for r in result:
             r["last_turn_ts"] = turn_map.get(r["id"])
             r.update(cache_policy_for_runtime(runtime_for_record(r)))
+            for omit in self._LIST_OMIT:
+                r.pop(omit, None)
         return result
 
     def get_session_id(self, name: str, scope: str) -> str | None:
         for s in self.sessions.values():
             if s.name == name and s.scope == scope:
### 262b38b5b #71: #71: исследование — 92.8% провода даёт одно поле, второй вызов от нулевого дросселя

diff --git a/docs/workers/feat-instant.md b/docs/workers/feat-instant.md
index 82b9025ea..add67e2e3 100644
--- a/docs/workers/feat-instant.md
+++ b/docs/workers/feat-instant.md
@@ -18,10 +18,13 @@
   ложатся в одну цепочку, и стенд показывает «конфликтов нет» там, где их не могло быть.
   В стенде — `git branch -M main` сразу после init, и проверять предпосылку, а не вывод.
 - **«Успешно» в выводе скрипта — не доказательство.** Мой же `--seed` печатал «отсечка
   проставлена», пока узкий regex не матчил метку: сообщение было, эффекта нет. Проверять
   СЛЕДУЮЩЕЙ командой, а не сообщением об успехе.
+- **Тестовые данные для замера сжатия — не `"x" * N`.** Повторяющийся текст gzip схлопывает
+  почти в ноль, и «замер по проводу» доказывает ничего (1078 б против 812 б). Псевдотекст из
+  случайных слов жмётся как настоящий: те же данные дали 16 267 б против 818 б.
 - **Мутация — единственная улика.** Когда файл ветки совпадает с тем, что отдаёт сервер
   (после мержа — всегда), неприменившийся стаб выглядит как применившийся. Ломай нарочно:
   проверка ОБЯЗАНА покраснеть. Харнесс для браузерных прогонов — `docs/tasks/8/mutation-check.py`;
   для кода — откат файла через `git show`. Мутация должна падать сама, если её якорь исчез.
 - **`all([]) == True`.** Проверка, агрегирующая собранное на лету (DOM, файлы, логи), при