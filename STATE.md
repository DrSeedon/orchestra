# STATE.md — Orchestra (Живая память проекта)

**Обновлено:** 2026-11-17 (**Шаг 2 ВЫПОЛНЕН И ВЫКАЧЕН В БОЙ `:8888`:** полный auto-approve `--dangerously-skip-permissions` + параллельные сессии `--process-per-session` + `Semaphore(3)` + живой 2-сессионный smoke `PASS`)

## 1. Боевой контур (`orchestra-vps:/home/kesha/orchestra`, `:8888`)
- **Статус деплоя:** ветка `agy-acp-safe` влита `--ff-only` в `main` и запушена в `origin`, `orchestra.service` — `active`, `telegram-bot-api.service` не тронут, `restart_cut_turns` дельта `0`, все 3 локально изменённых файла в `/home/kesha/orchestra` сохранены побайтово, все 10 боевых оркестраторов Максима нетронуты.
- **Конфигурация провайдера и защита сети:**
  - `data/disabled_providers.json` → `["claude", "grok"]` (`antigravity` разблокирован).
  - Профиль Кати установлен в `data/antigravity-auth-home` (`0700` папки / `0600` файлы, gitignored, `useG1Credits: false`, `useAiCredits: false`, `telemetryEnabled: false`, `auth.type: "oauth-personal"`).
  - В `.env` выставлены `ANTIGRAVITY_AUTH_HOME=/home/kesha/orchestra/data/antigravity-auth-home` и `ORCHESTRA_ENFORCE_PROVIDER_EGRESS=1`.
  - Сеть: резидентский прокси `127.0.0.1:18080` → `178.93.29.64` (`Amsterdam, NL`, `AS215294`) + ядерный killswitch `nftables` `skgid 977 reject` (`0 packets / 0 bytes`).

## 2. Что реализовано в Шаге 2
1. **Полный auto-approve инструментов (`ANTIGRAVITY_AUTO_APPROVE=1` по умолчанию):**
   - В `AcpProfile.start()` (`app/antigravity_acp.py`) в `agy acp` передаётся `--dangerously-skip-permissions` при `ANTIGRAVITY_AUTO_APPROVE != "0"`.
   - В `AcpProfile._permission()` добавлен страховочный авто-выбор `allow_once` / `allow_always` для запросов `kind == "permission"`, при этом пользовательские вопросы `interaction_*` остаются интерактивными.
2. **Одновременная работа нескольких сессий и проектов:**
   - `agy acp` запускается с `--process-per-session` (изолированные `--worker` подпроцессы на каждую сессию со своими `cwd` и `mcpServers` под единым `front`-процессом профиля).
   - Глобальный `Lock()` заменён на `asyncio.Semaphore(3)` (`ANTIGRAVITY_MAX_CONCURRENT_TURNS=3`) + короткий `_setup_lock` на RPC-инициализацию + индивидуальный `session_lock(session_id)`.
   - `canonical_profile("personal")` (`app/backend_antigravity.py`) резолвит пустой `config_dir=""` из боевой таблицы `profiles` в дефолтный `ANTIGRAVITY_AUTH_HOME`.

## 3. Верификация (Офлайн + Живой боевой smoke на `:8888`)
- **Офлайн (airgapped `unshare --net` + `sys.addaudithook`):** 11 ACP-сьютов — **`224 passed, 0 failed`**, `tests/test_default_pipeline.py` — **`62 passed`**, `scripts/check_instruction_contract.py` — **PASS**.
- **Боевой 2-сессионный параллельный smoke на `:8888` (`step2-deploy/live-8888-multisession-smoke.json`):**
  - Пассивные `/api/models` (`22` модели Antigravity) и `/api/usage` породили **`0`** процессов `agy`.
  - Две сессии в разных папках/скоупах и профилях (`acp-smoke-s1`: `antigravity/gemini-3.8-flash-high`, `profile=""` + `acp-smoke-s2`: `antigravity/gemini-3.8-flash-medium`, `profile="personal"`) отработали **одновременно** (`15.64 с` на обе, параллельные `--worker` процессы), обе вызвали `mcp_orchestra_list_agents` и `read_file` с **`0` карточек ручного апрува**, вернули свои маркеры (`ALPHA_PARALLEL_SCOPE_771` / `BETA_PARALLEL_SCOPE_882`), `ok=1, stop_reason="end_turn"`, чисто архивированы (`0` оставшихся smoke-сессий и процессов), `nftables` дельта **`0 packets / 0 bytes`**.
- **Наблюдение по серверному каталогу Google на consumer-профиле Кати (`katyas16k.ks@gmail.com`):**
  - В окне `10:24Z` (Шаг 1) `/v1internal:fetchAvailableModels` отдавал 18 вариантов (включая `gemini-4-argon`, `gemini-4-hydrogen`, `claude-opus-5-5`, `claude-sonnet-5-5`), а с `14:23Z` отдаёт `offered=claude-opus-4-6-thinking,claude-sonnet-4-6,gemini-3.8-flash,gpt-oss-120b-medium` (`6` вариантов; модели `Carbon` на consumer `g1-pro` нет). Бэкенд честно проверяет реально рекламируемый `offered` без тихой подмены (`no nearest fallback`).
