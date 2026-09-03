# #251 — read-only сверка Grok на ноутбуке

Дата: 2026-08-13. Доступ: reverse SSH к `maxim-911aird`; выполнялись только `hostname`,
`stat`, чтение `config.toml`, перечисление **имён** env и `grok --version`. Файлы, процессы и
настройки ноутбука не изменялись; модельные и другие тяжёлые прогоны не запускались.

Санитизированный результат:

```text
login-shell grok: 0.2.112 (9bbd559437)
~/.grok/config.toml: 0664 maxim:maxim
[features] telemetry=false
[telemetry] trace_upload=false
[telemetry] mixpanel_enabled=false
[telemetry] otel_enabled=false
env names matching grok telemetry/feedback, OTEL or Sentry: none
```

Остальной конфиг: internal installer с auto-update; официальный marketplace; UI
`max_thoughts_width=120`, `fork_secondary_model=grok-4.5`, `yolo=false`,
`compact_mode=false`, `permission_mode=always-approve`. Эти параметры не относятся к
телеметрии и на VPS не переносились.

Полезные три выключателя уже присутствовали на VPS независимо и дополнены более полным набором:
product analytics, feedback, indexing, trace upload, Mixpanel, external OTEL и Sentry hard-off.
То есть с ноутбука не потребовалось копировать значение, которого ещё не было на VPS.
