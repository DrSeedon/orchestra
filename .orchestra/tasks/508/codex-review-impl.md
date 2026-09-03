<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Самостоятельно просмотрел diff в пределах указанных файлов. Внешний Codex review недоступен; Sol не запускался без отдельного разрешения.

Проверка: `uv run pytest -q tests/test_tg_ingress_508.py tests/test_tg_bridge.py` → `199 passed`.

## Findings

Нет findings.

ACK: `@dp.message()`

## Verdict

ACK — blocking/suggestion/question отсутствуют.
