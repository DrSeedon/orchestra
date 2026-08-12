# Задача #201: стоимость Codex cache writes и Spark

Проверено 12.08.2026 по первоисточникам OpenAI.

## Опубликованные ставки cache write

Реально открытый URL (текстовый прокси для страницы, которая отвечает 403 обычному curl):
https://r.jina.ai/http://developers.openai.com/api/docs/pricing

Дословный фрагмент секции `Standard` (цены за 1M токенов):

> | Model | Input | Cached input | Cache writes | Output | Input | Cached input | Cache writes | Output |
> | gpt-5.6-sol | $5.00 | $0.50 | $6.25 | $30.00 | $10.00 | $1.00 | $12.50 | $45.00 |
> | gpt-5.6-terra | $2.00 | $0.20 | $2.50 | $12.00 | $4.00 | $0.40 | $5.00 | $18.00 |
> | gpt-5.6-luna | $0.20 | $0.02 | $0.25 | $1.20 | $0.40 | $0.04 | $0.50 | $1.80 |

В коротком контексте cache write стоит `$6.25/M` для Sol, `$2.50/M` для Terra и
`$0.25/M` для Luna. Эти ставки добавлены в `CODEX_TOKEN_PRICES`.

## Spark: опубликованной числовой цены нет

Реально открытый URL официальной карточки тарифов Codex:
https://r.jina.ai/http://help.openai.com/en/articles/20001106-codex-rate-card

Дословно:

> | GPT-5.3-Codex-Spark | research preview | research preview | research preview |

И примечание на той же странице:

> GPT-5.3-Codex-Spark may be available in Codex as a research preview - credit rates for this model are not final.

Число не подставлено по аналогии с `gpt-5.3-codex`: это была бы цена без источника.
Spark добавлен в таблицу явным значением `None`, а `_codex_cost` теперь бросает
`ValueError("No published token price ...")`. Поэтому ход больше не записывается как правдоподобный
`$0`: отсутствие цены видно немедленно и не искажает накопленную статистику.

## Порог длинного контекста

Реально открытый URL карточки модели:
https://developers.openai.com/api/docs/models/gpt-5.6-sol.md

Дословно:

> Prompts with >272K input tokens are priced at 2x input and 1.5x output for the full request.

Единица порога — один prompt/request, не сумма за thread, session или turn. Поэтому применять
наценку к накопленной дельте `turn_input` было бы неверно: один ход Codex может содержать несколько
запросов. Формула не изменена. Кроме того, текущий измеренный предел запроса Codex в Orchestra —
258,400 токенов (`CODEX_CONTEXT_LIMITS`), ниже порога 272K; это локальный замер, не утверждение
из документации OpenAI.

## Реализация и проверки

- `cache_write_input_tokens` протянут через snake_case rollout totals/context, camelCase
  app-server usage, `_usage_delta`, `AggregateUsage.cache_create_tokens` и metadata.
- Формула разбивает вход на непересекающиеся `fresh`, `cached` и `cache_write`: write-токены
  вычитаются из fresh перед начислением своей ставки.
- `uv run pytest -q tests/test_backend_codex.py tests/test_codex_usage.py` — `88 passed`.
- Мутация удаления `- cache_write` из расчёта fresh покрасила целевой тест:
  `0.0034 != 0.0024`; после восстановления маркер формулы найден ровно один раз.
