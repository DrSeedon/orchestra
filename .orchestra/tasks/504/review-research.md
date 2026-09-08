> **RETRACTED как описание текущего main (08.09.2026, #530).** Ниже — историческое доказательство ветки #504, а не действующий контракт. Утверждения о живых площадках A, необходимости внедрить T1/T2/T3/T5, ожидании T4 и текущей пригодности прежних оракулов отменены коммитом `264daeb75484bbe9f97e53c654180fca11c8a12a`: main уже отделяет управление от прозы, удаляет T4-классификатор и safeguard-fork, использует `provider_limit`, завершение CLI и временный round hint. Исторические результаты тестов остаются результатами своих снимков, не текущего main. Адресная развязка всех десяти площадок и тестов: [дифференциал #530](../530/diff-main-vs-504.md). Исходные байты: `git show bf496f8828e4ae5859ac09fd1a20a864ac9e895b:.orchestra/tasks/504/review-research.md`.

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

😏 Цифры воспроизводятся, но «механический inventory» проверяет только заранее внесённый список, а не полноту поиска.

## Summary

`check_anchors.py` подтверждает `A=9 B=9 C=83` и наличие всех 101 указанных якорей. Однако он не доказывает, что список полный или что все C-классификации действительно проверены по provenance; поэтому вывод о «каждой relevant branch» переходит от проверки к доверию к автору списка.

## Findings

### suggestion: Уточнить, что anchor-check не доказывает полноту инвентаря

**File:** `.orchestra/tasks/504/check_anchors.py:9-10` | **Confidence:** 0.99

`check_anchors.py` содержит вручную заданный `ROWS` и лишь проверяет, что указанный literal находится на указанной строке; он не сканирует `app/`, не ищет дополнительные syntactic comparison/regex branches и не проверяет уникальность или полноту provenance. Поэтому `anchors_ok=101` доказывает только корректность 101 перечисленного якоря, но не load-bearing выводы «every relevant branch», `9/9/83` и «all C sites». В исследовании это следует называть validated inventory, либо добавить независимый completeness-проход/сверку кандидатов.

### question: На каком основании подтверждена provenance-классификация всех 83 C sites?

**File:** `.orchestra/tasks/504/research.md:47-52` | **Confidence:** 0.94

Для C указано, что все 83 сайта происходят из deterministic output, но `check_anchors.py` проверяет только строковые якоря, а в тексте приведены лишь четыре representative exclusions. Без отдельного артефакта или проверки каждого producer path нельзя отличить «не model prose» от, например, typed row, чьё содержимое всё ещё формируется моделью. Это не опровергает четыре показанных примера, но делает общий вывод о всех 83 недоказанным.

## Verdict

**Overall Correctness:** ✅ Correct | **Confidence:** 0.82

Blast-тесты, текущие cited-кодовые пути и chronology воспроизводятся. Но центральные count/completeness/provenance-выводы требуют более сильного доказательства: текущий скрипт подтверждает перечисленные элементы, а не отсутствие пропущенных.

Инвентарь пока похож на список покупок, где проверили каждую записанную строку — и забыли проверить, не забыли ли купить хлеб.

## Round (2026-09-05T06:18:28Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну вот, со второго захода инвентарь наконец принёс доказательства, а не только уверенность 😏

## Summary

Оба предыдущих замечания исправлены. `check_anchors.py` проходит:

`A=9 B=9 C=83 total=101`
`inventory_anchors_ok=101 document_anchors_ok=17 anchors_failed=0`

`source-to-sink.md` добавляет независимое A/B closure-доказательство и корректно ограничивает C как inspected exclusion denominator.

## Findings

- Prior finding 1 — **FIXED**: исследование теперь прямо называет 101 строку curated inventory и не выдаёт anchor-check за доказательство полноты.
- Prior finding 2 — **FIXED**: provenance C сгруппирован по producer roots, а границы утверждения явно ограничены 83 inspected lookalikes.
- New findings — **нет**.

## Verdict

**APPROVED** — confidence: 0.95.

Цитата из изменённого артефакта: “A C row moving onto a model-text ingress would therefore be caught as an unclosed sink even if its old provenance label remained stale.”

Теперь это уже не список покупок, а список покупок с чеком и сверкой склада.
