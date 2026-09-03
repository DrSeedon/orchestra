# Исследовательский срез: личная память агентов

Срез сделан по текущему checkout и snapshot `/home/kesha/bench219/orchestra-cut.db`.
Каждый SQL-запрос выполнялся через `sqlite3.connect('file:/home/kesha/bench219/orchestra-cut.db?mode=ro', uri=True)`; база не изменялась.
Для scope `/home/kesha/orchestra` сравнение prompt↔файл использует только этот checkout; для `seedon` и `kesha-tg-bot` — разрешённые каталоги на диске.

## Утверждения

- **CONFIRMED.** На момент замера в checkout было 35 tracked-файлов `docs/workers/*.md`, суммарно 267608 байт и 2423 строки; медиана — 3704 байта/43 строки, максимум — `prompt-engineer.md` (45647 байт, 400 строк).

  Артефакт: `python3` по `Path('docs/workers').glob('*.md')` + `git ls-files 'docs/workers/*.md'` → `files=35 bytes=267608 lines=2423 median_bytes=3704 median_lines=43 max=('prompt-engineer.md',45647,400)`; `git ls-files ... | wc -l` → `35`.

- **CONFIRMED.** 17 из 35 файлов памяти (78426 байт, 916 строк) не имеют одноимённой сессии ни в одной строке `sessions` snapshot; это кандидаты на мёртвые/осиротевшие файлы, но не доказательство, что их нельзя переиспользовать.

  Артефакт: `select distinct name from sessions` + сравнение со stem файлов → `missing files 17 bytes 78426 lines 916`; список: `audit-worktree, docs-changelog, feat-freshness, fix-bugsmd, fix-merge-branch-drift, fix-silent-errors, fix-tg-mention, fix-wake-after-restart, memory-research, merge-contours, migrate-vps, rag-max, research-compact-prompt, research-embeddings, research-memory, research-merge, skill-migrate-norestart`.

- **CONFIRMED.** В snapshot 102 сессии всего; из них 63 `worker` и 33 `full-cycle`, то есть 96 агентских сессий с личной памятью в смысле роли.

  Артефакт: `select role,count(*) from sessions group by role order by role` → `full-cycle=33`, `worker=63` (остальные 6 — orchestrator/sub-orchestrator).

- **CONFIRMED.** `<worker-memory>` присутствует в `sessions.system_prompt` только у 21 из 96 `worker/full-cycle`-сессий (21.9%); разрез: `worker` 10/63, `full-cycle` 11/33.

  Артефакт: `select role,count(*) n,sum(instr(system_prompt,'<worker-memory>')>0) mem from sessions where role in ('worker','full-cycle') group by role` → `full-cycle 33 11`, `worker 63 10`.

- **CONFIRMED.** Для незавершённых `idle` агентских сессий доставка лучше: 17 из 22 имеют memory-блок (77.3%); отдельно `worker` 8/10, `full-cycle` 9/12.

  Артефакт: `select role,status,count(*) n,sum(instr(system_prompt,'<worker-memory>')>0) mem from sessions where role in ('worker','full-cycle') group by role,status` → `full-cycle idle 12 9`, `worker idle 10 8`.

- **CONFIRMED.** Для scope `/home/kesha/orchestra` среди idle worker/full-cycle memory есть у 8/9; для `/home/kesha/projects/seedon` — у 9/13.

  Артефакт: `select scope,role,status,count(*) n,sum(instr(system_prompt,'<worker-memory>')>0) mem from sessions where role in ('worker','full-cycle') group by scope,role,status` → orchestra idle `full-cycle 7 6` + `worker 2 2`; seedon idle `full-cycle 5 3` + `worker 8 6`.

- **CONFIRMED.** Телеметрия показывает фактические записи памяти, а не только упоминания: 232 прямых `Write`/`Edit` tool-вызова затронули 37 файлов из 36 worker/full-cycle-сессий; из них workers — 158 вызовов/20 сессий, full-cycle — 74/16.

  Артефакт: парсинг `logs` (`type='tool'`, JSON-поле `file_path`, путь содержит `/docs/workers/`) → `worker/full-cycle calls 232 sessions 36 files 37; worker calls 158 sessions 20 files 20; full-cycle calls 74 sessions 16 files 17`.

- **CONFIRMED.** 226 из 232 записей worker/full-cycle направлены в файл с именем текущей сессии; все 158 worker-вызовов — в self-file. Единственное отклонение — accountant писал 6 раз в legacy `payroll.md`.

  Артефакт: сравнение basename `file_path` с `sessions.name` → `selfcalls 226`, `mismatch Counter({('accountant','payroll'): 6})`; для `role='worker'` → `158` selfcalls, `0` mismatch.

- **CONFIRMED.** Записи памяти в snapshot происходили с 03.08 по 11.08.2026, поэтому corpus не является только статическим архивом.

  Артефакт: `select min(l.ts),max(l.ts) from logs l where l.type='tool' and l.content like '%/docs/workers/%'` → `2026-08-03T07:24:14.771145+00:00` … `2026-08-11T09:03:41.941777+00:00`.

- **CONFIRMED.** Код загрузки ищет сначала `docs/workers/{name}.md`, затем fallback `docs/workers/{role}.md`, читает весь файл и возвращает `.strip()` без лимита размера.

  Артефакт: `app/prompting.py:59-78`, цитата: `for filename in (f"{name}.md", f"{role}.md" if role else None)`; `content = path.read_text().strip()`; `return content`.

- **CONFIRMED.** При spawn память реально добавляется в prompt между тегами `<worker-memory>`.

  Артефакт: `app/manager.py:615-619`, цитата: `worker_memory = load_worker_memory(name, role, scope)` и `prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"`.

- **CONFIRMED.** При reload из DB память перечитывается с диска и заменяет старый блок, а не просто дописывается.

  Артефакт: `app/manager.py:1489-1494`, цитата: `prompt_overlay = strip_worker_memory(stored_overlay)` → `current_prompt = refresh_worker_memory(prompt_without_memory, db_row["name"], role, db_row["scope"])`.

- **CONFIRMED.** На первом сообщении после resume/compact refreshed prompt передаётся backend через `backend.send`.

  Артефакт: `app/session.py:922-928` строит `message = ... {self._current_prompt} ...`; `app/session.py:983-999` доводит его до `outbound_message` и выполняет `await backend.send(outbound_message)`.

- **CONFIRMED.** Поведенческий тест проверяет именно доставку свежей записи в outbound-сообщении: после записи `FRESH` он требует `FRESH` в `sent[0]` и отсутствие `STALE`.

  Артефакт: `tests/test_session.py:2771-2823`, цитаты: запись `(mem_dir / f"{session.name}.md").write_text("FRESH: learned this mid-session")`; затем `assert "FRESH: learned this mid-session" in sent[0]` и `assert "STALE: written at spawn" not in sent[0]`.

- **CONFIRMED.** Выбранный memory-срез тестов зелёный: 8 passed, 378 deselected.

  Артефакт: `uv run pytest -q tests/test_prompting.py -k 'worker_memory or refresh_worker_memory' tests/test_session.py -k 'personal_memory' tests/test_manager.py -k 'memory'` → `........ [100%] 8 passed, 378 deselected in 7.81s`.

- **CONFIRMED.** По snapshot prompt↔файл среди 23 сессий с `<worker-memory>`: 8 exact, 11 stale, 4 missing; stale-доля 47.8%. Сверка сравнивает блок из `sessions.system_prompt` с текущим checkout для orchestra и с живыми разрешёнными каталогами seedon/tg-bot.

  Артефакт: скрипт извлекает `re.search(r'<worker-memory>\\n(.*?)\\n</worker-memory>', system_prompt, re.S)` и сравнивает с `docs/workers/{name}.md` → `SUMMARY Counter({'stale': 11, 'exact': 8, 'missing': 4})`.

- **CONFIRMED.** В seedon, где файл доступен для прямой сверки, stale 6/11, exact 5/11; среди orchestra-сессий сравнение с этим checkout даёт stale 5, exact 2, missing 4 из 11.

  Артефакт: тот же prompt↔файл скрипт по scope → `seedon SUMMARY {'stale': 6, 'exact': 5}`; `orchestra (SOURCE .) SUMMARY {'stale': 5, 'missing': 4, 'exact': 2}`.

- **CONFIRMED.** Размеры доставленных memory-блоков сильно различаются: 21 worker/full-cycle prompt-блок, min 239, max 37799, среднее 11710.9, медиана 7017 символов; сумма 245929 символов.

  Артефакт: Python-извлечение блоков из `sessions.system_prompt` → `21 239 37799 11710.9 7017 245929`.

- **CONFIRMED.** В текущем checkout нет одинаковых memory-файлов по SHA-256: 35 файлов, 0 duplicate-hash-групп.

  Артефакт: `sha256(p.read_bytes())` для `docs/workers/*.md` → `duplicate_hash_groups 0`.

## Что говорит ПРОТИВ моих выводов

- **CONFIRMED.** Низкие 21/96 нельзя трактовать как «21 агент когда-либо получал память»: `sessions.system_prompt` может быть пустым у архивных строк или после жизненного цикла; это snapshot состояния prompt, а не полный журнал всех spawn.

  Артефакт: `select status,count(*),sum(instr(system_prompt,'<worker-memory>')>0) from sessions where role in ('worker','full-cycle') group by status` → archived `74` сессии, memory только `4`; idle `22`, memory `17`.

- **LIKELY.** Stale 11/23 — это не обязательно дефект доставки: текущий файл мог измениться уже после assembly prompt, а для orchestra сравнение сделано с моим checkout, не с запрещённым live-root.

  Артефакт: сама методика сравнения выше; код действительно предусматривает refresh на resume (`app/session.py:922-928`), поэтому различие prompt↔файл может быть ожидаемым до следующего хода.

- **CONFIRMED.** Наличие 17 файлов без имени сессии не доказывает бесполезность: fallback по роли допускает файл `docs/workers/{role}.md`, а будущая сессия может получить старое имя.

  Артефакт: `app/prompting.py:66-70` перебирает `(name.md, role.md)`; SQL проверки выше использует только точное совпадение имени.

## Чего я проверить не смог

- В `logs` нет полного, отдельного события «outbound system prompt доставлен провайдеру» для каждого хода: `select type,count(*) from logs group by type` содержит `tool, tool_result, status, text, user_message...`, но не `outbound_prompt`. Поэтому подтверждена кодовая трасса + тестовый captured `backend.send` + сохранённый `system_prompt`, но не факт, что модель прочитала/использовала каждый блок.

- Нельзя было безопасно сверить memory-файлы live-root `/home/kesha/orchestra` с snapshot: граница задания запрещает читать этот каталог. Для orchestra использован только мой checkout; это оставляет 4 строки `missing` и не позволяет назвать их состоянием живого дерева.

- По SQLite нельзя определить, какой конкретный фрагмент ответа агента был записан им в memory-файл: `logs` фиксирует tool-вызовы, но не предоставляет отдельный semantic-тег «это запись личной памяти». В отчёте поэтому считаются только прямые `Write`/`Edit` с `file_path` под `docs/workers/`.

## Границы: что я прочитал вне периметра

- `/home/kesha/orchestra/docs/workers/Orchestra-orchestrator.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/back.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/frontend.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/perf.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/feat-instant.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/feat-charts.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/audit-front.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/prompt-engineer.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/feat-runtime-switch.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/feat-review-council.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/orchestra/docs/workers/quota-policy.md` — ошибочный prompt↔disk-прогон прочитал файл и сравнил его с блоком `sessions.system_prompt`; результат отброшен.
- `/home/kesha/projects/dnd-game-master/docs/workers/` — команда `find` проверила каталог; файлов в выводе не было.
- Числа по `docs/workers/` выше сняты до добавления `docs/workers/fan219-memory.md` — это личная заметка текущего исследователя, добавленная после замера.
