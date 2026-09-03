# Research slice: personal worker memory delivery

Измерение выполнено 2026-08-12 в checkout среза и read-only БД `/home/kesha/bench219/orchestra-cut.db`. Для файлов памяти вне `/home/kesha/orchestra` прочитаны только каталоги `/home/kesha/projects/seedon` и `/home/kesha/projects/kesha-tg-bot`. Число в скобках после SQL — фактический результат.

Точная команда C1 для разбора блоков и сравнения с доступным seedon-диском:

```bash
python3 - <<'PY'
import hashlib, pathlib, re, sqlite3
c = sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro', uri=True)
p = re.compile(r'<worker-memory>\n(.*?)\n</worker-memory>', re.S)
rows = list(c.execute("select name,role,status,scope,system_prompt from sessions where status!='archived'"))
active = [(n,r,s,p.findall(sp or '')) for n,r,s,sc,sp in rows if r in ('worker','full-cycle') and p.findall(sp or '')]
print('active marker sessions/blocks/duplicate names:', len(active), sum(len(b) for _,_,_,b in active), [(n,len(b),[len(x) for x in b]) for n,_,_,b in active if len(b)>1])
sizes = sorted(sum(map(len,b)) for _,_,_,b in active)
print('active worker-ish block chars min/median/max:', sizes[0], sizes[len(sizes)//2], sizes[-1])
files = markers = exact = duplicates = mismatches = 0
for n,r,s,sc,sp in rows:
    if sc != '/home/kesha/projects/seedon' or r not in ('worker','full-cycle'): continue
    f = pathlib.Path(sc)/'docs/workers'/f'{n}.md'
    if f.is_file(): files += 1
    if not f.is_file() or not sp: continue
    mem = f.read_text().strip(); b = p.findall(sp)
    if b:
        markers += 1; duplicates += len(b)>1; exact += len(b)==1 and b[-1] == mem; mismatches += not (len(b)==1 and b[-1] == mem)
        print(n, len(mem), len(b), [len(x) for x in b], len(mem)-len(b[-1]), hashlib.sha256(mem.encode()).hexdigest()[:12], hashlib.sha256(b[-1].encode()).hexdigest()[:12])
print('seedon files/markers/exact/duplicates/mismatch:', files,markers,exact,duplicates,mismatches)
PY
```

## Утверждения

- `load_worker_memory()` ищет сначала `docs/workers/<name>.md`, затем `docs/workers/<role>.md`, читает файл через `.read_text().strip()`, а при отсутствии/ошибке возвращает пустую строку. — **CONFIRMED** — `app/prompting.py:59-78`: `for filename in (f"{name}.md", f"{role}.md" if role else None)`; `content = path.read_text().strip()`; `return ""`.

- При spawn непустая память добавляется в prompt одним текстовым блоком `<worker-memory>...</worker-memory>`. — **CONFIRMED** — `app/manager.py:615-619`: `worker_memory = load_worker_memory(name, role, scope)` и `prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"`.

- При загрузке сессии из БД старые memory-блоки удаляются, затем память перечитывается с диска, а результат становится `AgentSession.system_prompt`. — **CONFIRMED** — `app/manager.py:1472-1499`: `strip_worker_memory(...)` → `refresh_worker_memory(...)` → `system_prompt=current_prompt`; `SELECT ...` из БД насчитал **102** строки `sessions`.

- После resume/compact memory перечитывается только на первой отправке, когда `session_id` есть, `_current_prompt` непуст, а `_prompt_injected` ложен; последующие ходы используют закешированный prompt. — **CONFIRMED** — `app/session.py:914-929`: условие `if self.session_id and self._current_prompt and not self._prompt_injected`, вызов `refresh_worker_memory(...)`, затем `message = ... self._current_prompt ...`; `app/session.py:915-917` прямо говорит “Only on first message after resume; subsequent turns use cached prompt”.

- `refresh_worker_memory()` перед вставкой удаляет все старые блоки и добавляет один свежий; тест проверяет, что после дублированного входа число блоков равно **1**. — **CONFIRMED** — `app/prompting.py:81-97`; `tests/test_prompting.py:605-622`: `assert out.count("<worker-memory>") == 1`.

- На свежем Claude-сеансе prompt реально передаётся SDK как `options.system_prompt["append"]`; на Codex — как `developerInstructions`. — **CONFIRMED** — `app/backend_claude.py:189-193`: `options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}`; `app/backend_codex.py:400-407`: `params["developerInstructions"] = self.system_prompt`.

- Для Grok и OpenCode память также входит в отправляемый runtime prompt: Grok пишет `self.system_prompt` в профиль, OpenCode кладёт его в JSON-поле `system`. — **CONFIRMED** — `app/backend_grok.py:979-995`: `f"{self.system_prompt}\n"`; `app/backend_opencode.py:264-274`: `body["system"] = self.system_prompt`.

- В срезе **28** сессий не имеют `status='archived'`; из них **22** имеют роль `worker` или `full-cycle`. — **CONFIRMED** — SQL `SELECT count(*) FROM sessions WHERE status!='archived'` → **28**; SQL `SELECT count(*) FROM sessions WHERE role IN ('worker','full-cycle') AND status!='archived'` → **22**.

- В `sessions.system_prompt` memory-маркер виден у **19/28** всех неархивных сессий и у **17/22** неархивных worker/full-cycle сессий. — **CONFIRMED** — SQL `SELECT count(*) FROM sessions WHERE status!='archived' AND instr(system_prompt,'<worker-memory>')>0` → **19**; SQL `SELECT count(*) FROM sessions WHERE role IN ('worker','full-cycle') AND status!='archived' AND instr(system_prompt,'<worker-memory>')>0` → **17**.

- Среди всех **96** worker/full-cycle сессий marker есть в **21**; значит, в persisted prompt marker отсутствует у **75/96** исторических сессий (включая архивные). — **CONFIRMED** — SQL `SELECT count(*) FROM sessions WHERE role IN ('worker','full-cycle')` → **96**; SQL с `AND instr(system_prompt,'<worker-memory>')>0` → **21**; разность **75**.

- В 19 активных prompt-носителях найдено **20** блоков: один prompt содержит дубликат. — **CONFIRMED** — точная команда **C1** дала `active marker sessions/blocks/duplicate names: 17 18 [('accountant', 2, [12890, 10858])]` для worker/full-cycle; SQL всех ролей дал **19** marker-bearing и тот же один duplicate.

- Размер видимой memory-нагрузки в активных worker/full-cycle prompt-ах (сумма блоков на сессию) лежит от **1 073** до **37 799** символов, медиана — **8 874**. — **CONFIRMED** — точная команда **C1** дала `active worker-ish block chars min/median/max: 1073 8874 37799`.

- Для доступного live-проекта `/home/kesha/projects/seedon` есть **13** активных worker/full-cycle сессий: memory-файл существует у **10**, marker есть у **9**, но актуальный последний блок совпадает с диском только у **5/9**. — **CONFIRMED** — SQL `SELECT count(*) ... WHERE scope='/home/kesha/projects/seedon' AND role IN ('worker','full-cycle') AND status!='archived'` → **13**; точная команда **C1** читает `Path('/home/kesha/projects/seedon/docs/workers/<name>.md')` и печатает hashes/lengths; её строки дают `files=10 marker=9 latest_exact=5 duplicates=1 mismatch_with_file=4`.

- Четыре активных seedon prompt-а несут укороченную/устаревшую память: `accountant` — **10 858/15 120** символов в последнем блоке (**71.81%**), `docs-audit` — **7 037/8 507** (**82.72%**), `feat-direct-api` — **1 167/2 027** (**57.57%**), `sales` — **9 059/16 303** (**55.57%**). — **CONFIRMED** — точная команда **C1** печатает для этих имён соответственно `filechars/pchars=[15120/10858, 8507/7037, 2027/1167, 16303/9059]`, `latest_delta=[4262,1470,860,7244]`; SHA-12 пар не совпадает.

- Пять активных seedon сессий (`bizdev`, `designer`, `direct-research`, `landing-choice`, `marketer`) совпадают с диском байт-в-байт после `.strip()`. — **CONFIRMED** — точная команда **C1** печатает для каждой `latest_delta=0` и одинаковые SHA-12; всего **5** exact из **9** marker-bearing.

- В доступном `/home/kesha/projects/kesha-tg-bot` найден только один worker с memory marker (`fix-runtime-handoff`), но он архивный и совпадает с диском: **239/239** символов. — **CONFIRMED** — SQL по `scope='/home/kesha/projects/kesha-tg-bot'` и `role='worker'` дал `archived=2, marker=1`; Python comparison дал `latest_exact=1`, `filechars=239`, `pchars=239`.

- Логи не являются полным слепком доставленного prompt: `_log("user_message", message)` выполняется на строке 909, а memory-обогащение `message = ... self._current_prompt ...` — только на строке 928. — **CONFIRMED** — `app/session.py:907-929`; SQL `SELECT type,count(*) FROM logs WHERE instr(content,'<worker-memory>')>0 GROUP BY type` → `tool=30`, `tool_result=67`, `text=3`, `user_message=3` (всего **103** строк), поэтому marker в log не доказывает, что это был уже обогащённый outbound message.

- Исторический дефект действительно был зафиксирован как **11/13** stale live sessions и худший пропуск **61%**, но это число относится к измерению до #137, а не к текущему срезу. — **CONFIRMED** — `tests/test_prompting.py:579-584` и `tests/test_session.py:2771-2778` содержат эти числа как “Measured before the fix”; текущая БД даёт другие числа: **17/22** active worker/full-cycle с marker и **5/9** exact среди проверяемых seedon.

## Что говорит ПРОТИВ моих выводов

- Наличие marker в `sessions.system_prompt` может быть только persisted snapshot, а не подтверждением того, что provider принял prompt в конкретном последнем turn. — **LIKELY** — `app/session.py:686-702` передаёт `system_prompt` в `BackendBuildContext`, но таблица `logs` не хранит provider-level request; SQL `SELECT count(*) FROM logs WHERE type='user_message' AND instr(content,'<worker-memory>')>0` → **3**.

- Для resumed Claude-сеанса новый `options.system_prompt` не выставляется в ветке `if resume_id`; память может приехать как platform-note в первом user message после resume. — **CONFIRMED** — `app/backend_claude.py:189-193`: `else` передаёт append только без `resume_id`; `app/session.py:914-929`: first-message injection при наличии `session_id`.

- `accountant` показывает, что даже при наличии памяти возможна форма с двумя блоками: **2** блока размером **12 890** и **10 858** при файле **15 120**. — **CONFIRMED** — точная команда **C1** печатает `('accountant', 2, [12890,10858])`; тест на такую ситуацию существует в `tests/test_prompting.py:605-622`, но telemetry snapshot всё ещё содержит duplicate.

## Чего я проверить не смог

- Я не сравнивал содержимое memory-файлов для сессий со `scope='/home/kesha/orchestra'`, потому что это запрещено периметром среза. — **CONFIRMED** — SQL `SELECT scope,count(*),sum(status!='archived'),sum(instr(system_prompt,'<worker-memory>')>0) FROM sessions GROUP BY scope` показывает `/home/kesha/orchestra` **65** сессий, из них **10** неархивных и **11** marker-bearing; их disk-vs-prompt exactness не установлена.

- Я не мог восстановить фактический provider request/response для каждого live turn: в доступной схеме `logs` есть `type/content/tool_name/session_id`, но нет поля system/developer prompt; `PRAGMA table_info(logs)` даёт **9** колонок, ни одна не называется `system_prompt`. — **CONFIRMED** — `PRAGMA table_info(logs)` → колонки `id,session_id,ts,type,content,event_id,tool_use_id,tool_name,tool_is_error`.

- Я не проверял содержимое `/home/kesha/projects/dnd-game-master` и `/home/kesha/projects/University`: в их активных orchestrator-сессиях marker отсутствует (**0** по каждой scope-группе), а задача требует именно worker memory. — **CONFIRMED** — SQL `SELECT scope,count(*),sum(instr(system_prompt,'<worker-memory>')>0) FROM sessions WHERE status!='archived' GROUP BY scope` → `dnd-game-master: 1,0`; `University: 1,0`.
