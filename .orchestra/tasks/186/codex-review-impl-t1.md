## Summary

Целевой набор тестов запущен полностью:

```text
30 passed in 4.20s
```

Формула на корректных UTC-входах работает, включая границы `[03:00, 17:00)`. Интервал `16:59 → 03:01` следующего дня даёт ровно `2/60` часа: одна минута до 17:00 и одна после 03:00.

Историческая фикстура внутренне согласована: значения монотонны внутри сегментов, оба отмеченных сброса действительно нарушают монотонность ровно в указанных точках. Значения `EXPECTED_DEFICIT_AT_H24` выводятся непосредственно из `WEEKS`: при h=24 прошло 14 рабочих часов, осталось 84; расчёт даёт примерно `48.5`, `53.7`, `−17.5`, `−24.2`.

## Findings

blocking: [app/quota_runway.py:70](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_runway.py:70) — UTC-контракт не обеспечен. `next_weekly_reset()` делает `replace(hour=7)` в часовом поясе входа, поэтому для `now` в `Europe/Berlin` возвращает вторник 07:00 Berlin, а не 07:00 UTC. Аналогично `working_hours_between()` на строках 95–98 применяет полосу 03:00–17:00 в локальном timezone входа. В UTC+3 интервал 03:00–04:00 UTC, переданный как 06:00–07:00+03:00, будет ошибочно засчитан как локальная рабочая полоса. Наивные datetime ещё хуже: смешение с aware-входом выбрасывает `TypeError`, а `astimezone()` трактует naive относительно timezone машины. Нужна единая политика: отклонять naive и нормализовать все aware-входы в UTC до календарной арифметики. Добавьте тесты с UTC+03:00 и naive datetime для обеих функций.

blocking: [app/quota_runway.py:139](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_runway.py:139) — `NaN` обходит все защитные ветки и возвращает `state="data"` с `pace`, `runway_hours` и `deficit` равными `NaN`. Сравнение `nan < baseline` ложно, а затем арифметика распространяет нечисло. Такой вердикт невозможно надёжно сравнить с порогом и нельзя сериализовать строгим JSON-кодером. Аналогично не проверяются бесконечности и физический диапазон процентов. Для чистой метрической границы стоит fail loud на не-конечных значениях и процентах вне `0..100`; нужен параметризованный тест для `nan`, `inf`, отрицательного и `>100`.

suggestion: [tests/test_quota_runway.py:292](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/tests/test_quota_runway.py:292) — четвёртая незамечаемая мутация: заменить строку накопления на округление/усечение каждого дневного пересечения, например `total += int((b - a).total_seconds() / 3600)`. Все текущие проверки рабочих часов используют целые границы и продолжат проходить; исторический replay тоже использует целые часы. Нужен тест `working_hours_between(16:59 UTC, next-day 03:01 UTC) == approx(2 / 60)`. Он одновременно закрывает короткие интервалы, обе границы полосы и переход через ночь.

suggestion: [app/quota_runway.py:159](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_runway.py:159) — нулевой темп намеренно выпускает `inf/-inf` из публичного результата, но тест проверяет только арифметику. Стандартный `json.dumps` запишет нестандартное `Infinity`, а строгие JSON-сериализаторы обычно отвергнут его; форматирование также покажет пользователю `inf`. Если `inf` остаётся частью внутреннего контракта, до подключения T4 нужен тест границы сериализации/форматирования и явное преобразование в конечное представление у потребителя.

question: [app/quota_runway.py:28](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_runway.py:28) — выбор 10 часов методологически лучше, чем 6: это нижняя граница области, на которой бэктестировалcя порог 14, а не только число, подобранное под ложную тревогу на h=6. Но доказательство остаётся слабым: спокойные недели всего две, обе другого тарифа, а значение 10 выбрано после просмотра результата. Я бы сохранил 10 и документировал его как границу применимости имеющегося бэктеста, не как подтверждённый оптимальный минимум. Переоценить после первой спокойной недели Max20.

## Verdict

Changes requested. UTC-нормализация и проверка конечности входов нужны до merge: сейчас допустимые по сигнатуре входы способны дать неверный runway или `NaN`. Остальная арифметика и исторический replay выглядят согласованными.

## Round (2026-08-11T10:54:31Z)

## Re-review status

- FIXED — UTC contract: every datetime entry point now rejects naive values and normalizes aware values before arithmetic.
- FIXED — invalid percentages: `_checked_pct` runs before comparisons and prevents NaN/non-finite/out-of-range values from reaching arithmetic.
- FIXED — partial-hour mutation: the new `16:59 → 03:01` test precisely catches overlap truncation.
- FIXED — infinite runway: `inf` remains a deliberate internal contract, with serialization risk explicitly pinned for T4.
- FIXED — 10-hour minimum: correctly documented as the backtest’s applicability boundary, not a validated optimum.

`window_start_at` validation placement is safe: `None` produces `no_data`; every non-`None` value is normalized before reaching `working_hours_between`. Raising `ValueError` is appropriate because malformed provider data violates the pure function’s contract and T4 will isolate and log the exception without killing the shared loop.

## New findings

None.

## Verdict

Approved. All 42 targeted tests pass, and no remaining path into the arithmetic bypasses the new validation.

## Round 2

Verbatim current source line:

>     полоса 03:00–17:00 применилась бы к локальным часам — то есть тихо к другим суткам.
