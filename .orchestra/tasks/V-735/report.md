# V-735: график линии Claude со сдвигом

Payload `/api/usage/quota-map` теперь передаёт `rule.claude_weekly_shift_hours` из `QuotaPolicy`. `_qlLimitAt` использует это значение только для lane `claude`, пересчитывая норму и допуск в точке `t + shift_hours / 168`; далее применяется штатный потолок. Для старого payload, где ключа нет, `Number(undefined)` не проходит `Number.isFinite`, поэтому сдвиг становится нулевым и график продолжает рисоваться по прежней формуле. Значения `lanes[].limit_pct` уже приходят от гейта, который использует ту же политику.

Тест API проверяет поле политики и актуальный серверный порог. Браузерный тест сверяет `QuotaPanel.limitAt` с `lanes[].limit_pct`, проверяет legacy fallback и неизменность кривой Sol. Мутация, сбрасывающая JS-сдвиг, дала `1 failed` на сверке Claude (`55.5` вместо `59.8333`).

Проверка: `uv run --frozen python -m pytest tests/test_quota_map_api.py tests/test_t344_quota_lines_browser.py -q` → `42 passed`; `git diff --check` прошёл.

Python-часть требует рестарта; JS обновляется без него.
