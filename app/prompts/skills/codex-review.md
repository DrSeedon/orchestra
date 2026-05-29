---
name: codex-review
description: Cross-LLM adversarial review через Codex CLI (GPT-5.5)
---

# Codex Review — cross-LLM ревью

## Когда использовать
- После написания плана — ревью плана перед имплементацией
- После имплементации — ревью кода перед коммитом
- При спорных архитектурных решениях — второе мнение

## Принцип — ВТОРОЕ МНЕНИЕ, НЕ ИСТИНА

Codex — другая модель. Часто прав, но не всегда. Ты должен:
- Проверять каждое blocking-замечание через код (grep, read)
- Спорить если не согласен — через resume сессии
- Не соглашаться слепо

## Процесс

### 1. Запуск ревью
```bash
cd {cwd}
mkdir -p /tmp/codex-sessions
SLUG="task-review"  # или имя задачи
codex exec -s workspace-write --json - <<'CODEX_PROMPT' 2>&1 | tee /tmp/codex-sessions/${SLUG}.jsonl
PROJECT CONTEXT (calibrate review severity):
- Scale: small team, MVP stage
- Philosophy: simple, flat, minimal abstractions
- What matters: correctness, security, data integrity
- blocking = crash/corrupt/security. suggestion = real improvement. nit = skip

Review the following: <план или diff>
Write review to docs/tasks/<id>/CODEX_REVIEW.md
CODEX_PROMPT
```

### 2. Сохранить session_id
```bash
SESSION_ID=$(jq -r 'select(.type=="thread.started") | .thread_id' /tmp/codex-sessions/${SLUG}.jsonl 2>/dev/null | head -1)
test -n "$SESSION_ID" && echo "$SESSION_ID" > /tmp/codex-sessions/${SLUG}.session
```

### 3. Итерация до консенсуса
1. Прочитать ревью, проверить каждое замечание через код
2. Пофиксить blocking/suggestion замечания
3. Resume сессию:
```bash
SESSION_ID=$(cat /tmp/codex-sessions/${SLUG}.session)
codex exec resume "$SESSION_ID" --skip-git-repo-check --json - <<'CODEX_PROMPT' 2>&1 | tee -a /tmp/codex-sessions/${SLUG}.jsonl
Fixed N findings. Re-review.
CODEX_PROMPT
```
4. Повторять пока Codex не скажет APPROVED или 5+ раундов

### 4. Формат замечаний
- **blocking:** — must fix, баги/security/data loss
- **suggestion:** — рекомендация, не блокирует
- **question:** — нужен ответ
- **nit:** — мелочь, пропускаем

## Правила
- Codex ВСЕГДА в background (`run_in_background: true`)
- Не показывать сырой JSONL — только итоги
- Resume, не новая сессия для follow-up
- `workspace-write` sandbox (не `danger-full-access`)
