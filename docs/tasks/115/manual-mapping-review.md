# #115 — решение по восьми manual commits без numeric task ref

## Вердикт

**Рекомендация по всем восьми: оставить task link пустым навсегда.** Это не восемь
плохо распарсенных номеров. В frozen evidence нет ни одного numeric task id в
commit subject, worker branch/worktree или `sessions.task_id`; доступные
assignment rows для `sol-efficiency` и `prompt-engineer` также не содержат номера.
Первоначальный assignment `research-subscription` уже выпал из retained logs, и
его содержимое здесь не утверждается. В `tm_tasks` проекта Orchestra нет
title/description match для
`sol-efficiency`, `subscription-strategy`, `prompt-engineer`, `self-improvement`
или `pre-send`; подбирать соседнюю по времени задачу было бы ложной атрибуцией.

| № | Target commit | Caller / project | Что физически произошло | Что могло быть задачей | Рекомендация |
|---:|---|---|---|---|---|
| 1 | `ca6b858` | `Orchestra-orchestrator` / Orchestra | `cherry_pick` source `b61a7a4` из `research-sol-efficiency`; добавлены raw TSV/scripts в `docs/tasks/sol-efficiency/` | Назначение log `292860`: отдельный research-only «форензика логов Codex/Sol», без `#N`; session task пуст, branch/worktree содержат только slug. `#86` лишь тематически близок, но был закрыт 2026-06-29 и в назначении не упомянут | **Оставить непривязанным** |
| 2 | `ed5b5e3` | тот же / Orchestra | `cherry_pick` source `35e2af0`; добавлен `docs/tasks/sol-efficiency/research.md` | Та же unnumbered работа, что №1; отдельного task evidence для второго commit нет | **Оставить непривязанным** |
| 3 | `a1a3d3b` | тот же / Orchestra | `cherry_pick` source `d8d57ce`; robustness pass того же research | Та же unnumbered работа, что №1–2; отдельного task evidence для третьего commit нет | **Оставить непривязанным** |
| 4 | `9793a44` | `Orchestra-orchestrator` / Orchestra | `cherry_pick_conflict_resolution` source `eeac43a`; взяты `docs/tasks/subscription-strategy/{research,addendum}` | Worker/session/branch используют только slug `research-subscription`; source subject `#subscription-strategy`, не numeric ref. Session task пуст; matching Task Manager task отсутствует. Initial assignment row не сохранился, поэтому его содержание неизвестно | **Оставить непривязанным** |
| 5 | `7a8e1b7` | тот же / Orchestra | `cherry_pick_conflict_resolution` source `6f13f75`; завершён sequencer, добавлены measurements/Codex review | Та же slug-based `subscription-strategy`, что №4; initial assignment неизвестен, но ни один сохранившийся provenance layer не даёт numeric ref | **Оставить непривязанным** |
| 6 | `aa3d382` | `Orchestra-orchestrator` / Orchestra | чистый manual `squash` ветки `adhoc-568267/prompt-engineer`, source `99e5e5c`; создан `docs/workers/prompt-engineer.md` | Назначение log `369407`: «ЗАДАЧА ОТ ЮЗЕРА» — личная база знаний, без номера. `#81` соблазнительно близок по теме, но это уже закрытая 17 июня механика auto-inject, а не содержание личного файла | **Оставить непривязанным** |
| 7 | `c277632` | тот же / Orchestra | manual `squash_conflict_resolution`; `add/add` в `docs/workers/prompt-engineer.md`, взята worker version; source chain `8181ec1` (`self-improvement`) + `8646a13` (личная память) | Назначение log `369739`: «ВТОРАЯ ЗАДАЧА», без номера. `#84 Self-learning` — другая старая backlog-задача и нигде не названа | **Оставить непривязанным** |
| 8 | `6926fea` | тот же / Orchestra | manual `squash_conflict_resolution`; повторный `add/add`, взята worker version; source chain `7d6b1f0` (orchestration pre-send gate) + `0bddcfd` (личная память) | Назначение log `371200`: «НОВАЯ ЗАДАЧА», без номера. `#111` и `#114` названы только как инцидент, который выявил слабое правило; commit не реализует ни гибернацию, ни dirty `BUGS.md`. `#115` уже существовал, но это отдельный merge research; `#116/#117` созданы позже commit | **Оставить непривязанным** |

Короткий ответ для решения: **`1–8 → пропустить`**.

## Четвёртый сегодняшний prompt-engineer merge вне восьмёрки

`9ff4a7f53708ad365b73cf1db1cefc8a5bd8dad3` создан после frozen cutoff
`logs.id <= 371999`: orchestrator получил сообщение
`[from:prompt-engineer] DONE … commit 35f0229` в inbox log `372506`; затем создал
свежую ветку от `main`,
cherry-pick'нул именно `35f0229`, затем сделал `ff-only` в `main` (logs `372616`,
`372634`).
Subject `#prompt-policy`, numeric task ref отсутствует; target является ancestor
`main` и отсутствует в `tm_tasks.git_commits`.

Для task linking решение владельца: **не привязывать**. Но это отдельный manual
integration с exact source-SHA → named-worker lineage, прошедший мимо
RAG/lifecycle/ref side effects. Владелец одобрил добавление log `384556`:
classifier расширен **дополнительным**, а не замещающим режимом
`[from:worker] DONE exact SHA → caller exact cherry-pick → target SHA → ff-only
main`; source/target patch-id совпадает, оба objects закреплены refs. `9ff4a7f`
теперь 33-я manifest entry / 32-й recovery candidate с
`task_link_disposition=skip_owner_confirmed_no_numeric_ref`.

## Основание и границы уверенности

- Frozen manifest: `docs/tasks/115/recovery-input.json`.
- Read-only SQLite: exact assignments `292860`, `369407`, `369739`, `371200`;
  merge/cherry-pick evidence `305700–305707`, `370921–370922`,
  `371461–371479`, `371945–371954`, `372616–372655`.
- Git: exact target/source subjects, changed paths and main ancestry.
- Live Task Manager: exact task list and creation timestamps; keyword search по
  title+description дал zero matches для пяти slug'ов выше.

Confidence: **CONFIRMED** для физического Git-механизма и отсутствия numeric
evidence; **UNCERTAIN** только для невысказанного человеческого намерения. Такое
намерение нельзя превращать в task link задним числом без exact номера владельца.
