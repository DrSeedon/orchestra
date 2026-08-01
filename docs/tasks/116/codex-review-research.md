## Summary

Ну да, «независимые vertical slices» успели поделить один hash и не сказать ему об этом 😏

Исследование убедительно подтверждает саму проблему freshness, разумность hash-check и направление cache penalty у Claude. Выводы о Codex cache сформулированы достаточно осторожно: provider effect явно помечен как неизмеренный, поэтому отдельного замечания по стоимости нет.

Но перед Phase 2 нужны правки: шесть блокирующих пробелов затрагивают доказанность stale-count, приоритет инструкций, RAG watermark, retry semantics и зависимости тикетов.

## Findings

### blocking: Не выдавайте 28/33 skill copies за доказанный stale-count

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:131>)

Метод использует «resolved default pipeline role», хотя persisted `session.pipeline` входит в действующий runtime contract ([app/session.py](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/app/session.py:561>)), и исключает project-owned файлы только среди extras. Tracked required skill, изменённый проектом, либо skill из закреплённого non-default pipeline будет посчитан stale при расхождении с текущим default. Поэтому 28/33 сейчас является upper bound, а не «доказанным» числом; нужен пересчёт по persisted pipeline с отдельным managed/project-owned breakdown.

### blocking: Worker memory нельзя безусловно понижать до user priority

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:309>)

Сам документ устанавливает, что предыдущая `<worker-memory>` уже находится в persisted system prompt. Если новая memory удаляет или меняет предписывающее правило, user-tail delta не заменит старую system-версию: модель продолжит считать старое правило более приоритетным. T1 должен ограничиваться действительно append-only factual memory либо классифицировать удаления и конфликтующие/prescriptive изменения как authoritative refresh через T2.

### blocking: T1 поглощает mismatch, который должен запускать T2

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:463>)

T1 хранит и продвигает `prompt_hash` для static role layers после принятия user-priority delta, а T2 запускает authoritative reconnect только при hash mismatch. После T1 тот же component уже выглядит доставленным, поэтому последующая установка T2 не увидит необходимости поднять его до system/developer priority. Нужны разные `user_delivered_hash` и `authoritative_applied_hash`, либо static authoritative layers следует полностью убрать из T1; без этого тикеты не независимы.

### question: Чем подтверждается применение Codex developer instructions?

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:214>)

Исследование честно помечает Codex resume как protocol-confirmed, но T2 AC проверяет только наличие `developerInstructions` в request. Schema acceptance не доказывает, что provider применил новое значение к существующему thread; при молчаливом игнорировании implementation может продвинуть delivered hash и начать stale turn. Нужен provider probe до закрытия T2 либо контракт, при котором Codex authoritative refresh остаётся experimental и hash не считается применённым без наблюдаемого подтверждения.

### blocking: Ошибка записи generation не может сама записать состояние error

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:437>)

Утверждение «metadata write failed → state becomes unknown/error» невозможно, если `requested_generation` и error marker хранятся в той же `rag_state`: при отказе записи старый row может остаться `fresh`, хотя merge уже завершён. Нужен durable requested generation вне отказавшей RAG metadata либо fail-closed правило, запрещающее search возвращать `fresh` после неподтверждённой записи; одного additive `CREATE TABLE IF NOT EXISTS` для этого недостаточно.

### suggestion: Показывайте freshness всех проектов, участвовавших в cross-project search

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:443>)

`freshness_by_project` только для проектов, попавших в hits, скрывает самый важный случай: stale проект не дал результата именно из-за отставшего индекса. Это также слабее T4 AC «cross-project reports per-project freshness». Возвращайте state всех проектов, реально охваченных cross-project query, либо явное поле неполного coverage.

### blocking: `list_agents` не разрешает неизвестный outcome второго spawn POST

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:396>)

После timeout на initial-task delivery `list_agents` подтверждает только создание worker, но не отвечает, принял ли `/send` задачу. Сохранение существующей инструкции вызвать `send_message` может продублировать уже принятый turn, что противоречит conservative retry semantics. Semantic catch должен различать known delivery failure и `delivery_outcome_unknown`; во втором случае нельзя рекомендовать resend без проверки состояния/turn.

### blocking: #94 не обещает hash, который #116 объявляет своей зависимостью

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:545>)

#116 утверждает, что только потребляет предоставленный #94 catalog generation/hash, однако утверждённый T7/#94 contract обещает exact-set managed-skill sync и сохранение arbitrary snapshots, но не persisted catalog/delivered hash ([docs/tasks/90/plan.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/90/plan.md:104>); связь T7 с #94 зафиксирована в [docs/tasks/93/plan.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/93/plan.md:249>)). Нужно либо расширить AC #94, либо сделать вычисление catalog hash явной частью T2; текущая dependency заявлена нечестно.

## Verdict

**Needs revision before Phase 2.**

Базовые измерения и общая архитектура hash-at-send жизнеспособны, но candidate tickets пока не обеспечивают заявленную priority correctness, race-safe watermark и conservative partial-success handling. Сейчас это пять аккуратных билетов, у которых несколько деталей уже оформили совместную ипотеку.

## Round (2026-08-01T08:30:44Z)

## Summary

The document survived most of round one; Git HEAD, however, is still being asked to vouch for bytes it never saw 😏

Resolved: skill ownership, worker-memory priority, spawn outcome guidance, cross-project coverage, and #94 scope. Codex uncertainty and separate hash states are conceptually fixed, but two blocking ticket/design holes remain.

## Findings

### blocking: Bind `indexed_head` to the bytes actually indexed

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:490>)

Current backfill reads working-tree files, not Git objects. Counterexample: HEAD remains `A`, `foo.md` has uncommitted changes, the scan indexes those dirty bytes, both HEAD checks return `A`, and search reports `fresh_at_head` although commit `A`’s `foo.md` was never indexed. This is likely with 9/11 scopes dirty. Minimal correction: either scan files from the captured commit or require a docs-only dirty check before advancing `indexed_head`; otherwise return `unknown/working_tree_unchecked`, not `fresh_at_head`.

### blocking: Declare T2’s dependency on T1

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:545>)

T2 triggers from `authoritative_applied_hash` mismatch and advances that field, but T1 owns creation, persistence, recomputation, and gating of those hashes. Implementing T2 after only #93 cannot satisfy its own AC, and its file list lacks T1’s DB/manager work. Minimal correction: mark T2 `blocked-by: T1, #93` while retaining the additional #94 dependency for skills.

### question: Define migration semantics for existing sessions

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:531>)

What initial value does `authoritative_applied_hash` receive for 81 existing sessions? Seeding it from current sources falsely marks known drift as applied; leaving it empty fail-closed blocks every next turn whose historical delivery cannot be reconstructed, especially Codex sessions awaiting a provider probe. Add an explicit migration/rollout AC—preferably `unknown` with clearly stated blocking behavior—so T1’s operational effect and estimate are honest.

### suggestion: Remove the remaining Codex “LIKELY” claim

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:256>)

This paragraph still labels changed `developerInstructions` as “LIKELY,” contradicting the revised summary, T2 AC, and confidence section, which correctly say `UNCERTAIN`. Replace it with the same protocol-only wording so the artifact has one conclusion.

## Verdict

**Needs one more revision before Phase 2.**

Round-one blockers are substantially resolved, but T4 still cannot claim commit freshness from a dirty working-tree scan, and T2’s dependency graph remains false. The corrections are small and local—rather like checking the actual parcel instead of declaring it fresh because the shipping label matches.

## Round (2026-08-01T08:40:13Z)

## Summary

Apparently, by round three even Git HEAD was required to show supporting documents 😏

All round-two blockers are resolved. The RAG contract is now fail-closed, binds `indexed_head` to verified bytes, and prevents trust/result races. Legacy hash migration, T1→T2→#94 dependencies, Codex uncertainty, and measured costs are internally consistent. Prior dissent remains preserved.

## Findings

### suggestion: Align the overview with legacy compatibility mode

**File:** [docs/tasks/116/research.md](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-freshness/docs/tasks/116/research.md:38>)

The overview still says every failed/unverified authoritative refresh blocks the turn, while T1 correctly allows warning-only compatibility turns for `legacy_unknown/known_stale` sessions. Add that exception to the overview and §3.2; the ticket AC itself is unambiguous, so this is documentation consistency rather than a blocker.

## Verdict

**APPROVED — ready for Phase 2.**

No remaining blocking correctness, race, dependency, or cost claim was found. The third inspection finally checked both the shipping label and what was actually inside the parcel.
