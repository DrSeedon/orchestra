<knowledge>
## Knowledge: where it lives, how you find it, what it costs (all agents)

Canonical project memory lives in `.orchestra/kb/`. Task artifacts under `.orchestra/tasks/<id>/`
are supporting evidence, not a second memory store.

**Where your knowledge goes.** NEVER use the runtime's own memory directory
(`~/.claude/projects/.../memory/`) — no agent here can read it back, and on this machine it does
not exist. Durable knowledge goes to files in the repo: a lesson about how YOU work →
`.orchestra/workers/<your-name>.md`; a rule for the project → its canonical owner under the
project authoring policy; a research finding → a topic in `.orchestra/kb/` plus its evidence in
`.orchestra/tasks/<id>/`. Context is lost on compaction and restart; files are not.

**A new topic needs two things, and this rule has exactly one owner — this block.** The topic file
in `.orchestra/kb/`, AND its one-line description in `.orchestra/kb/README.md`. The platform builds
the index every agent sees from that README (`app/kb_index.py`), so a topic without its line
reaches nobody, and a line without its file breaks prompt assembly. Format and section rules live
in `.orchestra/guides/knowledge-authoring.md`; do not restate them elsewhere.

### Finding something without reading everything

**Pre-work order:** `pwd` → the topic index already in your prompt → targeted retrieval → the
relevant code. The index is navigation, not an instruction to read the library; open source
evidence only when it changes what you do.

`ORCHESTRA_LAYOUT_MISSING` or `ORCHESTRA_LAYOUT_PARTIAL` → stop and run the command from the error:
`scripts/migrate_orchestra_layout.py --repair <absolute-repository>`. Never fall back to the old path.

**Step 1 — navigation.** Pick candidate topics from the index in your prompt (or
`.orchestra/kb/README.md` if a project has none). Do not read their full text before searching.
For current operational questions follow the owner pointers in `current-operations.md`.

**Step 2 — lexical retrieval.** Выдели 1–3 отличительных якоря: exact symbol, path, command,
прежнее имя или существительное из формулировки задачи. Не передавай весь вопрос одним literal.
Сначала ищи только в `.orchestra/kb/`:

```bash
rg -l -i -F --glob '*.md' '<anchor>' .orchestra/kb
```

В найденных темах ищи второй якорь через `rg -n -i -F`, затем читай совпавший факт с заголовком
раздела и соседним контекстом, а не весь раздел. `Established` — принятые выводы; `Rejected`,
`RETRACTED`, `superseded` не являются действующими рекомендациями; `Historical observations` —
прошлый срез; `Gaps` — неизвестность. Дата доказательства не доказывает актуальность сегодня.
`.orchestra/tasks/` открывай только по ссылке из найденного факта; если ссылка несёт коммит,
читай через `git show <sha>:<путь>` — файла может уже не быть на диске.
Если KB ничего не дал, отдельный targeted `rg` по tasks разрешён, но его вывод не является
принятым знанием.

**Семантического поиска у нас нет, и флаг тут ни при чём.** При `active_owner=canonical`
(`app/routes/memory.py:40`) запрос до RAG не доходит вовсе: сначала подстрочный матч по записям
(`app/ia/project_knowledge.py:305`), затем `LIKE` по логам — то есть поиск лексический по
устройству маршрута, а не потому, что что-то отключили. Инструмент `search_memory` тебе
по-прежнему раздаётся и на отказ отвечает подсказкой — не повторяй вызов, уходи в `rg` по якорям.
Его хранилище указателей на 99.5% ведёт в дерево, удалённое миграцией раскладки (замер #524:
резолвится 64 записи из 12 759), поэтому пустой ответ оттуда ничего не доказывает.

**Skip retrieval only for:** точечную правку, где названы файл, строка/функция и желаемое
изменение; правку опечатки или форматирования; запуск названной команды или теста; вопрос о
текущем состоянии. Для точных строк и живого кода — grep, не память.

### Your own transcript — query it with code, don't re-read it

The KB holds conclusions from PAST tasks. Your CURRENT run is stored server-side as structured
JSON (`tool`, `tool_result`, `text`, `user_message`, each with `id` and `ts`), so you can grep,
count and filter your own history instead of scrolling context. It survives compaction:

```bash
curl -s -H "Authorization: Bearer $INTERNAL_TOKEN" --get \
  --data-urlencode "scope=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" \
  "http://127.0.0.1:8888/api/sessions/$(basename "$(git rev-parse --show-toplevel)")/logs"
```

Both values derive themselves — run it as written. Never hand-write `scope`: it is the REPOSITORY
path, not the worktree directory name, and the endpoint answers a bare `{"error":"not found"}`
when it is wrong. Pipe into `python3 -c` and aggregate; dumping the whole answer into context
defeats the point. Use it for questions about your own run — which files you already touched, what
a command printed 40 turns ago, how many times you retried something.

### Context economy

Every tool_result stays in your context and is re-read every turn. Minimize replay:
- grep/search BEFORE a full Read — find the lines, then Read with offset+limit
- For literal-context search use `grep -aboF '<literal>' <file>` and slice by byte offset in
  Python; avoid `.{0,N}` bounded windows (`N>=20`) for grep-like tools because of the V8-heap
  blowup path documented in the knowledge base
- Large exploration: spawn-capable roles may delegate a bounded slice; terminal workers report
  scope growth to their orchestrator instead of spawning
- Workers: no narration between tool calls. One line before your first action, one at blockers,
  and the DONE report. Your thinking block does the reasoning — don't duplicate it in chat
</knowledge>
