# Research slice: personal worker memory

Дата среза: 2026-08-12. База открывалась только так:

```python
sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro', uri=True)
```

## Замеры и первоисточники

1. **CONFIRMED — В базе 102 сессии: 65 в `/home/kesha/orchestra`, 30 в `seedon`, 3 в `kesha-tg-bot`, 3 в `dnd-game-master`, 1 в `University`; статусы: 74 `archived`, 26 `idle`, 2 `waiting`.** Артефакт: SQL `select scope,count(*) from sessions group by scope;` и `select status,count(*) from sessions group by status;` → числа выше.

2. **CONFIRMED — В 97 агентских сессиях (roles `worker`, `full-cycle`, `sub-orchestrator`) только 22 строки `sessions.system_prompt` содержат `<worker-memory>`: 22.7%.** Артефакт: SQL `select count(*) from sessions where role in ('worker','full-cycle','sub-orchestrator');` → `97`; SQL `select count(*) from sessions where role in ('worker','full-cycle','sub-orchestrator') and instr(system_prompt,'<worker-memory>')>0;` → `22`.

3. **CONFIRMED — Среди текущих (не archived) 28 сессий memory-блок есть у 19 (67.9%); если исключить оркестраторов, у 18 из 25 (72.0%).** Артефакт: SQL `select status,count(*),sum(instr(system_prompt,'<worker-memory>')>0) from sessions group by status;` → `idle 26 18`, `waiting 2 1`; SQL `select count(*) from sessions where status in ('idle','waiting') and role in ('worker','full-cycle','sub-orchestrator');` → `25`; SQL `select count(*) from sessions where status in ('idle','waiting') and role in ('worker','full-cycle','sub-orchestrator') and instr(system_prompt,'<worker-memory>')>0;` → `18`.

4. **CONFIRMED — Покрытие memory-блоком по контурам различается: `/home/kesha/orchestra` 11/65 (16.9%), `seedon` 11/30 (36.7%), `kesha-tg-bot` 1/3 (33.3%), `dnd-game-master` 0/3, `University` 0/1.** Артефакт: SQL `select scope,count(*),sum(instr(system_prompt,'<worker-memory>')>0),round(100.0*sum(instr(system_prompt,'<worker-memory>')>0)/count(*),1) from sessions group by scope;` → `(65,11,16.9)`, `(30,11,36.7)`, `(3,1,33.3)`, `(3,0,0.0)`, `(1,0,0.0)`.

5. **CONFIRMED — Платформа выбирает файл сначала по точному имени агента, затем по имени роли, и читает только непустой файл.** Артефакт: `app/prompting.py:59-78`: `for filename in (f"{name}.md", f"{role}.md" if role else None)`; `path = base / "docs" / "workers" / filename`; `if path.is_file()`; `content = path.read_text().strip()`; `if content: return content`.

6. **CONFIRMED — При spawn память добавляется в prompt ровно одним `<worker-memory>`-блоком.** Артефакт: `app/manager.py:615-619`: `worker_memory = load_worker_memory(name, role, scope)` и `prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"`.

7. **CONFIRMED — При загрузке/резюме из DB текущий файл перечитывается до создания `AgentSession`; это не только исторический `system_prompt`.** Артефакт: `app/manager.py:1491-1499`: `current_prompt = refresh_worker_memory(...)`, затем `AgentSession(... system_prompt=current_prompt, ...)`.

8. **CONFIRMED — После resume/compact память перечитывается перед первым outbound-сообщением и действительно передаётся backend.** Артефакт: `app/session.py:914-929` вызывает `refresh_worker_memory(...)`, встраивает результат в `message`; `app/session.py:998-999` вызывает `await backend.send(outbound_message)`. Для новых Claude-сессий prompt передаётся SDK как append: `app/backend_claude.py:189-192`; для Codex как `developerInstructions`: `app/backend_codex.py:400-413`; для OpenCode как `body["system"]`: `app/backend_opencode.py:264-274`.

9. **CONFIRMED — В telemetry есть 300 tool-log записей с явным `file_path` под `docs/workers/`: 50 `Write` и 206 `Edit` (34 и 25 разных сессий соответственно); 223 tool-result записи сообщают об успешном `created/updated`.** Артефакт: SQL `select count(*) from logs where type='tool' and content like '%file_path%docs/workers/%';` → `300`; SQL `select count(*),count(distinct session_id) from logs where type='tool' and content like '%Write:%' and content like '%file_path%docs/workers/%';` → `50,34`; SQL с `'%Edit:%'` вместо `'%Write:%'` → `206,25`; SQL `select count(*),count(distinct session_id) from logs where type='tool_result' and content like '%docs/workers/%' and (content like '%created successfully%' or content like '%updated successfully%');` → `223,38`.

10. **CONFIRMED — Память физически не только “пишется в логи”: в текущем дереве 35 файлов `docs/workers/*.md`, все 35 tracked, 0 untracked и 0 ignored.** Артефакт: `find docs/workers -maxdepth 1 -type f -name '*.md' | wc -l` → `35`; `git ls-files 'docs/workers/*.md' | wc -l` → `35`; `git ls-files --others --exclude-standard 'docs/workers/*.md' | wc -l` → `0`; `git ls-files --others -i --exclude-standard 'docs/workers/*.md' | wc -l` → `0`. Правило исключения подтверждено `.gitignore:9-10`: `workers/` и `!docs/workers/`.

11. **CONFIRMED — На доступном живом контуре `seedon` 24 файла памяти и в `kesha-tg-bot` 4; в `dnd-game-master` и `University` файлов нет.** Артефакт: `find /home/kesha/projects/seedon/docs/workers -maxdepth 1 -type f -name '*.md' | wc -l` → `24`; `find /home/kesha/projects/kesha-tg-bot/docs/workers -maxdepth 1 -type f -name '*.md' | wc -l` → `4`; `find /home/kesha/projects/dnd-game-master/docs/workers -maxdepth 1 -type f -name '*.md' | wc -l` → `0`; `find /home/kesha/projects/University/docs/workers -maxdepth 1 -type f -name '*.md' | wc -l` → `0`.

12. **CONFIRMED — В seedon из 11 сессий с memory-блоком только 5 (45.5%) совпадают с текущим файлом byte-for-byte; у 6 (54.5%) prompt отличается, включая 1 сессию с двумя блоками.** Артефакт: точный скрипт `C12` ниже → `rows=11, same=5, diff=6, missing=0`; SQL `select name,length(system_prompt)-length(replace(system_prompt,'<worker-memory>','')) from sessions where scope='/home/kesha/projects/seedon' and system_prompt like '%<worker-memory>%';` показывает duplicate-кандидата `accountant`.

13. **CONFIRMED — В kesha-tg-bot единственная сессия с memory-блоком (`fix-runtime-handoff`) совпадает с текущим `docs/workers/fix-runtime-handoff.md`.** Артефакт: точный скрипт `C12` ниже с `scope='/home/kesha/projects/kesha-tg-bot'` → `rows=1, same=1, diff=0, missing=0`.

14. **CONFIRMED — В snapshot DB есть дублирование personal memory: 23 сессии содержат блок, но 2 сессии содержат по 2 блока; `accountant` имеет блоки длиной 12,890 и 10,858 символов.** Артефакт: точный скрипт `C14` ниже → distribution `{1: 21, 2: 2}`, `accountant → blocks=2, lens=12890,10858`.

15. **CONFIRMED — В собственном checkout 17 из 35 файлов памяти не имеют одноимённой строки в snapshot `sessions` для scope `/home/kesha/orchestra`; это кандидаты на orphan/dead memory, но не доказательство удаления.** Артефакт: точный скрипт `C15` ниже → `files=35, sessions=65, intersection=18, files_no_db=17`.

16. **CONFIRMED — Размеры файлов памяти имеют длинный хвост: в checkout `/home/kesha/orchestra` 35 файлов, median 3,704 B, p90 14,815 B, max 45,647 B; 8 файлов больше 10 KB, 3 больше 20 KB.** Артефакт: `python3 -c 'from pathlib import Path; import statistics; v=sorted(p.stat().st_size for p in Path("docs/workers").glob("*.md")); print(len(v),statistics.median(v),v[int(.9*(len(v)-1))],max(v),sum(x>10000 for x in v),sum(x>20000 for x in v))'` → `35 3704 14815 45647 8 3`. Это числовой сигнал возможного “лишнего”, но сам размер не доказывает нерелевантность текста.

17. **CONFIRMED — Кодовая ветка role-fallback сейчас не используется физическими файлами: среди checkout и двух доступных живых `docs/workers` нет `worker.md`, `full-cycle.md`, `orchestrator.md` или `sub-orchestrator.md` (0 файлов).** Артефакт: `find docs/workers /home/kesha/projects/seedon/docs/workers /home/kesha/projects/kesha-tg-bot/docs/workers -maxdepth 1 -type f \( -name 'worker.md' -o -name 'full-cycle.md' -o -name 'orchestrator.md' -o -name 'sub-orchestrator.md' \) | wc -l` → `0`; fallback остаётся предусмотренным `app/prompting.py:66`.

### Exact scripts for C12/C14/C15

```bash
# C12 — run once with each listed scope.
python3 - <<'PY'
import pathlib, re, sqlite3
scope = '/home/kesha/projects/seedon'
con = sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro', uri=True)
rows = con.execute("select name,system_prompt from sessions where scope=? and system_prompt like '%<worker-memory>%'", (scope,)).fetchall()
same = diff = missing = 0
for name, prompt in rows:
    blocks = re.findall(r'<worker-memory>\s*(.*?)\s*</worker-memory>', prompt, re.S)
    path = pathlib.Path(scope) / 'docs/workers' / f'{name}.md'
    if not path.exists(): missing += 1
    elif len(blocks) == 1 and blocks[0].strip() == path.read_text().strip(): same += 1
    else: diff += 1
print(f'rows={len(rows)}, same={same}, diff={diff}, missing={missing}')
PY
# output for seedon: rows=11, same=5, diff=6, missing=0
# changing scope to /home/kesha/projects/kesha-tg-bot outputs:
# rows=1, same=1, diff=0, missing=0

# C14 — duplicate blocks and their lengths.
python3 - <<'PY'
import re, sqlite3, collections
con = sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro', uri=True)
out = []
for name, prompt in con.execute("select name,system_prompt from sessions where system_prompt like '%<worker-memory>%'"):
    blocks = re.findall(r'<worker-memory>\s*(.*?)\s*</worker-memory>', prompt, re.S)
    out.append((name, blocks))
print(collections.Counter(len(b) for _, b in out))
for name, blocks in out:
    if len(blocks) > 1: print(name, len(blocks), [len(b) for b in blocks])
PY
# output: Counter({1: 21, 2: 2}); accountant 2 [12890, 10858]

# C15 — file names versus DB names in the checkout scope.
python3 - <<'PY'
import pathlib, sqlite3
files = {p.stem for p in pathlib.Path('docs/workers').glob('*.md')}
con = sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro', uri=True)
names = {r[0] for r in con.execute("select name from sessions where scope='/home/kesha/orchestra'")}
print(len(files), len(names), len(files & names), len(files - names))
PY
# output: 35 65 18 17
```

## Что говорит ПРОТИВ моих выводов

- `sessions.system_prompt` — сохранённый assembled prompt, а не wire-capture ответа модели. Прямое лог-доказательство фактического outbound-инжекта с `<worker-memory>` есть только в 3 `user_message` и 3 `text` записях: SQL `select type,count(*) from logs where content like '%<worker-memory>%' and type in ('user_message','text') group by type;` → `user_message=3, text=3`. Остальные 67 marker-совпадений в `tool_result` — код/отчёты, не доставка.
- Срез DB исторический и содержит archived-сессии; отсутствие одноимённого файла не доказывает, что файл не существовал в момент spawn или что его нужно удалять.
- Сравнение “prompt vs disk” удалось сделать только для `/home/kesha/projects/seedon` и `/home/kesha/projects/kesha-tg-bot`; `/home/kesha/orchestra` запрещён условием, поэтому 17 orphan-кандидатов и stale-доля для него не подтверждены живым диском.
- Логи Write/Edit считают события инструментов, а не уникальные коммиты или успешность каждого изменения; поэтому число 300 — верхняя оценка операций/упоминаний, а не число уникальных записанных уроков.

## Чего я проверить не смог

- Не смог измерить, прочитала ли модель memory-блок и повлиял ли он на поведение: в доступных таблицах нет model-attention/ack метрики.
- Не смог снять end-to-end payload всех backend-протоколов из wire-логов; доставку подтвердил кодовым трассированием и частичным логом, не полным replay.
- Не смог установить, какие из 17 orphan-кандидатов исторически мёртвые, а какие просто принадлежат другому worktree/ветке.
