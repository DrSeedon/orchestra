# Промпты, правила и предохранители: как текст становится действием

Путь правила до агента и обратно: чем собирается промпт, где текст модели начинает управлять системой и какие предохранители стоят на этом пути.

## Established

### Сборка и доставка промпта

Что агент РЕАЛЬНО видит в промпте: сборка ролей из слоёв и модулей, доставка правок, зеркала.

- Собранный промпт роли = `base.md` + `roles/<role>.md` + модули из `pipeline.yaml`; проверяется
  одним вызовом `build_system_prompt(DEFAULT_PIPELINE, role)` (`app/pipeline.py`) · замер 19.08:
  orchestrator 49 782 Б, sub-orchestrator 49 080, worker 24 901, full-cycle 53 352, reducer 9 434 ·
  2026-08-19, #prompt-cleanup
- Запускать сборку в воркте только интерпретатором главного чекаута
  (`/home/kesha/orchestra/.venv/bin/python` + `sys.path.insert(0,'.')`): `uv run` создаёт в воркте
  ПУСТОЙ `.venv` и падает `ModuleNotFoundError: yaml` · 2026-08-19, #prompt-cleanup
- Дубль текста доказывается счётчиком вхождений в СОБРАННОМ промпте, а не наличием двух файлов ·
  `p.count('## Background jobs') == 2` у orchestrator и sub-orchestrator до правки (`base.md` +
  `modules/background-jobs.md`) · 2026-08-19, #prompt-cleanup
- Списки `modules:` у ролей прибиты дословно в `tests/test_default_pipeline.py:191-206`: любое
  добавление или удаление модуля роняет тест и требует правки теста в том же коммите ·
  2026-08-19, #prompt-cleanup
- Содержание политики ревью прибито якорями `tests/test_default_pipeline.py:512-530` (в том числе
  `**Sol review is mandatory regardless of size**` и `**targeted Opus cross-family review**`):
  снять обязательность ревью нельзя, не правя этот тест · 2026-08-19, #prompt-cleanup
- Слово `Pre-mortem` запрещено в промптах оркестраторов негативным тестом
  `TestPremortemReachesWorkingRolesOnly.test_orchestrator_roles_do_not_receive_the_step`; пишешь
  правило про самопроверку в `orchestration.md` — не используй это слово · 2026-08-19, #prompt-cleanup
- `CLAUDE.md` читается агентом каждый ход целиком: 144 306 Б на 19.08 до чистки; потолок зеркала
  `AGENTS.md` для Codex — `project_doc_max_bytes` в `~/.codex/config.toml`, на этой машине
  262 144 Б · 2026-08-19, #prompt-cleanup
- **Выносишь блок правил из общего файла в opt-in список подключения (`modules:`, includes,
  imports) → собери финальный артефакт для КАЖДОГО потребителя до и после кодом самого продукта
  и сравни; потребитель с пустым списком теряет блок молча.** Замер 06.09 (#490): три модуля
  вынесены из `base.md` в `.orchestra/pipelines/default/prompts/modules/`, у роли `reducer` в
  `pipeline.yaml` стояло `modules: []` — без явного добавления она одна лишилась бы всего
  вынесенного слоя, при том что четыре остальные роли выглядели бы правильно. Оракул: собрать
  промпт каждой роли тем же `app.pipeline.build_system_prompt` (`app/pipeline.py:583`) до и после,
  затем требовать, чтобы каждая смысловая единица «до» была либо дословно в «после», либо в
  таблице переформулированных с литеральными якорями. Негативный контроль обязателен: удаление
  двух правил из модулей обязано дать FAIL с именами якорей. Полные текстовые дампы промптов в
  задачу НЕ кладут — они пересобираются той же командой и стоят ~6000 строк диффа, из-за чего
  мерж отбивается по потолку; хранят скрипт-оракул, `base_ref`, команду сборки и sha256 срезов ·
  2026-09-06, #490
- **Правки промптов и `pipeline.yaml` рестарта НЕ требуют:** `build_prompt_modules` читает модули
  без кеша, манифест кешируется по `(mtime_ns, st_size)`, живые агенты подхватывают на следующем
  ходе. Это отличает слой промптов от Python-кода в `app/**` · 2026-09-06, #490
- **Большинство правил корневого файла проекта в корневом файле не место: из 276 классифицированных правил там законно остаются 38.** Аудит #501 прочитал `CLAUDE.md` целиком (449 строк) вместе со всем деревом промптов и развёл правила по владельцу: ALL-AGENTS 172, ORCHESTRATOR 61, STAY 38, GLOBAL 3, DELETE 2. Критерий у каждой строки один и тот же и назван в самой таблице — назвать живой проект, где триггер правила сработать НЕ может; не назвал ни одного → правило не принадлежит этому репозиторию. Часть строк помечена `DUPLICATE`: идея уже живёт в дереве промптов, и локальная копия — источник расхождения, а не второй экземпляр правила. **Якоря аудита — номера строк редакции `b125584a`, и после переписывания корня в #523 они по номерам НЕ резолвятся: искать по первым словам правила, а не по `CLAUDE.md:<номер>`** · ищи: `276 правил`, `ALL-AGENTS`, `STAY`, `аудит корневого файла`, «что вынести из CLAUDE.md» · `.orchestra/tasks/501/audit.md` (таблица построчно и десять самых дорогих строк с ценой ошибки) · 2026-09-05, #501

### Текст модели как управляющий сигнал

- **Класс-A мест, где свободный текст модели напрямую меняет поведение Orchestra, — 10, а не 9.** Первый счёт дал `A=9 B=9 C=83 total=101` и был ОТОЗВАН 2026-09-05 (#504, фаза 2): обход остановился на типизированном JSONL `agent_message` и пропустил его внутренний matcher `agent_message.text` в `app/mcp_stdio.py:3590`. Исправленный счёт — `A=10 B=9 C=83 total=102`, `inventory_anchors_ok=102 document_anchors_ok=17`; каждый перечисленный производитель текста лёг на 19 строк A/B. Самое вероятное место срабатывания в обычной работе осталось прежним: `app/session.py:250`, где обычная фраза `session limit`/`usage limit` в прозе возвращает `timed`. Read-only снимок боевой базы нашёл 29 строк `text` со словарём лимитов, из них 16 длиннее 200 знаков · ищи: `model text control flow`, `session limit`, `usage limit`, `app/session.py:250`, `agent_message text`, `app/mcp_stdio.py:3590`, «текст модели управляет поведением» · `.orchestra/tasks/504/source-to-sink.md` (исходное закрытие фазы 1 и исправленное закрытие); `.orchestra/tasks/504/check_anchors.py` на коммите `449c9516` · 2026-09-05, #504 · открыть: `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/source-to-sink.md`; `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/check_anchors.py`
- **Приём попал в Orchestra 2026-07-01 коммитом `1aa9c06a`** (`WIP: auto-saved uncommitted changes before worker spawn (2026-07-01 11:28)`) — как `_GARBAGE_PATTERNS` в сжатии контекста. Его убрали `6f4b244c` 2026-07-11, вернули `bb42ed21` 2026-07-24, и к 2026-08-22 он оброс новыми семействами класса A · ищи: `1aa9c06a`, `_GARBAGE_PATTERNS`, `when model text matching started`, «когда начали грепать текст модели» · `git log -S'_GARBAGE_PATTERNS' --reverse -- app/session.py`; диффы коммитов и хронология в `.orchestra/tasks/504/research.md` · 2026-09-05, #504 · открыть: `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/research.md`
- **Замена для ВСЕХ мест класса A одна: типизированный сигнал, которым владеет производитель, а не текст.** Для провайдера это `LimitEvent/model_error`, для сжатия — `turn_end`, для инструмента — `tool_use/tool_result`, для вставленной истории — provenance, для ревью — структурная квитанция с вердиктом и находками. Текст ассистента остаётся полезной нагрузкой и только ею · ищи: `typed signal`, `LimitEvent`, `model_error`, `turn_end`, `review receipt`, «чем заменить поиск по тексту модели» · текущие типизированные швы и замены по каждому месту в `.orchestra/tasks/504/research.md` §§Per-site table, Verdict; прямые пробы ложных срабатываний в источнике [4] · 2026-09-05, #504 · открыть: `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/research.md`
- **Боевой `claude-agent-sdk==0.2.114` УЖЕ отдаёт типизированный `RateLimitEvent/RateLimitInfo(status,resets_at,rate_limit_type,...)`, а Orchestra расплющивает его в текст `RATE_LIMIT_RAW`.** 613 живых строк доказывают, что путь работает. При этом все 613 первичных статусов были `allowed` при `overageStatus=rejected` — значит терминальное поведение можно взводить ТОЛЬКО по первичному `status=rejected` · ищи: `RateLimitEvent`, `RATE_LIMIT_RAW`, `overageStatus rejected`, `status rejected`, «типизированный лимит Claude» · установленный `claude_agent_sdk/types.py:1236-1278`; `app/backend_claude.py:1390-1396`; read-only онлайн-бэкап SQLite сгруппировал 613 строк `RATE_LIMIT_RAW` как `('allowed','five_hour','rejected','org_level_disabled')`; `.orchestra/tasks/504/phase2-field-evidence.md` · 2026-09-05, #504 фаза 2 · открыть: `git show 8c14f4cadb54b3c0f73dff93f6b9125eff324674:.orchestra/tasks/504/phase2-field-evidence.md`
- **Замена текстового контракта на типизированный обнажает УСТАРЕВШИЕ СТИМУЛЫ тестов, а не ошибки в проверках.** В #504 таких оказалось три: недостижимое сравнение объекта-корутины по имени, тест сжатия, всё ещё подсовывающий баннер провайдера как `text`, и фикстура успешного ревью с нулём `command_execution`. Каждый сохранил свою правильную проверку поведения после исправления стимула и представления · ищи: `stale stimulus`, `typed contract`, `coroutine objects`, `command_execution`, «устаревший стимул теста» · `.orchestra/tasks/504/converted-tests.md` §Phase 3; базовое/WIP доказательство `refreeze-T1-*.txt`; мутация и восстановление `t5-*-*.txt`, `quote-*-*.txt` · 2026-09-05, #504 фаза 3 · открыть: `git show 2e531541c9130677857e2807e606a64d6ff09a71:.orchestra/tasks/504/converted-tests.md`

### Предохранители агента

- **Anthropic в commerce-agents оставляет в промпте только те правила, чья ошибка ограничена неверным ТЕКСТОМ.** Всё, где ошибка стоит действия — provenance, лимиты, апрув, набор доступных тулов, идентичность и отгораживание третьей стороны, — принуждается кодом executor/backend · ищи: `commerce-agents`, `docs/safety.md`, `provenance`, `host approval`, «guardrails агента» · `docs/tasks/507/research.md` §§Guardrails, граница необратимых действий; upstream `docs/safety.md:12-59` на `fd4d59224ab96b43c6dc6888207c67b3bd5a24cf` · 2026-09-03, #507 · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`
- **У нас четыре важных шва остаются во власти промпта, а не кода:** апрув человека не имеет серверной квитанции; правило «сначала источник» не заставляет реально прочитать файл; делегат на ресёрч/ревью не получает read-only набор тулов, принуждённый кодом; пригодность факта для базы знаний решает сам пишущий агент · ищи: `approval receipt`, `grounding`, `read-only delegate`, `semantic eligibility`, «что у нас живёт в промпте» · `docs/tasks/507/research.md` §Где Anthropic принуждает кодом; `pipelines/default/prompts/modules/orchestration.md:6-38`; `pipelines/default/prompts/modules/memory-search.md:4-39`; `app/tm.py:32,319-390`; `scripts/check_kb_contract.py:13-30` · 2026-09-03, #507 · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`
- **Проверка результата у нас СТРОЖЕ, чем в открытом blueprint Anthropic:** платформа до мержа сама запускает замороженный оракул приёмки и сопоставленное подмножество pytest, тогда как открытый commerce-agents поставляет unit-тесты, но не поставляет harness и датасет поведенческой оценки · ищи: `evaluate_pinned_oracle`, `evaluate_test_gate`, `repo ships no eval harness`, «кто судит успех агента» · `docs/tasks/507/research.md` §Проверка результата; `app/acceptance.py:349-378`; `app/merge_operations.py:1661-1740`; upstream `plugins/commerce-builder/skills/commerce-evals/SKILL.md:8-11` · 2026-09-03, #507 · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`
- **Публичный blueprint расходится со статьёй как минимум в четырёх проверяемых местах:** ключ памяти продавца — `merchant_id`, а не человек или оператор; рантайм имеет tier-one и lookup, но не предзагрузку сигналов; демо-экстрактор — `asyncio.create_task` в том же цикле, а не отдельный поток или процесс; grounding, извлечение и анализ на уровне хода неодинаковы на трёх путях рантайма · ищи: `memory_subject`, `tier_one`, `spawn_background`, `Managed Agents`, «статья но нет в коде» · `docs/tasks/507/research.md` §Заявлено в статье; upstream `merchant_agent/executor.py:133-135`, `commerce_common/memory.py:229-245,601-637`, `examples/demo_common/host.py:77-85,185-203`, `docs/safety.md:27,31,33` на `fd4d59224ab96b43c6dc6888207c67b3bd5a24cf` · 2026-09-03, #507 · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`
- **Импортированную историю рантайма мы помечаем `transcript_untrusted` и тела tool payload не переносим, но ОБЩЕГО санитайзера/забора/потолка для живых результатов тулов перед решением модели у нас нет.** Репозиторный обход `rg -n -i 'sanitize.*tool|fenc(e|ing).*tool|third.party' app pipelines/default/prompts tests` общего исполнителя не нашёл · ищи: `transcript_untrusted`, `tool payload bodies`, `Fence.fence_payload`, `live tool results`, «prompt injection из tool data» · `docs/tasks/507/research.md` G1 и Model errors; `app/runtime_history.py:27-31,320-345,460-495`; upstream `commerce_common/fencing.py:99-149` · 2026-09-03, #507 · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`
- **Archestra принуждает запрет по СОДЕРЖИМОМУ аргументов тула детерминированно и вне промпта.** Условие политики достаёт значение из аргументов по пути (`get(input, key)`) и сравнивает операторами `endsWith|startsWith|contains|notContains|equal|notEqual|regex`; решение принимается на четырёх швах — LLM-прокси (потоковый и непотоковый), MCP-gateway перед исполнением и встроенный диспетчер `run_tool`. Наш контраст — `#228`, где `can_use_tool` на аргументах не вызывался ни разу · ищи: `evaluateInputCondition`, `evaluateSingleMcpToolInvocationPolicy`, `block_when_context_is_untrusted`, `run_tool does not bypass input conditions`, «запрет по содержимому аргументов», «где принуждается guardrail» · upstream `archestra-ai/archestra` @ `c0f30875`: `platform/backend/src/models/tool-invocation-policy.ts:375-414,536-663`, `platform/backend/src/routes/proxy/llm-proxy-handler.ts:1733,2198`, `platform/backend/src/routes/mcp-gateway/utils.ts:799`, `platform/backend/src/archestra-mcp-server/run-tool.ts:457`, `docs/pages/platform-mcp-gateway.md:163` · 2026-09-03, #470
- **«Tainted conversation» у Archestra — НЕ статический список тулов-эксфильтраторов.** Слова `taint` в коде нет вовсе; состояние называется `contextIsTrusted`/`unsafeContextBoundary`, а роль списка играют строки политик в Postgres на каждый тул с хардкод-дефолтом fail-closed (`block_when_context_is_untrusted` на вызов, `mark_as_untrusted` на результат, отсутствие политики в грязном контексте = блок). Важное: КЛАССИФИКАЦИЯ «какой тул опасен» делается LLM-субагентом при обнаружении тула, детерминированно только принуждение после неё · ищи: `contextIsTrusted`, `unsafeContextBoundary`, `createDefaultPolicies`, `PolicyConfigurationService`, `autoConfigureOnToolDiscovery`, «список тулов эксфильтраторов» · upstream `archestra-ai/archestra` @ `c0f30875`: `platform/backend/src/guardrails/trusted-data.ts:95,292-307,467-476`, `platform/backend/src/models/tool.ts:537-561,570-582,4164`, `platform/backend/src/agents/subagents/policy-configuration.ts:48`, `platform/backend/src/database/seed.ts:1221`, `platform/backend/src/models/tool-invocation-policy.ts:654-659` · 2026-09-03, #470
- **Признак «разговор грязный» у Archestra не липкий: он пересчитывается заново из массива сообщений КАЖДОГО запроса.** Отсюда прямое следствие: внешний клиент, приславший историю без грязного tool-result, получает чистый контекст. Наследование при делегировании передаётся обычным HTTP-заголовком, а не подписанным утверждением, и компенсируется вторым независимым расчётом доверия прямо перед исполнением тула в чате · ищи: `evaluateIfContextIsTrusted`, `getMessages`, `UNTRUSTED_CONTEXT_HEADER`, `evaluateToolExecutionContextTrust`, «липкое состояние taint», «обходится ли taint» · upstream `archestra-ai/archestra` @ `c0f30875`: `platform/backend/src/routes/proxy/llm-proxy-handler.ts:333-338,966-969,1013`, `platform/backend/src/agents/context-trust.ts:13-52`, `platform/backend/src/guardrails/tool-invocation.ts:352-398` · 2026-09-03, #470

## Rejected

### Сборка и доставка промпта

- «`CLAUDE.md` обрезается зеркалом, поэтому надо срочно резать» — на 19.08 неверно: потолок
  262 144 Б против файла 144 306 Б, обрыва нет. Резать надо ради читаемости и стоимости хода,
  а не ради обрыва · 2026-08-19, #prompt-cleanup
- «Каталог памяти рантайма (`~/.claude/projects/.../memory/`) — рабочее место для знаний» —
  на этой машине каталога не существует (`ls` → No such file or directory), и прочитать его
  агент не может · 2026-08-19, #prompt-cleanup

### Текст модели как управляющий сигнал

- **«Этот класс дефектов живёт только в сжатии контекста» — отвергнуто.** Обход исходников нашёл вне компакта живую обработку лимитов, валидацию ревью, чистку истории харнеса и продублированную классификацию исхода вызова тула · ищи: `compact only`, `outside compaction`, `blind review`, `round guard`, «дефект только в компакте» · опровергнуто: `.orchestra/tasks/504/check_anchors.py` (`A=9`) и `.orchestra/tasks/504/research.md` строки 1-9 · 2026-09-05, #504 · открыть: `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/check_anchors.py`; `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/research.md`
- **«Слова `DONE`, `RESEARCH DONE`, `PLAN READY` в прозе закрывают задачу» — отвергнуто.** Приёмка `DONE` не читает вовсе, а терминальное состояние веера — типизированный `message_kind` · ищи: `DONE marker`, `RESEARCH DONE`, `PLAN READY`, `message_kind`, «слово DONE закрывает задачу» · опровергнуто: `app/acceptance.py:148`; `app/fan_barrier.py:34`; `.orchestra/tasks/504/research.md` разбор класса B · 2026-09-05, #504 · открыть: `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/research.md`

### Предохранители агента

- **«Открытый commerce-agents — полностью реализованный production blueprint» отвергнуто.** Сам репозиторий объявляет harness оценки зоной ответственности деплоя, примеры не имеют ни авторизации, ни лимитов запросов, а заявления статьи про память и рантайм расходятся с вызывающим кодом · ищи: `fully implemented`, `eval harness`, `auth`, `memory_subject`, «готовый production blueprint» · опровергнуто: `docs/tasks/507/research.md` §§Заявлено в статье, Counter-evidence; upstream `plugins/commerce-builder/skills/commerce-evals/SKILL.md:8-11`, `docs/safety.md:61-86` · 2026-09-03, #507 · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`
- **«Предохранители Orchestra целиком живут в промпте» отвергнуто.** Мерж проверяет кодом происхождение задачи/сессии/ветки, актуальность цели, замороженный оракул и сопоставленные тесты · ищи: `all prompt-only`, `merge_operations`, `pinned oracle`, `mapped tests`, «у нас нет кодовых предохранителей» · опровергнуто: `app/routes/sessions.py:1847-2009`; `app/acceptance.py:349-378`; `app/merge_operations.py:1613-1740`; `app/workspace.py:1290-1597`; `docs/tasks/507/research.md` G3/G8/G9 · 2026-09-03, #507 · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`

## Gaps

### Сборка и доставка промпта

- Сколько токенов реально стоит фиксированная часть хода (промпт + `CLAUDE.md` + скиллы) при
  99% cache_read — не мерили ни разу; все оценки в байтах · 2026-08-19, prompt-engineer
- Доезжают ли правки промптов до УЖЕ ЖИВЫХ сессий без реконнекта и с какой задержкой — известно
  частично (re-injection на resume/compact), сквозного замера на живом агенте нет ·
  2026-08-19, prompt-engineer
- «Грабли» в `CLAUDE.md` (92 920 Б, 64% файла) на дубли построчно не проверялись ·
  2026-08-19, prompt-engineer

### Текст модели как управляющий сигнал

- Какое именно типизированное поле Claude SDK или провайдера отличает терминальный месячный/временной лимит подписки от временного ограничения частоты — из локального кода не видно; текущий адаптер получает баннер общим текстом ассистента плюс родовой `rate_limit` · 2026-09-05, #504 — РЕШЕНО 2026-09-05 #504 фаза 2: в установленном пакете есть `RateLimitEvent.status/rejected` и `rate_limit_type`, а 613 живых событий `allowed` доказывают путь производителя
- Как часто в истории встречались отсутствующие или написанные с ошибкой формы находок ревью класса B — не измерено: #504 проследил последствия отсутствия, но полный корпус артефактов не разбирал · 2026-09-05, #504

### Предохранители агента

- Не проверено живым запросом, действительно ли внешний клиент с подчищенной историей получает чистый контекст у Archestra: вывод сделан чтением пути прокси, платформу намеренно не поднимали; искать `taint bypass` / `подчищенная история`; остановило: запрет поднимать чужую платформу на боевом хосте (#470, постановка) · 2026-09-03, #470
- Не найден код потока «любой submit MCP-сервер → security review → approve»: найден только гейт доверенного реестра образов (`pending-image-approval` / `:id/approve`), а `promote|promotion` по моделям/маршрутам/сервисам пуст; поток может жить под другими словами или во фронтенде; искать `pending-image-approval` / `security review MCP` / «промоушен dev staging prod»; остановило: грепал по `approv`/`promote`, дальше не копал — фронтенд не разбирал · 2026-09-03, #470
- Не измерено, насколько общий санитайзер/забор живых результатов тулов изменит решения Claude/Codex на корпусе Orchestra и не повредит ли он законному содержимому источников · ищи: `live sanitizer efficacy`, `prompt injection eval`, `over-refusal`, «нужен ли fence tool results» · упёрлось в: #507 был ресёрчем по исходникам без разрешения на эксперимент или внедрение · 2026-09-03, #507
- Не выбрано кодовое представление апрува человека для архитектуры и реализации задачи и не доказано, обязан ли мерж требовать такую квитанцию · ищи: `human approval receipt`, `merge gate`, `architecture approval`, «апрув пользователя в коде» · упёрлось в: архитектурное решение требует отдельного обсуждения с владельцем и в фазу 1 #507 не входило · 2026-09-03, #507

## Источники

### Сборка и доставка промпта

- .orchestra/tasks/prompt-cleanup/audit.md — аудит противоречий в правилах и промптах, 19.08.2026
- .orchestra/tasks/203/ — доставка модулей по ролям, утечки в чужие роли
- .orchestra/tasks/220/, .orchestra/tasks/137/ — перечитывание личной памяти на resume/compact

### Текст модели как управляющий сигнал

- `.orchestra/tasks/504/research.md` — полный инвентарь A/B/C, история приёма, тесты на радиус поражения и швы замены. В `main` каталога `.orchestra/tasks/504/` нет вовсе; файл живёт только в истории ветки задачи (проверено 06.09.2026, #523). · открыть: `git show cfef1f91ef0b7b813a97c338fa8e4c295d740997:.orchestra/tasks/504/research.md`

### Предохранители агента

- .orchestra/tasks/470/research.md — Archestra.AI: девять заявок лендинга против кода, разбор «tainted conversation» и прогрессивной загрузки тулов, лицензионные гейты; `.orchestra/tasks/470/anchor-check.txt` — машинная сверка 105 ссылок `путь:строка`.
- docs/tasks/507/research.md — полная матрица приёмов и предохранителей боевых агентов Anthropic против наших, расхождения статьи с кодом, граница необратимых действий, проверка результата и обработка ошибок модели. По пути `docs/tasks/507/` его нет — он в архиве ноутбучных задач (проверено 06.09.2026, #523; побайтово совпадает со снимком `4983598717e3`). · открыть: docs/tasks/507/research.md → `.orchestra/archive/laptop-tasks/507/research.md`
