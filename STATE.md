# STATE.md — Orchestra (Живая память проекта)

**Обновлено:** 2026-11-17 (**Шаг 2 ВЫКАЧЕН В БОЙ `:8888` + ПРОВЕРЕН КАТАЛОГ `hydrogen-sandbox-orchestrator` БЕЗ `--process-per-session` ПОСЛЕ `UseAICodeMendel=true`**)

## 1. Боевой контур (`orchestra-vps:/home/kesha/orchestra`, `:8888`)
- **Статус деплоя:** `orchestra.service` — `active` (`7cfc494db` + отчёты `main`), `telegram-bot-api.service` не тронут, `restart_cut_turns` дельта `0`, все 3 локально изменённых файла в `/home/kesha/orchestra` сохранены побайтово, боевые оркестраторы Максима нетронуты.
- **Конфигурация провайдера и защита сети:**
  - `data/disabled_providers.json` → `["claude", "grok"]` (`antigravity` разблокирован).
  - Профиль в `data/antigravity-auth-home` (`0700` папки / `0600` файлы, gitignored, `useG1Credits: false`, `useAiCredits: false`, `telemetryEnabled: false`, `auth.type: "oauth-personal"`).
  - В `.env`: `ANTIGRAVITY_AUTH_HOME=/home/kesha/orchestra/data/antigravity-auth-home`, `ORCHESTRA_ENFORCE_PROVIDER_EGRESS=1`.
  - Сеть: резидентский прокси `127.0.0.1:18080` → `178.93.29.64` (`Amsterdam, NL`, `AS215294`) + ядерный killswitch `nftables` `skgid 977 reject` (`0 packets / 0 bytes`).

## 2. Что работает в бою (Шаг 2)
1. **Полный auto-approve инструментов (`ANTIGRAVITY_AUTO_APPROVE=1` по умолчанию):** `--dangerously-skip-permissions` + страховочный выбор `allow_once`/`allow_always` на `permission` в `AcpProfile._permission` (вопросы `interaction_*` остаются интерактивными).
2. **Мульти-сессии и мульти-проекты:** `--process-per-session` + `asyncio.Semaphore(3)` (`ANTIGRAVITY_MAX_CONCURRENT_TURNS=3`) + `_setup_lock` + `session_lock(sid)` + резолв `profile='personal'` (`config_dir=''`) в `ANTIGRAVITY_AUTH_HOME`.
3. **Верификация:** офлайн `224 passed, 0 failed` (11 ACP-сьютов) + `62 passed` (`test_default_pipeline.py`) + живой 2-сессионный параллельный smoke на `:8888` (`PASS`, `15.641s`, `0` карточек ручного апрува, `nft_delta = 0/0`).

## 3. Проверка `hydrogen-sandbox-orchestrator` и серверного каталога Google (`15:52Z`)
- **Сессия:** `hydrogen-sandbox-orchestrator` (`id: 626ea34f-d213-4ebc-81e1-b209468d31cd`, `model: antigravity/gemini-4-hydrogen-high`, `/home/kesha/projects/hydrogen-sandbox`, TG-топик `#300743`).
- **Чистый контрольный эксперимент без `--process-per-session` и без `--cloud_code_endpoint` (`step2-deploy/mendel-no-pps-probe/acp-server-20261117_165224-2335316.log`):**
  - Запущен одиночный `agy acp --disable-telemetry` (`worker=false`), выполнен `authenticate`, выждано **`2.5 с` после `16:52:25.639 UseAICodeMendel routing switch changed: false -> true`** (`CCPA routed this account to AICode; serving AICode FetchConfig flags`), после чего отправлен `session/new` (`16:52:28.143`, `cwd=/home/kesha/projects/hydrogen-sandbox`).
  - Итог в `16:52:28.160`: **`Advertising available models to client: current=gemini-3.8-flash-high, count=6`** (`gemini-3.8-flash-{high,medium,low}`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`).
  - Разбор дизассемблера `agy 1.5.9` подтвердил: флаг `UseAICodeMendel` читается только в `ListExperiments` и `ccpaRoutesToAICode` (не в `fetchAvailableModels`), а `GetModelInfos()` применяет `ModelExperiments` динамически на каждый `session/new`. То есть сейчас сам сервер Google `/v1internal:fetchAvailableModels` отдаёт на consumer-аккаунте ровно эти `6` вариантов (без `gemini-4-*` и `claude-*-5-5`), а наш `--process-per-session` в бою не виноват и сохранён.
