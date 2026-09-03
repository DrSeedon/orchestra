# Research #286 — gate artifact

Канонический полный синтез лежит в `docs/tasks/286/report.md`, потому что именно этот путь заказан
постановкой. Сырые и агрегируемые числа — `docs/tasks/286/data.json`; preregistration и точные
критерии — `docs/tasks/286/prereg.md`.

## Вопрос

Подтверждает ли минимальный свежий paired replay, что Spark можно допустить вместо Luna на
полностью закрытые oracle-backed leaf, и даёт ли он преимущество по correctness, failures, wall,
cold start, tokens или virtual dollars?

## Гипотезы и фальсификаторы

- Spark сохраняет correctness и снижает wall; неверно, если проиграет frozen test или не будет
  быстрее ни в одной паре.
- Luna экономичнее; неверно, если Spark не расходует больше tokens на обеих задачах и официальный
  Spark rate устанавливает меньшую цену.
- Старый #222 уже полон; неверно, потому что там нет per-tool failure outcome и cold-start timing.

## Findings

- **CONFIRMED на двух fixtures:** обе модели 2/2 PASS и дали одинаковые pairwise diffs; Spark
  суммарно быстрее на 28.4% wall. Tier 1 — прямой preregistered measurement.
- **CONFIRMED:** cold start Spark не выиграл устойчиво (mean 8.36 s против 7.11 s), tool failures
  не случились 0/0. Tier 1; второе не обобщается на failure recovery.
- **CONFIRMED:** Luna публична и имеет ставку $0.20/$0.02/$1.20 per MTok; Spark rate остаётся
  research-preview/unknown. Tier 2 — первичные OpenAI pages + current source.
- **CONFIRMED на #222 cell:** missing data → Spark silently invented 2/2, Luna asked 2/2.
- **LIKELY:** Spark лучше только как latency/overflow lane предельно закрытого leaf; малый N не
  поддерживает более широкое правило.

## Counter-evidence и границы

Spark output в новых задачах выше на 50.1%; Luna-priced Spark sensitivity разнонаправлен по
задачам; actual Spark dollars неизвестны. Новый N=2, tool failures отсутствовали. Future Git
objects и parent roots недоступны, но сеть и остальной HOME физически доступны, поэтому глобальная
недостижимость ответа не доказана. Публичный 1.05M Luna API context не переносится на локальный
ChatGPT-auth CLI limit 258.4K.

## Affected files / риск будущей реализации

Задача исследовательская: runtime/config не менялись. Если routing когда-либо пересматривается,
единственный owner — `pipelines/default/prompts/modules/model-routing.md`; новый отчёт поддерживает
текущий узкий Spark gate, а не его ослабление.

Источники и конкретная routing table: `report.md` §§ «Публичное предназначение моделей»,
«Конкретная таблица маршрутизации», «Артефакты и источники».
