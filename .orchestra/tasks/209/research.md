# #209 — максимальный контекст GPT-5.6 в Orchestra

## RESEARCH DONE

Проверено 23.08.2026 на `codex-cli 0.147.0`, ChatGPT Pro auth и текущем удалённом
каталоге Codex. API model card и подписочный Codex CLI — разные поверхности с разными
практическими потолками.

## Установлено

- Official model card для Sol/Terra/Luna: 1 050 000 total context, 922 000 max input,
  128 000 max output.
- Живой каталог подписочного CLI: `context_window=272000`,
  `max_context_window=872000`, `effective_context_window_percent=95` для всех трёх
  GPT-5.6. Значит текущий максимум CLI — 872 000 raw и 828 400 effective; это в
  3.21 раза больше прежних 258 400 effective.
- Исходник CLI выводит auto-compact из 90% resolved context и зажимает пользовательский
  предел сверху. Для 872 000 корректный максимум auto-compact = 784 800.
- Живой strict-config прогон с заведомо завышенными 1 050 000 / 922 000 завершился
  успешно, но `token_count.model_context_window` вернул 828 400: удалённый каталог
  действительно зажал окно до 872 000 raw, затем применил 95% usable.
- Базовый `~/.codex/config.toml` выставлен на 872 000 / 784 800. #209 переносит эти
  два числовых ключа в приватные managed homes, не копируя `[projects.*]`, MCP-серверы
  или секреты. Код вступит в силу при следующем разрешённом рестарте Orchestra.

## Цена и лимит подписки

| Метрика | Sol | Terra | Luna |
|---|---:|---:|---:|
| API input, $/1M | 4.00 | 2.00 | 0.20 |
| API output, $/1M | 20.00 | 12.00 | 1.20 |
| ChatGPT credits input/cached/output | 100/10/500 | 50/5/300 | 5/0.5/30 |
| Pro 20x local messages / 5h | 200–2 000 | 500–4 000 | 5 000–40 000 |

- Снижение Sol действует и на подписочную шкалу: против GPT-5.5 input credits ниже
  на 20%, output credits — на 33.3%. Promo заявлено минимум до 21.11.2026.
- API-запросы свыше 272K input стоят 2× по input и 1.5× по output за весь запрос.
  Подписочная документация не обещает тот же точный multiplier, поэтому переносить
  его на ChatGPT credits нельзя.
- Само увеличение потолка токены не расходует. Расход растёт, когда история реально
  становится длиннее: каждый следующий ход несёт больше input/cache-read.
- Базовый machine config содержит `service_tier="fast"`; для GPT-5.6 это 1.5× скорость
  ценой 2.5× подписочных credits. Orchestra намеренно не переносит этот ключ в managed
  homes, поэтому множитель относится к standalone Codex, а Orchestra-воркеры остаются
  на Standard. Само наличие большого потолка отдельного множителя не включает.

## Что говорят пользователи

Кураторская страница OpenAI Community содержит положительные отзывы о длинных задачах,
удержании большого контекста и рекомендации пользоваться Sol. Это анекдоты о качестве,
не измерение расхода подписки; численный вывод выше опирается только на официальную
rate card и живой CLI.

## Источники

- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://learn.chatgpt.com/docs/pricing
- https://learn.chatgpt.com/docs/config-file/config-reference
- https://learn.chatgpt.com/docs/agent-configuration/speed
- https://github.com/openai/codex/blob/main/codex-rs/protocol/src/openai_models.rs
- https://developers.openai.com/community

## Проверки

- `codex debug models` — текущий удалённый каталог 272000 / 872000 / 95%.
- Strict-config живой ход — 16 529 input, 11 008 cached, 10 output, effective 828 400.
- `uv run pytest -q tests/test_mcp_config_isolation.py tests/test_backend_codex.py`
  — 114 passed (локально и независимо у Sol reviewer).
- Review route: one targeted Sol pass, модель `gpt-5.6-sol`; APPROVED с цитатой
  изменённой строки и собственным зелёным прогоном. Wrapper отметил job failed только
  из-за отсутствия заголовка `## Verdict`; содержательный вердикт и evidence есть.
