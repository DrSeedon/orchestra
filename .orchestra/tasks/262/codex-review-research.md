## Summary

Расчёты mean/median, Codex usage-bearing boundary, cache semantics, weekly normalization `4.348125`, current Codex/Claude pool estimates и ETA арифметически воспроизводятся. Synthetic 26 rows исключены до знаменателей; Spark не превращён в `$0`; ограничения Antigravity/Jio обозначены честно.

Sighted proof: «API-equivalent rewards expensive list pricing and says nothing about correctness.»

## Findings

suggestion: `docs/tasks/262/research.md:200` — значение первого Claude partial segment не воспроизводится. По frozen DB, текущим ценам и заявленным границам `38→80` получается `$781.32659475 / 42 × 100 = $1,860.30`, а не `$1,828`. Это не меняет основной диапазон, но фраза о независимом подтверждении `$1,836` сейчас численно неверна → исправить число либо явно показать другую границу/формулу.

suggestion: `docs/tasks/262/research.md:239` — physical-ceiling PASS почти тавтологичен: сегменты строятся из значений utilization, а потолок задаётся как `100 × число сегментов`; при каждом значении в `[0,100]` сумма ranges конструктивно не превысит этот потолок. Равенство raw-positive и range действительно проверяет отсутствие повторных подъёмов внутри сегмента, но текущий тест не является независимой проверкой количества физически возможных pool за период → считать потолок из календарной длительности/reset semantics, независимо от найденных падений.

suggestion: `docs/tasks/262/research.md:57` — заявленный воспроизводящий расчёт не полностью воспроизводим и не заморожен: скрипт лежит вне репозитория, импортирует текущие price tables и вручную содержит Claude completed `$1,836.28296511`, Grok pilot costs/percent boundaries и весь Antigravity aggregate. Изменение кода цен поменяет повторный расчёт, а несколько headline-значений вообще не выводятся из snapshot/evidence → сохранить скрипт и входной manifest рядом с исследованием либо перечислить SHA/точные источники каждого hardcoded input.

suggestion: `docs/tasks/262/research.md:209` — формулировка «До 20 известных traces … было 8%» точнее данных. Первый trace имеет UUIDv7 timestamp `07:08:31.859`, а ближайший 8% snapshot — `07:08:32.295`, то есть на 0.436 секунды позже начала trace. Это может быть валидным pre-billing snapshot, поскольку ход ещё не завершён, но доказательством строго pre-batch состояния не является → назвать его «до первого завершения» и сохранить эту неопределённость в Grok bracket.

## Verdict

**NEEDS REVISION.** Blocking-класса crash/corruption/security не найдено. Основные operational conclusions — Codex исчерпается первым и Claude/Codex headline economics — сохраняются, но physical-ceiling proof и воспроизводимость доказательств требуют исправления до принятия research как подтверждённого.

## Round (2026-08-13T09:02:35Z)

## Summary

All four prior findings are resolved. The reproduction command succeeds and matches the research’s denominators, turn statistics, cache invariants, pool estimates, ETA values, and revised physical checks.

Sighted proof: “Воспроизводящий manifest фиксирует считанные оттуда значения и SHA владельцев: это не исполняемый production price table и не может разойтись с dashboard молча.”

## Findings

suggestion: `docs/tasks/262/measure.py` — the script does not reproduce the monthly `4.348125` normalization or API-equivalent per subscription dollar, despite those being a load-bearing requested outcome and the subscription prices already existing in `measurement-inputs.json` → print and verify the subscription-economics table from those frozen inputs.

## Verdict

**APPROVED with one non-blocking reproducibility suggestion.** No blocking findings remain; the research conclusions are supported by the frozen evidence.
