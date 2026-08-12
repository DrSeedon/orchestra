# Исследовательский срез: работают ли правила промпта

## Вывод

Короткий ответ — численные прокси и ограничения приведены в пунктах 3, 5–12 и в секциях ниже.

## Утверждения и артефакты

1. **CONFIRMED — проект действительно загружает и `CLAUDE.md`, и ролевые prompt-модули.** В `pipelines/default/pipeline.yaml:8-14` указано `inherit_claude_md: true` и копирование `CLAUDE.md`; там же `:9-11` заданы prompt layers. Набор модулей для ролей указан в `pipelines/default/pipeline.yaml:25`, `:41`, `:57`, `:73`.

2. **CONFIRMED — наблюдаемый проектный срез содержит 65 сессий и 30 030 log-записей.** Артефакт (read-only SQLite):

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT count(DISTINCT s.id) sessions,count(l.id) logs,min(l.ts) first_ts,max(l.ts) last_ts FROM sessions s LEFT JOIN logs l ON l.session_id=s.id WHERE s.scope='/home/kesha/orchestra';"
   ```

   Результат: `sessions=65`, `logs=30030`, `first_ts=2026-07-28T04:47:07...`, `last_ts=2026-08-11T09:53:14...`.

3. **CONFIRMED — для поведения до 03.08 есть только 2 проектные записи; обе не являются рабочими tool/text-событиями.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT type,count(*) n FROM logs l JOIN sessions s ON s.id=l.session_id WHERE s.scope='/home/kesha/orchestra' AND l.ts<'2026-08-03' GROUP BY type;"
   ```

   Результат: `status | 2`. Поэтому полноценный pre/post эксперимент по большинству правил невозможен.

4. **CONFIRMED — собранный prompt-маркер доставлен всем 23 full-cycle и 40 из 41 worker-сессии.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT role,count(*) n,sum(instr(system_prompt,'Semantic memory —')>0) memory_marker,sum(instr(system_prompt,'Git workflow rules')>0) git_marker,sum(instr(system_prompt,'Self-improvement')>0) self_marker,sum(instr(system_prompt,'Research Method')>0) research_marker FROM sessions WHERE scope='/home/kesha/orchestra' GROUP BY role;"
   ```

   Результат: `full-cycle 23/23/23/23/23`, `worker 41/40/41/41/0`, `orchestrator 1/1/1/1/0`; отсутствие Research Method у worker ожидаемо по `pipeline.yaml:57` против `:73`.

5. **CONFIRMED — у full-cycle правило обязательного `search_memory` имеет сильный поведенческий прокси: 23/23 сессий вызвали его, 61 вызов; у worker — 24/41 сессий, 57 вызовов.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT s.role,count(DISTINCT s.id) sessions,count(DISTINCT CASE WHEN l.type='tool' AND l.content LIKE 'mcp__orchestra__search_memory:%' THEN l.session_id END) sessions_with_search,sum(l.type='tool' AND l.content LIKE 'mcp__orchestra__search_memory:%') search_calls FROM sessions s LEFT JOIN logs l ON l.session_id=s.id WHERE s.scope='/home/kesha/orchestra' GROUP BY s.role;"
   ```

   Это подтверждает частое исполнение, но не рост после правила: pre-окна нет. Само правило находится в `pipelines/default/prompts/modules/memory-search.md:4-14`.

6. **LIKELY — правило `git check-ignore` стало использоваться чаще после появления в своде, но это только нормированный proxy, не compliance-rate.** `CLAUDE.md:145` (commit `bce023f`, 2026-08-04 07:39+02) предписывает проверку до работы. Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "WITH x AS (SELECT CASE WHEN l.ts<'2026-08-04T05:39:04' THEN 'before_rule' ELSE 'after_rule' END period,l.content LIKE '%git check-ignore%' hit FROM logs l JOIN sessions s ON s.id=l.session_id WHERE s.scope='/home/kesha/orchestra' AND l.type='tool') SELECT period,sum(hit) hits,count(*) all_tools,round(100.0*sum(hit)/count(*),2) pct_tools FROM x GROUP BY period;"
   ```

   Результат: `before_rule 4/3339=0.12%`; `after_rule 84/7873=1.07%` — примерно `8.9x`, при этом знаменатель — tool-записи, а не задачи.

7. **LIKELY — правило копирования живой SQLite через `backup()` имеет большой сдвиг в сторону предписанного метода.** Правило добавлено commit `a0c7d1d` (2026-08-07 10:19+02). Артефакт классификации явных команд:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "WITH e AS (SELECT CASE WHEN l.ts<'2026-08-07T08:19:00' THEN 'before_rule' ELSE 'after_rule' END period,CASE WHEN l.content LIKE '%backup(%' OR l.content LIKE '%src.backup%' THEN 'sqlite_backup' WHEN l.content LIKE '%cp %orchestra.db%' OR l.content LIKE '%cp /home/kesha/orchestra/data/orchestra.db%' THEN 'cp_db' ELSE 'other' END method FROM logs l JOIN sessions s ON s.id=l.session_id WHERE s.scope='/home/kesha/orchestra' AND l.type='tool' AND (l.content LIKE '%orchestra.db%' OR l.content LIKE '%backup(%')) SELECT period,method,count(*) n FROM e GROUP BY period,method ORDER BY period,method;"
   ```

   Результат: до — `sqlite_backup=7`, `cp_db=45` (backup-share `13.5%`); после — `sqlite_backup=27`, `cp_db=3` (`90.0%`). Внутри этого эвристического множества сдвиг примерно `6.7x`. Цитата правила: `CLAUDE.md:177`.

8. **LIKELY — mutation-практика выросла после правил про мутации, но классификация широкая.** Артефакт (tool-запись считается mutation-like, если содержит `cp`, `pytest/test` и `bak/mutat`):

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "WITH e AS (SELECT CASE WHEN l.ts<'2026-08-07T03:20:26' THEN 'before_rule' ELSE 'after_rule' END period,CASE WHEN (l.content LIKE '%cp %' OR l.content LIKE '%cp\\n%') AND (l.content LIKE '%pytest%' OR l.content LIKE '%test%') AND (l.content LIKE '%bak%' OR l.content LIKE '%mutat%') THEN 1 ELSE 0 END hit FROM logs l JOIN sessions s ON s.id=l.session_id WHERE s.scope='/home/kesha/orchestra' AND l.type='tool') SELECT period,sum(hit) mutation_like_tools,count(*) all_tools,round(100.0*sum(hit)/count(*),2) pct_tools FROM e GROUP BY period;"
   ```

   Результат: до `45/7360=0.61%`, после `136/3852=3.53%` (примерно `5.8x`). Это не доказывает, что тест поймал мутант.

9. **CONFIRMED — lifecycle-гейт используется часто, но не на каждом kill.** После правила `pipelines/default/prompts/modules/worker-lifecycle.md:8-14` в срезе есть 54 `kill_worker` и 51 `worker_wip`; в том же session tool-поток содержит `worker_wip` не позднее 5 минут перед 46 из 54 kill (`85.2%`). Артефакт-команда:

   ```bash
   python3 - <<'PY'
   import sqlite3,datetime
   c=sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro',uri=True)
   r=c.execute("select l.session_id,l.ts,l.content from logs l join sessions s on s.id=l.session_id where s.scope='/home/kesha/orchestra' and l.type='tool' and l.ts>='2026-08-01' order by l.session_id,l.id").fetchall()
   d=lambda x: datetime.datetime.fromisoformat(x)
   k=[x for x in r if x[2].startswith('mcp__orchestra__kill_worker:')]; w=[x for x in r if x[2].startswith('mcp__orchestra__worker_wip:')]
   n=sum(any(x[0]==y[0] and 0 <= (d(x[1])-d(y[1])).total_seconds() <= 300 for y in w) for x in k)
   print('kills',len(k),'wips',len(w),'wip<=5min-before-kill',n,'rate',round(100*n/len(k),1))
   PY
   ```

   Результат: `kills 54 wips 51 wip<=5min-before-kill 46 rate 85.2`.

10. **CONFIRMED — правило общения через Orchestra tool выполняется широко: 672 точных `mcp__orchestra__send_message` tool-события в 60 из 65 сессий.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT count(DISTINCT l.session_id) sessions_with_send_message,(SELECT count(*) FROM sessions WHERE scope='/home/kesha/orchestra') project_sessions,count(*) send_tool_events FROM logs l JOIN sessions s ON s.id=l.session_id WHERE s.scope='/home/kesha/orchestra' AND l.type='tool' AND l.content LIKE 'mcp__orchestra__send_message:%';"
   ```

   Результат: `60/65` сессий, `672` событий. Это частое соблюдение, но пять сессий не имели такого вызова.

11. **CONFIRMED — `codex_review` реально вызывается, но телеметрия не позволяет проверить обязательность именно для shared-runtime diff.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT count(*) events,count(DISTINCT l.session_id) sessions FROM logs l JOIN sessions s ON s.id=l.session_id WHERE s.scope='/home/kesha/orchestra' AND l.type='tool' AND l.content LIKE 'mcp__orchestra__codex_review:%';"
   ```

   Результат: `43` событий в `16` сессиях. Обязательность формулируется в `pipelines/default/prompts/roles/worker.md:56`, но в `logs` нет поля «diff затронул shared runtime».

12. **CONFIRMED — запрет polling через `sleep` нарушается на уровне наблюдаемого command proxy: 160 tool-записей содержат `sleep`, из них 14 имеют `for ... sleep`, 23 — `while ... sleep`.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT count(*) sleep_tools,sum(content LIKE '%for i in%sleep%') for_sleep_tools,sum(content LIKE '%while%sleep%') while_sleep_tools FROM logs l JOIN sessions s ON s.id=l.session_id WHERE s.scope='/home/kesha/orchestra' AND l.type='tool' AND l.content LIKE '%sleep%';"
   ```

   Результат: `160`, `14`, `23`. Правило находится в `pipelines/default/prompts/base.md:42-43` и worker-ограничение — в `pipelines/default/prompts/roles/worker.md:11`; часть совпадений может быть легитимным bounded-тестом, поэтому это не оценка доли нарушений.

13. **CONFIRMED — в prompt-модуле есть устаревшая неполнота: тип `cron_command` реализован в коде, но не перечислен в инструкции.** `app/mcp_stdio.py:1845-1852` обрабатывает `elif type == "cron_command"`; `pipelines/default/prompts/modules/background-jobs.md:5-11` перечисляет `timer`, `file`, `command`, `ssh`, `run`, `cron`, но не `cron_command`. Это конкретный кандидат на «лишнее/мёртвое» в смысле неактуальной документации, а не доказательство мёртвого runtime-кода.

14. **CONFIRMED — один исторический worker действительно был создан до текущего memory-модуля и не содержит его в сохранённом prompt.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT name,role,created_at,length(system_prompt) chars FROM sessions WHERE scope='/home/kesha/orchestra' AND instr(system_prompt,'Semantic memory —')=0;"
   ```

   Результат: ровно `backend | worker | 2026-07-07T10:21:55... | 15006`; остальные 64 project-сессии имеют маркер. Это объясняет один структурный outlier и не доказывает нарушение поведения в нём.

15. **CONFIRMED — история prompt-версий есть, но она не привязана к каждому log-событию.** Артефакт:

   ```bash
   sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' "SELECT count(DISTINCT template_hash) template_hashes,count(DISTINCT length(system_prompt)) prompt_lengths FROM sessions WHERE scope='/home/kesha/orchestra';"
   ```

   Результат: `template_hashes=14`, `prompt_lengths=40`. Проверка схемы `sqlite3 -header -column 'file:/home/kesha/bench219/orchestra-cut.db?mode=ro' 'PRAGMA table_info(logs);'` показывает поля `id, session_id, ts, type, content, event_id, tool_use_id, tool_name, tool_is_error` — `template_hash` там нет. Поэтому нельзя надёжно сказать, какой именно текст видел агент в момент конкретного tool-вызова.

## Что говорит ПРОТИВ моих выводов

- Все «росты» выше используют интенсивность tool-событий или эвристическую классификацию команд, а не число подходящих задач (знаменатели и доли приведены в пп. 6–8).
- `cp`/`backup` совпадения включают резервные копии и копирование не только для доказательств WAL; `sleep` совпадения включают bounded benchmark и текст создаваемого скрипта (см. пп. 7 и 12).
- `worker_wip` перед `kill_worker` сопоставлен только по session и времени, а не по имени worker в JSON; часть 85.2% может быть ложным совпадением (см. п. 9).
- Полная доставка prompt-маркеров подтверждает наличие текста, но не чтение и не следование ему (п. 4; отсутствие event-level версии — п. 15).

## Чего я проверить не смог

- Причинный pre/post эффект каждого правила: до 03.08 в проектном скоупе нет рабочего telemetry baseline (п. 3).
- Реальную долю задач, где условие правила было применимо, и порядок «до начала работы» (в БД нет task-start/event-sequence семантики; знаменатели proxy приведены в пп. 6–8).
- Успех результата после действия (`git check-ignore` действительно был первым; `backup()` дал консистентный snapshot; mutation-тест покраснел) — в логах нет таких outcome-полей (пп. 6–8).
- Какая версия `CLAUDE.md`/модуля была загружена для конкретного log-события: есть только session-level `template_hash` (п. 15).
- Полный список мёртвых/лишних правил: для этого нужен статический аудит каждого утверждения против кода и отдельные применимые наблюдаемые сценарии; по текущему срезу уверенно найден только документальный разрыв `cron_command` (п. 13).
