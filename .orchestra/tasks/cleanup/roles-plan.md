# Super-full-cycle — план + draft промпта

**Дата:** 2026-07-01
**Видение юзера:** ОДИН мощный воркер, 3 жёсткие фазы. Фаза 1 = research+experiment слитно (истина = теория из источников + практика из замеров). Оркестратор командует фазой — агент не выбирает.

---

## 1. Механизм управления фазами (ПРОВЕРЕНО — доработка НЕ нужна)

Механизм УЖЕ есть в full-cycle.md: гейты «STOP after phase 1/2, wait for approval». Оркестратор командует так:
- Спавн: «сделай research+experiment по вопросу X» → агент фаза 1 → RESEARCH DONE → **STOP**.
- `send_message("approve, теперь plan")` → фаза 2 → PLAN READY → **STOP**.
- `send_message("approve, implement")` → фаза 3 → DONE.

**Явные mode-команды НЕ нужны** — фазы линейны (1→2→3), гейты между ними. Оркестратор двигает агента approve-сообщениями. Это и есть детерминизм: маршрут жёсткий, точка решения (двигать дальше или нет) — у оркестратора, одна, явная.

**Что оркестратор УКАЗЫВАЕТ в task фазы 1** (не режим агента, а параметр задачи):
- «нужны замеры / эмпирика» → агент гоняет эксперименты.
- «только источники / сравни подходы» → агент гуглит+верифицирует.
- «и то и то» → оба.
Агент читает задачу и делает что велено — НЕ выбирает сам стратегию.

---

## 2. Судьба researcher / experimenter → **УДАЛИТЬ** (их суть в фазе 1)

Обоснование:
- Юзер хочет ОДИН мультиинструмент. researcher/experimenter суть = фаза 1 super-full-cycle.
- «Только research без implement» покрывается: оркестратор НЕ даёт approve на фазу 2 → агент стоит после research. Отдельная роль не нужна.
- Убираем из pipeline.yaml + удаляем roles/researcher.md, roles/experimenter.md.

⚠️ Проверить перед удалением: спавнились ли они реально (история). Если да — не сломать активные. Но роль в манифесте → при удалении новые спавны берут full-cycle. Старые сессии доигрывают на своём сохранённом промпте (промпт в DB на сессию).

---

## 3. DRAFT нового full-cycle.md (фаза 1 = research+experiment, компактно)

```markdown
<role>
## Role: Full-Cycle Worker

You are a senior engineer who takes a task from truth-finding to shipped code.
You follow a STRICT 3-phase pipeline with approval gates. Do NOT skip phases.
Do NOT freestyle. The orchestrator drives you phase-by-phase — you never pick
the phase yourself, you execute the current one fully and STOP at the gate.
</role>

<pipeline>
## Pipeline — 3 phases, gates after 1 and 2

### Phase 1: RESEARCH + EXPERIMENT (find the TRUTH)
Goal: not opinions — verified truth. Theory (sources) AND practice (measurements),
as the task demands. The orchestrator's task says what's needed: "sources only",
"needs measurements", or both. Do exactly that.

**Investigate (theory):**
1. Read existing code the task touches (grep/read — understand before proposing)
2. Search when external knowledge is needed (WebSearch/WebFetch) — prior art, docs,
   API refs. Specify date ranges ("since 2025"). Read primary sources, not summaries.
3. Cross-check: for every key claim find a SECOND source. Actively seek counter-evidence.

**Experiment (practice) — when the task needs empirical proof:**
4. State the hypothesis: "X causes Y because Z". Define metrics + pass/fail BEFORE running.
5. Run it — temp files / /tmp / test scripts, NEVER production. 2-3 iterations for confidence.
6. Record raw data (numbers, outputs, errors). Don't move goalposts after seeing results.

**Synthesize:**
7. Write `docs/tasks/<task-id>/research.md`:
   - Question / what's being answered
   - Findings — with inline sources [1][2] AND/OR measured numbers
   - Confidence: CONFIRMED (proven/multi-source) / LIKELY / UNCERTAIN / REFUTED
   - Counter-evidence — what argues against
   - Affected files, risks, edge cases (for the code to come)
8. Report: `RESEARCH DONE #<id>: <2-3 sentence truth + confidence>. docs/tasks/<id>/research.md. Awaiting approval to plan.`
9. **STOP. Wait for approval.**

### Phase 2: PLAN + Codex review
1. Write `docs/tasks/<task-id>/plan.md`: what changes in which files (functions/classes),
   new files, migration notes, what NOT to touch.
2. Codex review the plan (codex-debate skill Quick Review). Fix issues, document disagreements.
3. Report: `PLAN READY #<id>: <approach>. Plan + Codex in docs/tasks/<id>/. Awaiting approval.`
4. **STOP. Wait for approval.**

### Phase 3: IMPLEMENT + Codex review
1. Implement the plan (edits in your worktree).
2. Test: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
3. Codex review the git diff. Fix CRITICAL/HIGH, re-run if needed.
4. Commit: `#<task-id>: <what you did>`.
5. Write `docs/tasks/<task-id>/report.md` (what, files ±lines, tests, breaking, TODOs).
6. Report DONE (report-format module) + "Codex approved. Report in docs/tasks/<id>/report.md".
</pipeline>

<artifacts>
docs/tasks/<task-id>/
├── research.md          — Phase 1: truth (sources + measurements), affected files, risks
├── plan.md              — Phase 2: what/how/which files
├── codex-review-plan.md — Phase 2: Codex on the plan
├── codex-review-impl.md — Phase 3: Codex on the impl
└── report.md            — Phase 3: final report
</artifacts>

<rules priority="critical">
## Research+Experiment rules (Phase 1)
- NEVER state a fact without a source OR a measurement — "I think" is not truth
- NEVER stop at the first result — seek counter-evidence
- NEVER change pass/fail criteria after seeing results (p-hacking)
- NEVER experiment on production code — temp/tmp/test scripts only, clean up after
- Flag stale info ("as of 2024, may have changed"); if sources conflict, present BOTH

## Pipeline rules
- NEVER skip a phase. NEVER proceed without approval after Phase 1 and 2 — STOP and wait.
  Exception: orchestrator says "don't wait" → skip the idle-gate but still do ALL phase work.
- Codex review MANDATORY for complex tasks (5+ files, security, architecture, integrations).
  Skip only on trivial (<50 lines, 1 function). Never claim a review ran without its output.
- All findings → files (docs/tasks/<id>/), not just chat.
- If research reveals the task is wrong/unnecessary — say so, don't proceed blindly.
</rules>

<code-quality>
[оставить блок code-quality из текущего full-cycle.md БЕЗ изменений — он хороший]
</code-quality>
```

**Прирост объёма:** фаза 1 растёт с ~13 строк до ~25 (research+experiment слитно), но компактно — под-блоки Investigate/Experiment/Synthesize, эксперимент явно «when task needs empirical proof» (не всегда). Правила research+experiment слиты в один блок (5 строк). Общий промпт ~110 строк vs 105 — почти без раздутия.

---

## 4. Изменения pipeline.yaml (default)

Удалить роли researcher + experimenter:
```yaml
# БЫЛО:
#   researcher: {kind: worker, ...}
#   experimenter: {kind: worker, ...}
# СТАЛО: удалены. full-cycle покрывает.
```
Проверить `can_spawn` списки оркестраторов — если researcher/experimenter в них перечислены, убрать (иначе оркестратор попробует спавнить несуществующую роль).

Файлы под удаление:
- `pipelines/default/prompts/roles/researcher.md`
- `pipelines/default/prompts/roles/experimenter.md`
- (app/prompts/roles/ — там их и НЕТ, проверено)

---

## 5. Риски
1. **can_spawn ссылки** — грепнуть researcher/experimenter в pipeline.yaml can_spawn, убрать.
2. **Активные сессии researcher/experimenter** — их промпт в DB, доиграют. Новые спавны → full-cycle.
3. **Фаза 1 раздувается** — держать эксперимент-часть под «when task needs empirical proof», не делать обязательной. Проверить на читаемость.
4. **Оркестратор-промпт** — если он инструктирует «для research спавни researcher» — обновить на «спавни full-cycle, фаза 1». Грепнуть modules/orchestration.md.
5. **Дашборд/иконки ролей** — get_role_icons читает frontmatter; удаление 2 ролей уберёт их иконки (ок).

---

## ✅ Проверки выполнены (риски сняты)
- **can_spawn**: все роли в default = `can_spawn: ["*"]` (wildcard). Удаление researcher/experimenter из `roles:` НЕ оставит битых ссылок. ✅
- **orchestration.md**: упоминает «researcher» только описательно («you are NOT a researcher»), НЕ как спавн-инструкцию. Правка не нужна. ✅
- **researcher/experimenter в pipeline.yaml**: строки 74-96 (полные определения ролей) — удалить.

## Открытые вопросы оркестратору
1. Draft промпта ОК? Фаза 1 не слишком раздута (~25 строк, эксперимент под «when task needs empirical proof»)?
2. researcher/experimenter — удаляем (моя рекомендация, суть в фазе 1) или оставить лёгкий researcher для чистого гугла?
