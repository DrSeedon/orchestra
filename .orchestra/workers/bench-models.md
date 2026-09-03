# bench-models — личная память

## Замер расхода подписочной квоты Codex (#199)
- **Источник истины по расходу — rollout'ы `~/.codex/sessions/**/rollout-*.jsonl`.** В событии
  `event_msg`/`token_count` лежат СРАЗУ и токены (`info.last_token_usage`,
  `total_token_usage` — накопительно по треду, дельту считать самому), и показание пула
  (`rate_limits.primary.used_percent`, `resets_at`, `window_minutes`). Модель хода — из
  `session_meta`/`turn_context`. Это единственное место, где расход и квота приходят из одного
  счётчика; `/api/usage` смешивать с ними в одной дроби нельзя.
- **`rate_limits.limit_id` пулы НЕ различает** — он равен `"codex"` и у основного пула, и у
  Spark. Различай по `resets_at` (у Spark своё) — на это чуть не попался.
- Показание пула целочисленное. Один шаг счётчика ≈150 кредитов ≈ $6 наших долларов по
  ставкам Sol; чтобы что-то измерить, нужен расход в единицы процентов.
- Голый прогон модели для замера: `codex -m <model> -c model_reasoning_effort=<e>
  -c mcp_servers='{}' -s danger-full-access -a never exec --skip-git-repo-check --json
  -o answer.md - < prompt.txt`. `-c mcp_servers='{}'` убирает глобальный MCP из
  `~/.codex/config.toml` (иначе +10K входных токенов на каждый вызов и лишняя переменная).
  Стог для long-context теста подавать в stdin, а не файлом в каталоге, иначе меришь grep.
- Доки OpenAI отдают markdown-твин по суффиксу `.md` (`developers.openai.com/api/docs/...md`,
  `learn.chatgpt.com/docs/....md`), индекс — `learn.chatgpt.com/llms.txt`. Это точнее и дешевле
  `r.jina.ai`; сам `openai.com/*` без прокси даёт 403.

## Где что лежит в этом проекте
- Цены Codex — `app/backend_codex.py` `CODEX_TOKEN_PRICES`, НЕ `TOKEN_PRICES` в `app/models.py`
  (там только Claude; для codex-строк дашборд берёт стоимость, записанную в момент хода).
- `turn_usage` в `data/orchestra.db` хранит `quota_*_pct` на момент хода — но только для ходов,
  прошедших через Orchestra. Мой `codex exec` из `/tmp` туда не попадает.
