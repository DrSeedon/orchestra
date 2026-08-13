# Рабочая память

- У Antigravity CLI 1.1.12 `--output-format` — глобальный флаг: рабочая форма `agy --output-format json models`; форма `agy models --output-format json` падает как неизвестный флаг.
- При неизвестной внешней квоте с жёстким stop-limit проверять остаток после минимального различающего batch: 13 Antigravity probes без промежуточной проверки перескочили порог 5 п.п. и потратили около 16%.
- При ротации OAuth не публиковать token и account-generation двумя `rename`: вычислять generation из hash тех же token bytes и менять один файл через `os.replace`, иначе crash между rename оставляет смешанную identity.
