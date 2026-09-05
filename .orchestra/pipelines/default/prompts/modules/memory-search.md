<memory-search>
## Project memory — file-first mode

**Pre-work order:** `pwd` → short KB index → targeted retrieval → relevant code.
Do not preload every matching topic. The index is navigation, not an instruction to read
the whole library; source evidence is opened only when it affects the task.

`ORCHESTRA_LAYOUT_MISSING` or `ORCHESTRA_LAYOUT_PARTIAL` → stop and run the command from the error: `scripts/migrate_orchestra_layout.py --repair <absolute-repository>`. Never fall back to the old path.

**Step 1 — navigation.** Read `.orchestra/kb/README.md` and pick candidate topics.
Do not read their full sections before searching. For current operational questions,
follow the owner pointers in `current-operations.md` when that topic is present.

**Step 2 — lexical retrieval.** Выдели 1–3 отличительных поисковых якоря: exact symbol, path,
command, прежнее имя или существительное из формулировки задачи. Не передавай весь вопрос как
один literal. Сначала ищи только в `.orchestra/kb/`. Команда первого прохода —
`rg -l -i -F --glob '*.md'`; передай ей один якорь и каталог:

```bash
rg -l -i -F --glob '*.md' '<anchor>' .orchestra/kb
```

В найденных topic-файлах ищи второй якорь через `rg -n -i -F`, затем читай совпавшие факты
с заголовком раздела и соседним контекстом, а не весь раздел. `Established` — принятые
выводы; `Rejected`, `RETRACTED`, `superseded` не являются действующими рекомендациями.
`Historical observations` описывает прошлый срез, `Gaps` — неизвестность. Для старых тем
допустимы русские названия разделов. Дата доказательства не доказывает актуальность сегодня.
`.orchestra/tasks/` открывай только по ссылке из найденного факта.
Если KB ничего не дал, отдельный targeted `rg` по tasks разрешён, но его вывод не является promoted
memory.

Approved `links:` можно раскрыть только после того же literal filter и в пределах текущего context
budget. Retrieval раскрывает не больше одного перехода. Target topic читается один раз; его связи
рекурсивно не обходятся.

`search_memory` остаётся compatibility-тулом и не является обязательным шагом. Если он сообщает,
что семантический поиск выключен, используй предложенную команду `rg` и не повторяй вызов.

**Skip only for:** an exact local edit naming file + line/function + desired change; typo/format-only
work; running a named command/test; current-status lookup. Use grep for exact strings/current lines.

Compatibility search may include task files, project rules and agent messages. Scope is this repo; fresh merges
can lag, so verify current code. Use `cross_project=True` only when the task explicitly spans
repositories or shared infrastructure across them.

## Your own transcript — query it with code, don't re-read it

The project KB covers conclusions from PAST tasks. Your CURRENT run is stored server-side too;
one request returns it as structured JSON (`tool`, `tool_result`, `text`, `user_message`, each
with `id` and `ts`) — so you can grep, count and filter your own history instead of scrolling
context. It survives compaction, because it lives on the server, not in your window:

```bash
curl -s -H "Authorization: Bearer $INTERNAL_TOKEN" --get \
  --data-urlencode "scope=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" \
  "http://127.0.0.1:8888/api/sessions/$(basename "$(git rev-parse --show-toplevel)")/logs"
```

Both values derive themselves — run it as written. Never hand-write `scope`: it is the
REPOSITORY path (`/home/kesha/orchestra`), not the worktree directory name, and the endpoint
answers a bare `{"error":"not found"}` when it is wrong. Pipe into `python3 -c` and aggregate;
dumping the whole answer into context defeats the point.

Use it for questions about your own run — which files you already touched, what a command
printed 40 turns ago, how many times you retried something.
</memory-search>
