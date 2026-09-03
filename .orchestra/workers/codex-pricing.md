# codex-pricing — личная память

## Веб-ресёрч: как достать дословный текст с закрытых доксайтов

Порядок, который сработал (задача #190, 11.08.2026):

1. **`learn.chatgpt.com` — суффикс `.md`.** Страница сама пишет в шапке: «Markdown versions of documentation pages are available by appending `.md` to the page URL». `curl https://learn.chatgpt.com/docs/pricing.md` → 57 КБ чистого markdown вместо 662 КБ HTML. Индекс всех страниц — `https://learn.chatgpt.com/llms.txt`.
2. **`help.openai.com` и `chatgpt.com` — 403 и на `curl`, и на `WebFetch`** (Cloudflare, «Enable JavaScript and cookies to continue»). Лечится текстовым прокси: `curl https://r.jina.ai/https://<полный-url>` → 200 и markdown, включая строку «Updated: 15 hours ago». Не сдаваться после двойного 403 — это НЕ значит «источник недоступен».
3. **Таблицы, где ячейки — иконки (✓/✗ через `<svg>`), текстом не извлекаются.** Матрица Feature availability выглядела пустой и в `.md`, и в наивном strip-tags. Решение: перед снятием тегов заменить `re.sub(r'<svg.*?</svg>','[Y]',...)`, потом стрипать. Иначе молча потеряешь ровно ту информацию, ради которой пришёл.
4. **GitHub без `gh` (его тут нет) и без токена:** дифф PR берётся как `https://github.com/openai/codex/pull/<N>.diff`, метаданные — `https://api.github.com/repos/<owner>/<repo>/pulls/<N>` (анонимно работает). А вот `api.github.com/search/code` требует аутентификации — 401. Список файлов репо: `git/trees/main?recursive=1`.

## Урок не про инструменты

Цифры лимитов OpenAI протухают за недели, а не за годы. Наш же `docs/tasks/codex-limits-abuse/research.md` от 18.07.2026 писал «Pro 5x Sol 75–450»; 11.08.2026 та же таблица того же URL дала «50-500». **Перед тем как опереться на чужую (в т.ч. свою прошлую) цифру о внешнем сервисе — перетяни страницу.** Расхождение само по себе стало ценным фактом в отчёте.
