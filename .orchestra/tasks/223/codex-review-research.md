## Summary

Исследование правильно находит prompt-only seam, отсутствие runtime-барьера и дыру в защите полученного оракула. Однако экономика координации названа причинной без достаточного контрфакта, пересчёт 6–10% в 4.8–8.0% смешивает несопоставимые замеры, а контракт «одна Luna → Sol» шире текущего `model-routing`.

Доказательство чтения артефакта: “Результат ребёнка — улика, не приёмка самим ребёнком.”

## Findings

suggestion: `docs/tasks/223/research.md:14-21` — разложение `$7.452 = $6.579 + $0.874` не отделяет причинную стоимость делегирования. Ход `$6.579` прямо включает спавн и подготовку стенда, которых нет в baseline без делегирования, поэтому нельзя утверждать, что весь он «нужен и в baseline». Разметьте его как смешанный расход с неизвестной делегационной долей.

suggestion: `docs/tasks/223/research.md:17-20,167-185` — `$0.874/$0.877` измеряют полные ходы, вызванные сообщениями, а не чистую фиксированную цену wake. В них 4.7–6.6K output-токенов и содержательная реакция родителя; без пустого/контрольного wake или сопоставимого хода нельзя называть величину причинной ценой самого пробуждения. Корректнее: «наблюдённая стоимость turn после сообщения».

suggestion: `docs/tasks/223/research.md:23-31` — переход `6–10% → 4.8–8.0%` не обоснован единым знаменателем. `6–10%` в #210 получены из долей строк двух implementation diff, тогда как коэффициент 80% использует один Opus-тикет, Luna research-срез из #219 и parent wake другой фазы. Он также предполагает одинаковые `B`, переносимую долю и ровно один wake для всей популяции. Оставьте 6–10% исходным порядком величины, а `$4.06` — отдельным сценарным расчётом, не новым агрегатным процентом.

suggestion: `docs/tasks/223/research.md:33-36,155-165` — текущий `model-routing.md:10-11` не гарантирует универсальное «ровно одна Luna, затем Sol»: Sol разрешён сразу для закрытой, но сложной работы, а escalation явно определён только для красной команды или недоказанного AC. Clarification, WIP/STOP и изменение oracle исследование самостоятельно расширяет до того же контракта. Phase 2 должна явно закрепить эти исходы в `full-cycle.md` либо честно назвать их новой политикой #223.

suggestion: `docs/tasks/223/research.md:61-67` — H4 объявлена `REFUTED`, хотя её фальсификатор допускает либо существующее правило, либо эмпирический второй Luna-заход; найдено только правило, а полезность второго захода не измерялась. Это нормативное решение, не эмпирическое опровержение. Пометьте H4 как `NOT TESTED; policy rejects retry`.

suggestion: `docs/tasks/223/research.md:187-197,230-237` — один последовательный ребёнок действительно не требует агрегирующего барьера #219, но вывод неполон для `failed/timeout/killed`: текущие ссылки доказывают wake по `send_message`, а не гарантированную доставку положительного terminal token при молчаливой смерти ребёнка. Prompt-only схема должна либо ограничить контракт нормальным `DONE` и явно признать этот failure gap, либо сослаться на существующий lifecycle-механизм, который гарантированно будит родителя.

suggestion: `docs/tasks/223/research.md:125-134` — вывод о `worker.md` верен: `Never author` запрещает создание своего acceptance test, но не запрещает редактировать, удалять, переименовывать, skip/xfail или ослаблять полученный. Immutable-oracle guard следует сделать обязательной частью worker-facing текста и parent acceptance, а не оставлять `worker.md` «optional», иначе защита зависит от того, насколько полно родитель сформулирует каждый тикет.

## Verdict

Needs revision. Блокирующих crash/security/data-loss дефектов нет, но три несущих утверждения — причинная цена wake, агрегатные 4.8–8.0% и «текущий контракт уже гарантирует одну Luna → Sol» — сейчас сильнее приведённых доказательств.

## Round (2026-08-12T09:11:34Z)

## Re-review status

1. **FIXED** — `$6.579` is correctly classified as mixed and non-identifiable.
2. **FIXED** — `$0.874/$0.877` are now message-triggered parent turns, not pure wake cost.
3. **FIXED** — `4.8–8.0%` is withdrawn; `$4.06` is clearly sensitivity analysis across mismatched measurements.
4. **STILL BROKEN** — the main routing discussion is corrected, but one stale statement remains.
5. **FIXED** — H4 is `NOT TESTED`, with retry rejected normatively by existing policy.
6. **FIXED** — sequential delegation is separated from N-child barrier semantics, including the manual stop/kill gap.
7. **FIXED** — immutable-oracle language in `worker.md` is now mandatory, alongside payload and parent verification.

Evidence of artifact review: “Таблица не переносится на популяцию и не обновляет headline 6–10 %.”

## New findings

suggestion: `docs/tasks/223/research.md:117-118` — F2 still says `model-routing` “требует Luna для закрытого тикета,” contradicting the corrected account at lines 31–35 and 158–168: complex closed work may route directly to Sol. Replace with “defaults/routes ordinary closed work to Luna, with the existing Sol complexity exception.”

question: the requested “current uncommitted diff” is empty: both `git diff` and `git diff --cached` report no changes, and the artifact matches `HEAD`. I therefore re-reviewed the current committed artifact rather than an uncommitted diff.

## Verdict

Approved with one non-blocking wording correction. No blocking findings or new bugs; the seven substantive round-one issues are resolved apart from the stale Luna-routing sentence.
