# src325-codex-1m — личная память

## Где брать сырьё по докам OpenAI/Codex (проверено 18.08.2026, #325)
- `developers.openai.com/<путь>.md` отдаёт НАСТОЯЩИЙ markdown: `codex/config-reference.md`, `codex/models.md`,
  `codex/pricing.md`, `api/docs/models/gpt-5.6-sol.md`. То же и у `learn.chatgpt.com/docs/*.md` (`codex/pricing.md`
  и `learn.chatgpt.com/docs/pricing.md` — побайтно один файл). Индексы: `developers.openai.com/llms.txt`,
  `learn.chatgpt.com/llms.txt`.
- Исключение: `codex/changelog.md` → 404, а сама страница — JS-оболочка (1.5 МБ HTML, ноль текста записей).
  Единственный рабочий путь — `https://r.jina.ai/https://developers.openai.com/codex/changelog`. Даты записей
  лежат отдельной строкой вида `*   2026-03-05` ПЕРЕД заголовком `### …`, а не в заголовке.
- `help.openai.com` даёт 403 и `curl`, и `WebFetch` → тоже через `r.jina.ai`.
- `api.github.com/repos/openai/codex/releases` без параметров вернёт 30 последних тегов, из них почти все alpha
  с телом в 25 байт. Нужен `per_page=100` + страницы 1–6 (~630 релизов), иначе вывод «в релизах ничего нет» ложный.

## Ground truth по контекстному окну нашего Codex
`~/.codex/models_cache.json` — каталог, который бэкенд отдал НАШЕМУ ChatGPT-аккаунту (поля `fetched_at`,
`client_version`, `models[].context_window / max_context_window / effective_context_window_percent`).
Это точнее любой доки: доки описывают API, а этот файл — то, что реально получает наш CLI.
Смотреть его ПЕРЕД тем, как искать цифру в интернете.
