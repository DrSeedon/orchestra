# Модели, квоты и телеметрия расхода

Канонический паспорт роутинга и транспортных ограничений: [model-routing.md](../pipelines/default/prompts/modules/model-routing.md).  
Архив ранних замеров (V-541, V-542, V-548–V-550, V-568, V-599, V-605, V-608, V-616–V-624, V-649, V-656–V-671, V-723–V-813): [models-and-quotas-history.md](models-and-quotas-history.md).

## Established (действует на 21.11.2026)

### 1. Три независимых пула Antigravity (Google) и 26 моделей
- В Orchestra и Кеше открыты все 3 пула квоты **Google Antigravity** (Волна 19, `d79440678`, 26 моделей каталога в `app/models.py`):
  - **Gemini** (`gemini-weekly` / `gemini-5h`): `gemini-4-neon`, `gemini-4-carbon`, `gemini-4-hydrogen`, `gemini-3.8-flash` (включая `agy-neon` / `agy-neon-orch`, контекст 1,000,000 токенов; для `Neon` API-эквивалент $3/$0.15/$15 за 1М).
  - **Argon** (`gemini-argon-wtu-weekly`): `gemini-4-argon` и `gemini-pro-orchestrator-argon` / `gemini-pro-orchestrator-g1-pro`.
  - **Claude / 3P** (`3p-weekly` / `3p-5h`): `claude-sonnet-5-5`, `claude-opus-5-5`, `gpt-oss-120b`.
- **Изолированный опрос квоты (`probe_antigravity_quota()`, Волна 21, `83a920f30`):** в `app/backend_antigravity.py` при запущенном `owner.process` или `BlockingIOError` на `.orchestra-acp.lock` (живой `acp_mux` Кеши) проба больше не возвращает `None`, а снимает изолированный `0700` временный `.gemini`-снапшот в `orch-agy-quota-*` (с симлинком `TOKEN_RELATIVE_PATH`) и резолвит бинарь `agy` через `shutil.which`.

### 2. Поколение Codex 6.2, обязательная `gpt-6-luna` для сторожей/кронов и `effort`
- Для сложного кодинга и научного фактчекинга действуют `gpt-6.2-sol` и `gpt-6.2-astra` (`hubsol` / `hubastra` — основной маршрут для кодинг-воркеров без локальных секретов VPS; локальный `gpt-6.2-sol` бережём только для редких задач с доступом к локальному контуру VPS).
- **Закон от 25.11.2026 (`gpt-6-luna` для сторожей и рутины):** один `seedon-cron` на `gpt-6.2-sol` сжёг `$46.09` (`52%` всего локального Codex за 3.8 дня). Все сторожа, крон-дежурные (`*-cron`, `*-watch*`), периодические сводки, алерты, триаж и мелкие рутинные задачи (всё вне детерминированных капсул `SkillCache`) переводятся **СТРОГО на `gpt-6-luna` (`luna` / `hubluna` / `hub-gpt-6-luna`, `effort=medium`)** — в `≥12×` легче `Sol` (`V-813`).
- Канонические ступени `effort` (`.orchestra/pipelines/default/pipeline.yaml`):
  - `claude-opus-5-5` / `hub-claude-opus-5-5`: `xhigh` (без `max`/`ultracode`).
  - `gpt-6.2-astra` / `hub-gpt-6.2-astra`: `high`.
  - `hub-gemini-4-carbon`: **`high`** (`medium` запрещён по правилу CEO); `hub-gemini-4-hydrogen`: **`high`**.
  - `gpt-6.2-sol`: `high` у оркестраторов/ревьюеров (`hub-gpt-6.2-sol: high`), `medium` у кодеров.
  - В боте Кеши по умолчанию для Antigravity: `gemini-4-neon-medium`.

### 3. Порог авто-компакта Antigravity (`85%`) и формулы подписочного расхода
- **Авто-компакт Antigravity (Волна 24, `22.11.2026`):** единый потолок **`85%` окна** (`850_000` при `1M`, `ANTIGRAVITY_AUTO_COMPACT_PCT = 85` / `ANTIGRAVITY_HARD_COMPACT_PCT = 85.0`) независимо от времени простоя. Константа `ANTIGRAVITY_CACHE_TTL_SEC = 3300` (`55 мин`, Волна 26) используется только для внутренней калькуляции `warm`/`cold` стоимости в `_record_usage` и `estimate_antigravity_turn_usage`.
- **Формула подписочного расхода Claude Max (`V-541`, `V-605`, `V-660`, `V-664`):**
  - Пул расходует **запись кэша** (~`0.604` п.п. недельного пула / 1М токенов, 1h-запись ~`1.2×` от 5m) и **генерацию выхода** (~`4.5–5.3×`), тогда как **чтение кэша ≈ 0** (`0.00687` п.п./М, 95% CI включает ноль).
  - Правило подогрева: выгодно только когда `n × H < (β_write − β_read) × K / 1e6`; произвольные интервалы «каждые N часов» без возврата полезного хода квоту не экономят (`V-541`).
  - Расход, `reset` и ценность пула нельзя делить как единый «общий котёл» по API-долларам (`V-542`). Сравнение Sonnet 5.5 против Opus 5.5 и уровней `effort` (`V-656`, `V-661`, `V-670`, `V-671`): на типовых задачах повышение `effort` выше `low`/`medium` растит выходной объём и цену кратно, а избыточное предписание шагов вместо критерия приёмки искажает стоимость дорогих моделей в `7.5–8.8×` (`V-550` — подробнее в [models-and-quotas-history.md](models-and-quotas-history.md)).

### 4. Телеметрия `/relay/usage` на Хабе и T3 Code `#471`
- **Проверка расхода на Хабе:** эндпоинт `/relay/usage` игнорирует `?days=N` (модуль `usage_query`, строка 77 в контуре релея): всегда передавать явные границы `since` и `until` в UTC.
- **T3 Code `#471` (`v1.3.64`):** клиент пропускает `thought_level`, отправляя Carbon/Hydrogen на `HIGH` независимо от локальной настройки клиента.

## Rejected (отменено)
- **`Gemini 4 Argon` (убран Google 25.11.2026):** `antigravity/gemini-4-argon-*`, `hub-gemini-4-argon` и `gemini-pro-orchestrator-argon` не назначаются новым воркерам; замена — `Neon` / `Hydrogen` / `Carbon`.
- **Использование `gpt-6.2-sol` / `gpt-6.2-astra` для сторожей, кронов и мелкой рутины (25.11.2026):** запрещено; за 3.8 дня `seedon-cron` на `Sol` сжёг 52% локального Codex (`$46.09`).
- **Холодный порог авто-компакта `18%` / `180_000` (`180K`, Волна 20 `416e93e55` → отменено в Волне 24 `22.11.2026`):** вызывал 45-секундную паузу при первом сообщении после простоя на ~`22%` контекста при неустановленном серверном TTL Google и потерей мелких деталей диалога.
- **Скрытый авто-фейловер рантайма в Кеше:** метод `failover_to_codex` и `_try_agy_failover` полностью удалены (`Волна 22`, `1efb3fe`). Кеша строго держит выбранный пользователем рантайм; файл локального кулдауна перенесён из `/tmp` в приватный каталог Кеши с правами `0600`, разделён по 3 пулам (`gemini` / `argon` / `3p`) с потолком TTL `900s` (`15 мин`) и сбрасывается при ручном переключении на Antigravity.
- **Устаревшие модели и настройки:** `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-astra`, `gpt-6.1-terra`, `gpt-5.6`, `OpenCode free` и `hub-gemini-4-carbon: medium` на роли CEO.

## Historical observations
- Все первичные осенние замеры, калибровки тарифов Codex, `Fable 5.1`, `GPT-6 Luna`, `Haiku 5.5`, `total_cost_usd` и детали экспериментов V-541…V-813 перенесены без потерь в [models-and-quotas-history.md](models-and-quotas-history.md).
