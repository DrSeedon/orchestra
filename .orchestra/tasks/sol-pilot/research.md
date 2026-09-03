# Research — реальный контекст GPT-5.6 Sol в Orchestra/Codex

Дата проверки: 2026-07-16.

## Вопрос

- **Контекст:** Orchestra запускает `gpt-5.6-sol` через Codex CLI с авторизацией ChatGPT, а не напрямую через OpenAI API.
- **Проверяемое изменение/утверждение:** в `app/models.py` для Sol записано окно `1_050_000`, а в `app/backend_codex.py` — usable-бюджет `997_500` (95%).
- **Базовая линия:** GPT-5.5 в текущем Codex CLI учитывается как `272_000 × 95% = 258_400` токенов.
- **Критерий ответа:** официальная спецификация модели плюс свежие метаданные и `model_context_window` реальных Codex CLI-сессий.

## Гипотезы и критерии опровержения

### H1 — Codex CLI объявляет для Sol полный effective-бюджет API-окна 1,05M

Причина: официальный API-каталог OpenAI заявляет для `gpt-5.6-sol` окно 1 050 000 токенов [1].

**Опровергнет:** свежий каталог моделей Codex или живая Sol-сессия сообщат окно около 272K/258,4K, а не 1,05M/997,5K.

### H2 — ChatGPT-auth Codex CLI объявляет для Sol те же 272K raw / 258,4K effective, что и для GPT-5.5

Причина: пользовательский продукт может давать меньшее окно, чем прямой API.

**Опровергнет:** хотя бы одна актуальная живая Sol-сессия сообщит клиентский `model_context_window` существенно выше 258 400 либо свежий Codex model cache сообщит raw-окно 1 050 000.

## Метод и заранее заданный pass/fail

1. Открыть официальные страницы OpenAI для API, Codex и подписочного продукта.
2. Проверить `codex --help`, `codex models` и версию CLI.
3. Прочитать свежий `~/.codex/models_cache.json` без изменения файла.
4. Запустить отдельные минимальные сессии Sol и GPT-5.5 и прочитать только поля `model` и `model_context_window` из их rollout JSONL.
5. **H1 проходит**, если Sol сообщает примерно `997_500` effective; **H2 проходит**, если две независимые Sol-сессии объявляют `258_400`, а cache объясняет клиентский budget как `272_000 × 95%`.

Гигантский запрос на 259K+ токенов не отправлялся: pass/fail проверяет клиентский accounting/compaction contract, который Codex фиксирует в событии `task_started`; физический транспортный предел ChatGPT backend остаётся за рамками эксперимента.

## Результаты измерений

### M1 — Codex CLI и команды

```text
$ codex --version
codex-cli 0.144.3

$ codex --help
exit 0; команды `models` в списке нет; размер контекста не показан

$ codex models
exit 1; CLI попытался открыть интерактивный TUI и отказался при TERM=dumb
```

Иными словами, `codex models` не является подкомандой в 0.144.3, а `--help` лимит не раскрывает. Официальная документация Codex вместо этого предлагает интерактивную `/model` или флаг `-m`; размер окна на странице Codex Models тоже не указан [3].

### M2 — свежий каталог моделей Codex

Файл `~/.codex/models_cache.json` был получен самим CLI в `2026-07-16T05:57:36.954243755Z`, `client_version = 0.144.3`.

```json
[
  {"slug":"gpt-5.6-sol","context_window":272000,"effective_context_window_percent":95},
  {"slug":"gpt-5.5","context_window":272000,"effective_context_window_percent":95}
]
```

Расчёт CLI: `272000 × 0.95 = 258400` usable-токенов.

### M3 — живые Codex-сессии

Две независимые Sol-сессии и одна контрольная GPT-5.5-сессия. Rollout metadata текущего аккаунта также сообщает `plan_type = plus`:

```json
{"model":"gpt-5.6-sol","model_context_window":258400}
{"model":"gpt-5.6-sol","model_context_window":258400}
{"model":"gpt-5.5","model_context_window":258400}
```

Отдельные `codex exec --json` вызовы успешно ответили `SOL_OK` и `GPT55_OK`; то есть измерялся живой доступ к выбранным моделям, а не только статический локальный конфиг.

Audit trail:

```text
~/.codex/sessions/2026/07/16/rollout-2026-07-16T12-55-51-019f697e-e48f-77e2-b314-23b1eb203c6c.jsonl  # Sol pilot
~/.codex/sessions/2026/07/16/rollout-2026-07-16T12-58-07-019f6980-f72e-7370-ac87-d62949bb6f8b.jsonl  # Sol probe
~/.codex/sessions/2026/07/16/rollout-2026-07-16T12-58-50-019f6981-9e01-7483-b04d-c4c7b4b41457.jsonl  # GPT-5.5 probe
```

Точные команды извлечения (содержимое промптов и credentials не выводят):

```bash
jq '[.models[] | select(.slug == "gpt-5.6-sol" or .slug == "gpt-5.5") | {slug, context_window, effective_context_window_percent}]' ~/.codex/models_cache.json

for file in \
  ~/.codex/sessions/2026/07/16/rollout-2026-07-16T12-55-51-019f697e-e48f-77e2-b314-23b1eb203c6c.jsonl \
  ~/.codex/sessions/2026/07/16/rollout-2026-07-16T12-58-07-019f6980-f72e-7370-ac87-d62949bb6f8b.jsonl \
  ~/.codex/sessions/2026/07/16/rollout-2026-07-16T12-58-50-019f6981-9e01-7483-b04d-c4c7b4b41457.jsonl
do
  jq -s -c --arg file "$(basename "$file")" \
    '{file: $file, model: ([.[] | select(.type == "turn_context") | .payload.model] | first), model_context_window: ([.[] | select(.payload.type == "task_started") | .payload.model_context_window] | first), plan_type: ([.[] | .. | objects | .plan_type? // empty] | first)}' \
    "$file"
done
```

## Findings

### 1. API-модель GPT-5.6 Sol действительно поддерживает 1,05M

Официальная карточка OpenAI API указывает `1,050,000 context window`, максимум ответа 128K и повышенную цену для запросов свыше 272K [1]. Это не выдуманная цифра и не чистый маркетинг: это спецификация API-поверхности.

**Уверенность: CONFIRMED** — первичный официальный источник (evidence tier 2).

### 2. Подписочный продукт может давать окно меньше API

Официальная справка ChatGPT Business прямо указывает для GPT-5.6 Sol окно 272K [4]. Официальная страница доступности подтверждает, что Codex CLI 0.144.0+ получает GPT-5.6 через отдельную продуктовую поверхность ChatGPT/Codex [5]. Проверенный аккаунт имеет план `plus`, поэтому применение числа Business к нему — только подтверждающая inference; точное число текущего CLI доказывают M2–M3, а не [4]–[5].

**Уверенность: LIKELY** — два первичных источника подтверждают product-specific limits, но не публикуют точный context window Codex CLI для Plus (evidence tier 2).

### 3. Codex CLI этого аккаунта объявляет и использует effective budget 258 400 токенов

Свежий server-fed cache сообщает 272K raw и 95% effective, а две независимые живые Sol-сессии фиксируют `model_context_window = 258400`. Результат совпадает с GPT-5.5 в том же CLI. Это доказанный клиентский budget для accounting/compaction, но не экспериментально подтверждённый транспортный предел ChatGPT backend.

**Уверенность: CONFIRMED** — повторённое прямое измерение плюс свежие метаданные CLI (evidence tier 1) для клиентского budget.

### 4. Записанные в Orchestra 1 050 000 / 997 500 неверны для текущего ChatGPT-auth Codex runtime

Текущее расхождение составляет `1_050_000 / 272_000 ≈ 3.86×` и столько же для usable-значений `997_500 / 258_400`. Измеренный факт: `CodexBackend` занижает live `context_pct` примерно в 3,86 раза.

**Уверенность: CONFIRMED** — локальный код и прямое измерение runtime (evidence tier 1).

Ожидаемое последствие: Orchestra может не достигнуть собственного порога auto-compact `>90%` до клиентской компактации Codex. Это не проверялось E2E у границы окна.

**Уверенность: EXPECTED** — вывод из измеренного denominator и порога `session_turns.py`, без граничного эксперимента.

### 5. Итог сравнения с GPT-5.5

В прямом API официальные карточки сейчас указывают 1,05M и для Sol, и для GPT-5.5 [1][2]. В проверенном Codex CLI обе модели дают одинаковые 272K raw / 258,4K effective budget. Поэтому корректная формулировка такая: **Sol — модель с 1,05M API-контекстом, но текущий Codex CLI Orchestra объявляет и использует 258,4K для context accounting/compaction, не 1M.**

**Уверенность: CONFIRMED** — первичные спецификации и повторённое измерение (evidence tiers 1–2).

## Контрдоказательства и ограничения

- Главный аргумент против вывода — API-карточка Sol с 1,05M [1] и официальные long-context оценки до 1M. Он подтверждает способность модели, но не лимит текущей ChatGPT-auth CLI-поверхности.
- Документация Codex не публикует число окна [3], поэтому продуктовый лимит приходится брать из server-fed cache и живого session event. Это сильнее догадки, но rollout может измениться без обновления документации.
- Не выполнялся запрос больше 258,4K с ожиданием серверной ошибки. Вывод относится к **доступному контекстному бюджету Codex CLI**, который определяет его compaction/accounting, а не к физическому пределу модели через другой транспорт.
- Cache также сообщил 272K для Terra и Luna, но живой E2E-запуск в этой задаче выполнен только для Sol и контрольного GPT-5.5; распространять вывод на всю семью без отдельного запуска не следует.

## Проверка инфраструктуры Sol/Orchestra

- `search_memory("codex integration research")` отработал через Orchestra MCP и вернул релевантные прошлые материалы по `docs/tasks/codex-integration/` и Codex review. **MCP search_memory работает.**
- `AGENTS.md` существует в корне worktree, прочитан полностью (`481` строка); в нём видны архитектура Orchestra, правила full-cycle, прокси, git/worktree и research-only gate. Эти же инструкции были внедрены в системный контекст сессии. **Промпт Orchestra виден.**
- `codex exec` для Sol и GPT-5.5 завершился с exit 0. **Codex CLI и доступ к моделям работают.**
- `codex_review` job `bg-f6772e9682` завершился с exit 0 и вердиктом `PASS with suggestions`, блокеров нет. Однако MCP-обёртка перезаписала созданный review коротким финальным `agent_message`; findings восстановлены из Codex rollout и сохранены в `codex-review-research.md`. Баг зарегистрирован через `report_bug`. **Запуск/background wakeup работают, сохранение review-артефакта работает некорректно.**
- Этот файл создан в worktree; git-проверка и коммит выполняются после adversarial review. **Файловые операции работают.**

## Затронутые файлы и риск будущего исправления

- `app/models.py:37-39` — общий fallback `CONTEXT_LIMITS` для Sol/Terra/Luna сейчас `1_050_000`; словарь используется в каталоге/восстановлении состояния и не имеет единой raw-семантики (для GPT-5.5 там уже `258_400`).
- `app/backend_codex.py:16-24` — live accounting denominator для них сейчас `997_500`; именно он доказанно искажает `context_pct` Sol.
- `tests/test_backend_codex.py:17-23` — тест закрепляет неверное для текущего CLI значение.
- `app/session_turns.py:173-177` — auto-compact зависит от вычисленного процента.

Для Sol `CODEX_CONTEXT_LIMITS` должен соответствовать текущему effective budget `258_400` либо, лучше, поступать из метаданных Codex, чтобы следующий rollout снова не сделал hardcode устаревшим. Контракт и значение общего `app.models.CONTEXT_LIMITS` нужно решать отдельно; механически записывать туда raw `272_000` нельзя. Реализация не входит в research-only Phase 1.

## Источники

1. [OpenAI API — GPT-5.6 Sol model](https://developers.openai.com/api/docs/models/gpt-5.6-sol) — первичный источник, открыт 2026-07-16.
2. [OpenAI API — GPT-5.5 model](https://developers.openai.com/api/docs/models/gpt-5.5) — первичный источник, открыт 2026-07-16.
3. [OpenAI Codex — Models](https://learn.chatgpt.com/docs/models) — первичный источник, открыт 2026-07-16.
4. [OpenAI Help — ChatGPT Business Models & Limits](https://help.openai.com/en/articles/12003714-chatgpt-business-models-limits) — первичный источник, открыт 2026-07-16.
5. [OpenAI Help — GPT-5.6 in ChatGPT](https://help.openai.com/en/articles/20001354) — первичный источник, открыт 2026-07-16.
