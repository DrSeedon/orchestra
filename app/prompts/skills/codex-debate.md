---
name: codex-debate
description: "Cross-LLM adversarial review через Codex CLI (GPT-5.5). Персистентные сессии, multi-round debate до консенсуса, Conventional Comments. Триггеры: 'спроси кодекса', 'кодекс ревью', 'ревьюй через кодекса', 'второе мнение', 'cross-review', 'adversarial review', 'переспроси кодекса', 'уточни у кодекса', 'продолжи с кодексом', '/codex', '/codex-debate'. НЕ юзать на тривиальных задачах."
---

# Codex Debate — cross-LLM adversarial review через GPT-5.5

## Purpose
Adversarial review плана/кода/решения через Codex CLI (GPT-5.5). Codex исследует код через shell, пишет результат в `docs/tasks/<id>/codex_<slug>.md`. Claude итерирует с ним до консенсуса. Юзеру показывается финал.

## Главный принцип — ВТОРОЕ МНЕНИЕ, НЕ ИСТИНА

Codex — другая модель с другими bias'ами. Часто прав, но **не всегда**. Claude должен:
- **Прислушиваться** к каждому замечанию
- **Проверять** все blocking-замечания через код (`grep`, `cat`, `ls`) **перед** тем как принять
- **Спорить** если не согласен — через resume сессии с контраргументами из кода
- **Эскалировать юзеру** если Codex просит удалить существующий функционал или поменять архитектуру
- **Не соглашаться слепо** — это обесценивает весь review

При расхождении формат для юзера: "Codex говорит X. Я проверил — [согласен / не согласен потому что Y]. Хочешь чтобы я вступил в дебаты с ним?"

## When to use
- "спроси кодекса", "кодекс ревью", "ревьюй через кодекса"
- "второе мнение", "cross-review", "adversarial review"
- "переспроси кодекса", "уточни у кодекса", "продолжи с кодексом" → **resume сессии, НЕ новая**
- `/codex` или `/codex-debate`
- Claude сам предлагает review для спорных решений — но **только с явного "да" юзера**

## When NOT to use
- Мелкие вопросы, тривиальные правки — трата токенов
- Одноразовые вопросы без feature-контекста → используй ephemeral mode

## Conventional Comments

Формат каждого замечания: `<prefix>: file:line — проблема → предложение`

| Prefix | Значение |
|---|---|
| `blocking:` | must fix, мерж невозможен. Баги, security, data loss |
| `suggestion:` | рекомендация. Улучшит код, но не блокирует |
| `question:` | нужен ответ автора |
| `thought:` | мысль вслух, не требует действия |
| `nit:` | мелочь, можно скипнуть |

## Pre-Flight

1. `command -v codex >/dev/null 2>&1` — иначе стоп: "codex CLI не установлен"
2. Определить **task_dir** — `docs/tasks/<id>/` (создать если нет)
3. Определить **slug** — kebab-case тема: `plan-review`, `code-review`, `architecture`. Спросить юзера при первом вызове, на resume — по контексту
4. **project_root** — корень проекта (cwd). Codex запускается оттуда

## Session Management

Персистентные сессии в `<task_dir>/codex_sessions.json`:
```json
{
  "sessions": {
    "<slug>": {
      "uuid": "<codex-thread-id>",
      "topic": "plan review",
      "started": "2026-05-20T10:00:00Z",
      "last_used": "2026-05-20T10:15:00Z",
      "turns": 1
    }
  }
}
```

Один slug = один файл `codex_<slug>.md` + одна запись в sessions.json. НЕ придумывать новый slug при resume.

### Новая сессия или resume?
```bash
TASK_DIR="docs/tasks/<id>"
SESSIONS_JSON="$TASK_DIR/codex_sessions.json"
SLUG="<slug>"
OUTPUT_FILE="$TASK_DIR/codex_${SLUG}.md"

mkdir -p "$TASK_DIR"
[ -f "$SESSIONS_JSON" ] || echo '{"sessions": {}}' > "$SESSIONS_JSON"
UUID=$(jq -r --arg slug "$SLUG" '.sessions[$slug].uuid // empty' "$SESSIONS_JSON")
```
- `$UUID` пустой → новая сессия
- `$UUID` есть + юзер говорит "продолжи/переспроси" → resume
- Юзер явно сказал "с нуля" → новая сессия (перезаписать UUID)

## New Session

Промпт через temp-файл (безопасный quoting):

```bash
cat > /tmp/codex-prompt-$$.txt <<EOF
Ты adversarial code reviewer. cwd — проект Orchestra (Python, FastAPI, SQLite).

<ЗАДАЧА: конкретная — прочитай план, ревьюй diff, и т.д.>

OUTPUT FILE: $OUTPUT_FILE

ИНСТРУКЦИИ:
1. Создай файл $OUTPUT_FILE с frontmatter:
   ---
   slug: $SLUG
   topic: <тема>
   created: <ISO timestamp>
   model: gpt-5.5
   ---
2. Структура:
   ## Tests
   <вывод тестов или "не применимо">
   ## Round 1 — <ISO>
   ### Summary
   <3-5 предложений>
   ### Замечания
   <Conventional Comments: blocking/suggestion/question/thought/nit>
   Каждое: file:line — проблема → фикс.
   ### Вердикт
   <рабочий / требует доработки / выкинуть>
3. Не трогай другие файлы. Только $OUTPUT_FILE.
4. Напиши на русском языке.

PROJECT CONTEXT (calibrate severity):
- Stack: Python 3.12+, FastAPI, SQLite, claude-agent-sdk
- Stage: MVP, small team
- Scale: ~10 users, NOT millions
- Philosophy: simple, flat, minimal abstractions. 3 lines > premature abstraction
- "blocking" = crash/corrupt/security. "suggestion" = real improvement. "nit" = skip
EOF

HTTPS_PROXY= HTTP_PROXY= timeout 300 codex exec \
  -s workspace-write \
  -c model_reasoning_effort="high" \
  --skip-git-repo-check \
  --json \
  -o /tmp/codex-last-msg.txt \
  - < /tmp/codex-prompt-$$.txt 2>&1 | tee /tmp/codex-last.jsonl
echo "EXIT:$?"

rm -f /tmp/codex-prompt-$$.txt
```

Pass `timeout: 300000` to Bash tool.

After completion — extract UUID and save:
```bash
UUID=$(jq -r 'select(.type=="thread.started") | .thread_id' /tmp/codex-last.jsonl | head -1)
[ -z "$UUID" ] && UUID=$(jq -r 'select(.type=="session_meta") | .payload.id' /tmp/codex-last.jsonl | head -1)

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq --arg slug "$SLUG" --arg uuid "$UUID" --arg topic "<topic>" --arg now "$NOW" \
  '.sessions[$slug] = {uuid: $uuid, topic: $topic, started: $now, last_used: $now, turns: 1}' \
  "$SESSIONS_JSON" > "$SESSIONS_JSON.tmp" && mv "$SESSIONS_JSON.tmp" "$SESSIONS_JSON"

test -s "$OUTPUT_FILE" || echo "WARNING: $OUTPUT_FILE empty or not created"
```

## Resume Session

```bash
UUID=$(jq -r --arg slug "$SLUG" '.sessions[$slug].uuid' "$SESSIONS_JSON")
TURN=$(($(jq -r --arg slug "$SLUG" '.sessions[$slug].turns' "$SESSIONS_JSON") + 1))

cat > /tmp/codex-prompt-$$.txt <<EOF
<ЗАДАЧА: follow-up — "I fixed N issues, re-review" / "Claude не согласен с X, аргументы: ...">

OUTPUT: допиши секцию ## Round $TURN в файл $OUTPUT_FILE. НЕ перезаписывай предыдущие раунды.

Формат:
## Round $TURN — <ISO>
### Re-review
<статус каждого предыдущего blocking: FIXED / STILL BROKEN / NEW BUG INTRODUCED>
### Новые замечания
<Conventional Comments если есть>
### Вердикт раунда
<APPROVED / требует ещё фиксов>

Напиши на русском.
EOF

HTTPS_PROXY= HTTP_PROXY= timeout 300 codex exec resume "$UUID" \
  -c model_reasoning_effort="high" \
  --skip-git-repo-check \
  --json \
  -o /tmp/codex-last-msg.txt \
  - < /tmp/codex-prompt-$$.txt 2>&1 | tee -a /tmp/codex-last.jsonl
echo "EXIT:$?"

rm -f /tmp/codex-prompt-$$.txt

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq --arg slug "$SLUG" --arg now "$NOW" \
  '.sessions[$slug].last_used = $now | .sessions[$slug].turns += 1' \
  "$SESSIONS_JSON" > "$SESSIONS_JSON.tmp" && mv "$SESSIONS_JSON.tmp" "$SESSIONS_JSON"
```

**CRITICAL:** `codex exec resume` does NOT support `-s` flag — sandbox inherits from original session.

## Ephemeral Mode (no task context)

For one-off questions outside task workflow:
```bash
HTTPS_PROXY= HTTP_PROXY= timeout 300 codex exec \
  -s read-only \
  --skip-git-repo-check \
  --ephemeral \
  -c model_reasoning_effort="medium" \
  -o /tmp/codex-last-msg.txt \
  "<вопрос>" 2>&1; echo "EXIT:$?"

cat /tmp/codex-last-msg.txt
```

No session saved, resume impossible.

## Auto-Iteration to Consensus

After Round 1 — iterate WITHOUT bothering the user:

1. Read `codex_<slug>.md`, parse findings
2. For each **blocking** — verify via code (grep/cat/ls). Decide: ACK / DISAGREE / PARTIAL
3. **Escalate to user** if Codex wants to:
   - Delete existing functionality
   - Substantially change architecture of working components
   - Something with unclear consequences
4. Fix ACK'd findings (Edit tool)
5. Resume session with changelog (see Resume section)
6. Codex appends Round N
7. Loop until:
   - Codex writes "APPROVED" / "no remaining blockers"
   - 5+ rounds without progress → decide yourself, show user
   - Escalation triggered → stop, ask user

## Show Result to User

```
Codex review done (slug: `<slug>`, rounds: N)

Verdict: <APPROVED / needs work / reject>

Findings:
- blocking: X found, Y fixed, Z rejected (with reasoning)
- suggestion: M found, K accepted
- nit: skipped

Full review: `docs/tasks/<id>/codex_<slug>.md`

Next:
- If OK — continue / push
- Want more debate — "переспроси кодекса про <X>"
```

## Prompt Templates

### Plan/Spec Review
```
Ты adversarial code reviewer. cwd — <project_root>.
1. Прочитай $PLAN_FILE
2. Исследуй код — ls/grep/cat — проверь ссылки из плана (файлы, функции, сигнатуры)
3. Запусти тесты если есть pytest
4. Запиши review в $OUTPUT_FILE
Ищи: scope creep, неверные ссылки, противоречия, security/race conditions.
Не больше 10 замечаний. Конкретика.
```

### Code Review (diff)
```
Ты adversarial code reviewer. cwd — <project_root>.
1. Найди тест-раннер, запусти
2. Посмотри diff: git diff или git diff <base>...HEAD
3. Прочитай изменённые файлы
4. Найди баги, security, breaking changes, race conditions
5. Запиши review в $OUTPUT_FILE
Не рефакторь работающий код. Нет замечаний — пиши "ACK".
```

### Debate (Claude disagrees)
```
Claude не согласен с замечаниями <ID-список>. Аргументы:
<аргументы с фактами из кода>
Проверь:
- ACK — принимаю, Claude прав
- Контраргумент — обоснование с фактами из кода
- Частично — что принято, что нет
Допиши ## Round N в $OUTPUT_FILE.
```

### Re-review After Fix
```
Применены фиксы: <changelog>
Для каждого предыдущего замечания: FIXED / STILL BROKEN / NEW BUG INTRODUCED.
Все blocking закрыты и нет новых → APPROVED.
Допиши ## Round N в $OUTPUT_FILE.
```

## Error Handling

| Error | Action |
|---|---|
| `codex not found` | Stop: "codex CLI не установлен, `npm i -g @openai/codex`" |
| `402 Payment Required` | User: "проверь chatgpt.com → Settings → Billing, потом `codex logout && codex login`" |
| `bwrap: Operation not permitted` | `sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0` |
| Resume with stale UUID | Delete from sessions.json, start fresh: "сессия протухла, начинаю новую" |
| Output file empty | Check `/tmp/codex-last.jsonl` last 30 lines |
| Codex changed wrong files | `git status` after run — only `codex_<slug>.md` should change |
| Rate limit | Stop, show user, do NOT retry |
| Timeout >5 min | Shorten prompt or use background run |

## Technical Notes

- **Proxy**: `HTTPS_PROXY= HTTP_PROXY=` — clear proxy for Codex (it uses OpenAI, not Anthropic)
- **Model**: `gpt-5.5` + `model_reasoning_effort="high"` for reviews, `medium` for ephemeral
- **Sandbox**: `workspace-write` for review (write output file), `read-only` for ephemeral
- **Sessions**: `codex_sessions.json` in task dir (NOT /tmp — survives reboot)
- **Raw JSONL**: `~/.codex/sessions/<year>/<month>/<UUID>.jsonl` (Codex-managed)
- **Security**: `workspace-write` = Codex reads all files in cwd. Check for `.env`/credentials before running
- **Bash timeout**: Always `timeout: 300000` on Bash tool + `timeout 300` in command

## What NOT to Do

- Do NOT show raw JSONL to user — only review file path + summary
- Do NOT create new session on follow-up — use `resume`
- Do NOT forget "напиши на русском" in prompts
- Do NOT forget OUTPUT FILE and PROJECT CONTEXT in prompts
- Do NOT agree blindly with blocking findings — verify via code
- Do NOT use `-s danger-full-access` without explicit user approval
- Do NOT run `workspace-write` in directories with secrets
- Do NOT bother user on every round — iterate to consensus (escalate only for deletions/arch changes)
- Do NOT save session pointers in `/tmp` — use task dir
