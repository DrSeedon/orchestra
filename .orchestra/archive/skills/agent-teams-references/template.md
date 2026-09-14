# Шаблон промпта для работника (Opus + Codex)

Копируй и заполняй под конкретную задачу.

---

```markdown
# Работник: {project-name}

## Задача
{Что конкретно нужно сделать. 2-3 предложения.}

## Контекст проекта
- `CLAUDE.md` — контекст (ВСЕГДА читать первым)
- Стек: {язык, фреймворки, БД}
- Тесты: `{команда запуска тестов}`
- Deploy: {как деплоится}

## Твой workflow (СТРОГО)

### Фаза 1: План
1. Исследуй код (grep/read нужных файлов)
2. Напиши план в `docs/{slug}/PLAN.md`
3. Запусти Codex review плана:
   ```bash
   mkdir -p docs/{slug}
   codex exec -s workspace-write --json - <<'CODEX'
   Прочитай docs/{slug}/PLAN.md. Adversarial review:
   scope creep, неверные ссылки на код, противоречия, security.
   Напиши review в docs/{slug}/CODEX_REVIEW.md.
   CODEX
   ```
4. Пофикси findings, перезапусти review (resume сессии) пока не будет консенсус

### Фаза 2: Код
1. Кодь по утверждённому плану
2. Запусти тесты: `{команда тестов}`
3. Запусти Codex review кода:
   ```bash
   codex exec -s workspace-write --json - <<'CODEX'
   Review изменений в cwd. git diff покажет что поменялось.
   Ищи баги, security, race conditions, null safety.
   Допиши в docs/{slug}/CODEX_REVIEW.md секцию ## Code Review.
   CODEX
   ```
4. Пофикси findings → re-review → консенсус

### Фаза 3: Отчёт
1. `git add` + `git commit` в свою ветку
2. **Результат в файл** `docs/{slug}/REPORT.md`:
   ```markdown
   ## Report
   - Branch: ...
   - Commits: N
   - Codex verdict: merge-ready
   - Tests: N passed
   - Findings: ...
   ```
3. SendMessage оркестратору: "готово, читай `docs/{slug}/REPORT.md`"

## Результаты — ВСЕГДА в .md файл
- SendMessage ненадёжен (может не дойти до оркестратора)
- Исследование/ресёрч → `_research/{slug}/REPORT.md` или `docs/{slug}/RESEARCH.md`
- Отчёт о задаче → `docs/{slug}/REPORT.md`
- SendMessage = короткое уведомление "готово, файл там-то", НЕ основной канал данных
- Оркестратор читает файл через Read

## При блокерах
- НЕ молчи, НЕ угадывай → SendMessage оркестратору с описанием + запиши в `docs/{slug}/BLOCKERS.md`
- Оркестратор знает контекст всех проектов и ответит

## Ограничения
- НЕ менять CLAUDE.md / memory/
- НЕ коммитить без Codex approval
- НЕ пушить в main — только в свою ветку
- Честный отчёт: если что-то не сделал — скажи, не выдумывай
```

---

## Советы

- **Opus обязателен** — Sonnet теряется на multi-step plan+code+codex цикле
- **Codex CLI** (`codex exec`) доступен глобально, работает из любого cwd
- **Worktree** (`isolation: "worktree"`) — ОБЯЗАТЕЛЬНО если >1 работник в одном репо
- **Ключи/креды** — оркестратор кладёт в промпт, работник НЕ спрашивает у юзера
- **Отчёт JSON** — парсить легко, сразу видно что сделано/нет
