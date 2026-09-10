# Эксперименты с CLI и MCP

## Grok 1.0.3: doctor видел 37 tools, а сессия загружала ноль

В расследовании Grok 1.0.3 `grok mcp doctor` сообщал «37 tools, healthy», но рабочая сессия
получала ноль серверов. `grok mcp list` тоже не отвечал на нужный вопрос: Orchestra передавала
сервер через ACP session/new, а list показывал конфигурационные источники Grok.

Различающие наблюдения нашли в `grok agent --debug --debug-file <file> stdio`:
`created with N MCP servers`, `folder untrusted: skipping repo-local`,
`ensure_mcp_tools_initialized: config_count=`. Оказалось, project .mcp.json объединялся
по имени до проверки folder trust. Коллизия имени вытесняла переданный сервер, а последующая
проверка trust удаляла замещающий. Пять способов подключения, включая --plugin-dir, дали
один отрицательный результат из-за общей причины, а не пяти независимых дефектов.

Не переносить порядок merge/trust на новую версию без проверки. Ценность опыта — разные
области проверки doctor/list/session и найденный общий confound.
Источник: [разбор Grok 1.0.3](https://github.com/DrSeedon/orchestra/blob/9a1735f1695519a445f393802c2154bd37337e38/.orchestra/workers/fix-grok-mcp.md);
[отчёт #264](https://github.com/DrSeedon/orchestra/blob/9a1735f1695519a445f393802c2154bd37337e38/.orchestra/tasks/264/report.md).

## Codex 0.153.4: наличие context-management tools проверяли контрольным запуском

В записи от 06.09.2026 описаны два изолированных CODEX_HOME: с
`[features.context_management] experimental_mode = true` модель сообщила о new_context и
get_context_remaining; без флага та же Astra перечислила набор без них. Зафиксированы
4382 и 3380 токенов. Это наблюдение о видимости tools в той версии, не замер экономии
недельного лимита и не основание автоматически включать флаг всему парку.

Та же запись содержит пробу vendor bwrap: RC=0 одновременно с
`loopback: Failed RTM_NEWADDR: Operation not permitted`. В этом окружении успешный код
запуска не подтверждал настройку loopback. Запись не содержит полного повторяемого стенда;
это историческое свидетельство, которое стоит проверить при аналогичной диагностике.
Источник: [запись двух проб от 06.09](https://github.com/DrSeedon/orchestra/blob/3208ceeda5a1c76ce9e0ed147b0c3fbce38ac497/AGENTS.md).
