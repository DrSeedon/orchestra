# review-337-opus — личная память

## Пробы, которые пригодятся снова

- **oEmbed X переехал:** `publish.twitter.com/oembed` отдаёт `301 → publish.x.com/oembed`.
  Без `-L` проба возвращает `HTTP 301, bytes=0` и читается как «канал мёртв». Всегда `curl -sSL`.
- **Положительный контроль для oEmbed** — `https://twitter.com/jack/status/20` («just setting up
  my twttr», HTTP 200, 630 Б). Несуществующий id даёт 404, неотличимый от поломки эндпоинта:
  сперва прогнать известный твит, потом делать вывод.
- **Exa MCP без ключа:** `POST https://mcp.exa.ai/mcp`, заголовки
  `Accept: application/json, text/event-stream`, `initialize` → взять `mcp-session-id` из
  ответных заголовков → слать его в `Mcp-Session-Id` на `tools/list`/`tools/call`.
  Ответ — SSE, парсить строки с префиксом `data: `. Тулов ровно два: `web_search_exa`
  (`query`, `numResults`) и `web_fetch_exa` (`urls`, `maxCharacters`), `includeDomains` нет.
  Поиск отдаёт поле `Highlights:` (обрывки через `...`), НЕ полный текст; полный текст даёт
  только `web_fetch_exa` и только там, где сайт не отдаёт 403.
- **Встроенный `WebSearch` не берёт reddit.com вовсе** — `API Error: 400 … domains are not
  accessible to our user agent`. Это не «плохо ранжирует», а отказ на уровне API.

## Метод

Ревьюя чужой ресёрч, первым делом открывать не прозу, а **сырьё, которое автор сам закоммитил**
рядом (`*.txt`, `*.jsonl`): расхождение прозы с собственным приложением — самая дешёвая находка.
В #337 два блокера из трёх нашлись так, за две команды `grep` по приложенному файлу.
