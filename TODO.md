# Orchestra TODO

## Bugs
- [ ] **Исчерпанная квота Codex даёт пустое падение вместо внятной ошибки** — воркер отдаёт `[auto-report] (stop_reason=error) Turn failed before an explicit report. Last output: (no output)`, и ни в чате, ни в journal Orchestra нет ни слова про лимит. Замер 2026-07-30: два воркера упали одновременно, я сначала решил что лёг API Anthropic (в журнале ноль ошибок, прокси живой, `api.anthropic.com` отвечал 401) — и только `GET /api/usage` показал `codex primary=100%`. Ложный след стоил ~15 минут разбора. У нас уже записано в граблях, что Codex НЕ шлёт отдельный text-event перед error → терминальный лимит надо проверять прямо в error handler и писать явное «квота Codex исчерпана, сброс <дата>». Плюс: воркер в этом состоянии не может даже закоммитить готовую работу — пришлось коммитить за двоих руками (`7354633`, `1cee6e5`)
- [ ] **Тест-изоляция: test_default_equals_upstream загрязняет 106 тестов** — `load_pipeline.cache_clear()` + monkeypatch `PIPELINES_DIR`. Pre-existing. Deselect в CI
- [ ] **Pending tm_sync_log без fire в CLI-контексте** — `_fire_sync` пишет pending до schedule; нет loop → запись висит
- [ ] **TG media buffer race (P2)** — _resolve_media после timeout-flush может записать в чужой слот. Нужен generation counter
- [ ] **Message disappears on agent switch** — SSE reconnect gap. 300ms delay added (partial fix)
- [ ] **TG дубли expandable+image** — partially fixed (skip expandable for Read/Grep/Bash/Glob when image sent), but Edit/Write may still duplicate
- [ ] **RAG-бэкфилл на merge_worker ненадёжен/медленный** — после merge индекс ещё старый: `search_memory` отдаёт предыдущую версию файла как «текущую». Ручной `POST /api/memory/reindex` чинит за ~4 мин. Триггер fire-and-forget → недоказуемо, «не сработал» или «не успел». Проверить: реально ли триггерится и сколько занимает. Найдено при архивации session notes 2026-07-26
- [ ] **Устаревшие копии скиллов в Claude-worktree** — `.claude/skills/` копируется при СОЗДАНИИ worktree и не обновляется: у `audit-fullcycle` до сих пор лежит `self-analysis`, удалённый 2026-07-26. Та же болезнь, что была с AGENTS.md. Осознанно вынесено за скоуп #89

## Features
- [ ] **Команда `/limits` в личке с ботом** (решение юзера 31.07 12:18) — показать остаток квот по запросу. **Только личный чат с ботом, НЕ топики группы.** Закреп и автопост юзер отклонил.
  **Данные уже есть** — `GET /api/usage` отдаёт `anthropic.five_hour/seven_day.utilization + resets_at` и `codex.primary`. Задача про доставку, не про сбор.
  **Требования:**
  - Обработчик в личном чате; в топиках группы команду не регистрировать
  - Показывать ОБА окна Claude (5h и 7d) — расходуются независимо, одно число врёт. Плюс Codex primary
  - Время сброса — в UTC+7 (Красноярск), не в UTC
  - Ответ — буллетами `• название — значение`, БЕЗ таблиц (на телефоне разъезжаются)
  - Не считать `extra_usage.spend_limit_reached` признаком блокировки: базовые окна при нём открыты, агенты работают (замер 30.07: 13 успешных ходов при поднятом флаге)
  - Ошибку `/api/usage` показывать текстом с классом исключения, не молча пустым ответом

## ⏸ КВОТА: Codex/Sol выжран 100%, сброс 2026-08-05 04:15 UTC
**Все воркеры на `gpt-5.6-sol` НЕ РАБОТАЮТ до 5 августа.** Симптом при попытке: `turn failed, no output` — пустое падение без внятной ошибки (см. Bugs, отдельный пункт). Доступно: **Spark 0%** (годен для ≤2 файлов, ясные AC, есть команда тестов), **Claude/Opus 33% недельного** (дорогой, но рабочий).

## 🗓 ЧЕТЫРЕ ЗАДАЧИ НА 5 АВГУСТА (когда сбросится Codex)
Всё встало не из-за ошибок, а из-за квоты. Порядок — по убыванию готовности.

1. **#106 — стенд A/B compact-промптов НЕ РАБОТАЕТ, чинить логирование.** Прогон дважды дал 17 успешных партий против 100 упавших, причина НЕ УСТАНОВЛЕНА: `run_evaluation.py` пишет в лог только счётчик `{"failed": 5}`, а текст ошибки (`stderr`/`stdout` из `invoke_claude`, строки 100-116) теряется. Одиночный вызов теми же флагами воспроизведён вручную — **работает**, `ok: True`, поэтому CLI и флаги (`--safe-mode`, `--effort`, `--tools`, `--no-session-persistence`) исключены. Падает что-то в массовом прогоне. **Сначала починить сохранение ошибки в лог, потом прогонять** — иначе третий прогон снова даст счётчик без объяснения. Цена полного прогона (замер по живому вызову `$0.0408`): ~117 генераций × ~$0.16 ≈ **$19**, около 5% недельного окна Claude. Дешевле: только holdout ≈ $6. Стенд готов и проверен: `docs/tasks/106/{fixtures.json,prompts.py,run_evaluation.py,score_results.py,protocol.md}`, слепое сравнение настроено (`primary-blinding-map.json`), варианты — `ORCHESTRA_CURRENT` / `KESHA_FULL` / `KESHA_HANDOFF_ONLY` / `CONCISE`. У `run_evaluation.py` есть `--resume` — успешные партии не пересчитываются.
2. **#93 (#90 T6)** — атомарные переходы spawn/switch/task под общим локом. Исполнитель: `audit-worktree` (ctx:55%, знает контекст) или `fix-branch-switch` (ctx:41%, только что чинил соседнюю зону). **При возобновлении первым делом отревьюить diff `4badfa3` — T3 так и не проходил Codex-ревью.**
3. **#94 (#90 T7)** — hash-suffix для slug + exact-set skill sync. После #93.
4. **A/B-сравнение Sol против Opus на одной задаче** (запрос юзера 30.07, решение не принято). **ПОЛНЫЙ РАЗБОР С ЦИФРАМИ: `docs/tasks/sol-vs-opus-2026-07-30.md` — читать его, а не пересказ ниже.** Повод: подозрение, что Sol оверинжинирит. **Замер по 5 задачам за 30.07 показал обратное:** прод-код НЕ раздут (#99 — 142 строки, #100 — 482, #102 — 296, #103 — 191, #104 — 6), абстракций «на вырост» нет, все функции по делу. Толстые доки (500-800 строк) — следствие МОИХ формулировок «задача открытая, исследуй и предложи подход». Контрпример: #104 с точным ТЗ (файл+строка+образец) → **6 строк прода**. Чтобы решить вопрос «переходить ли на Claude Max $200 и Opus вместо Sol» — прогнать ОДНУ задачу дважды, обе с жёстким ТЗ, сравнить прод-код / объём доков / найденные баги. Контраргументы против «Opus лучше»: за неделю Opus 9 раз печатал tool-call текстом вместо выполнения (у Sol — 0), а Sol-воркеры 30.07 дважды опровергли гипотезы оркестратора фактами (#103 — предложенный детектор сломал бы 40 живых конфигураций; #105 — причиной был не `grok:null`, а тихий `catch {}`).

## 📋 Кого будить и с чем (состояние на 2026-07-30 17:03)
Все воркеры idle, работа НЕ потеряна, всё смержено. Будить = `send_message`, контекст у них сохранён.

- **`research-compact-prompt`** (#106, ctx:49%) — ЕДИНСТВЕННЫЙ, кто реально работает. Запустил 117 blinded-генераций фоновым джобом `bg-ee3b1796d2` на **Opus** (поэтому квота Codex его не убила), ждёт результата. **Будить НЕ надо** — сам проснётся по завершении джоба и отчитается цифрами. Задача research-only: production `COMPACT_PROMPT` не менять, после Phase 1 — стоп на гейте.
- **`audit-worktree`** (ctx:55%) — ждёт #93 (T6: атомарные переходы spawn/switch/task под общим локом) и #94 (T7: hash-suffix для slug + exact-set skill sync). Разбудить **после 5 августа**. При возобновлении: **T3 так и не проходил Codex-ревью** — отревьюить diff `4badfa3` первым делом.
- **`fix-tg-speed`** (ctx:38%) — свободен, #102 и #104 смержены. Кандидат на следующую TG-задачу, знает очередь доставки досконально.
- **`fix-branch-switch`** (ctx:41%) — свободен, #103 смержен. Знает worktree-lifecycle; логичный исполнитель для #93/#94 наравне с `audit-worktree`.
- **`fix-topic-flicker`** (ctx:43%) — свободен, #99 закрыт целиком.
- **`frontend`** (ctx:54%) — свободен, #105 и #107 смержены. Знает `app.js`, `usage.js`, `tool_call_guard.py`.
- **`prompt-engineer`** (ctx:16%) — простаивает 4 дня, задач не давали.

## ⚠️ Ждёт РЕСТАРТА сервиса (код в main, сервис держит старый)
Накопилось за день, ни одно не активно до перезапуска:
- **#99 T2** — гистерезис иконки топика (⚡ сразу, ☕ через 5 мин тишины)
- **#100** — картинки в TG занимают хронологическую позицию
- **#102** — приоритет текста, сброс просроченной косметики, темп 1.05 с вместо 3.05
- **#104** — картинка результата заменяет текстовый дубль
- **#103** — squash больше не ломает `switch_worker_branch`, `force` проброшен в route+MCP
- **#107** — маркер напечатанного tool-call (дашборд + TG)
- **`ed4e3cd`** — конкурентный 429 не укорачивает flood-барьер
- **`a1bf654`** — правило про личную память `docs/workers/<имя>.md` всем ролям
- **#105** — фронт (выделение текста + usage), это СТАТИКА, рестарт не нужен, достаточно обновить страницу

## 🔔 Сообщить после рестарта
- **`COG-second-brain-orchestrator`** — #103 смержен, его костыль (`git checkout -b task-<id>/<worker> main` руками перед каждой выдачей задачи) больше не нужен. Он репортил баг с тремя воспроизведениями и жёг 2 лишних вызова на каждую задачу при 11 воркерах.
- **`kesha-tg-bot`** — по #106, когда придут цифры A/B compact-промптов.
- **`seedon-orchestrator`** — по #107: напечатанный tool-call теперь виден маркером (у него было 7 таких случаев за неделю).

## 🤔 Открытый вопрос к юзеру (не решён)
**Персональное хранилище воркера.** Механизм `docs/workers/<имя>.md` есть и авто-инжектится (`manager.py:1183`), правило теперь во всех ролях (`a1bf654`). Но остаётся развилка, которую юзер не выбрал: (A) оставить как есть — общий репозиторий, мержи; (B) персональный слой идентичности агента поверх роли, инжект при коннекте, «биздев» = сущность со своим промптом и скиллами, а не аргумент при спавне; (C) хранилище вне git — не мержится, но не версионируется и оркестратор его не видит. Мой выбор: A сейчас (сделано), B отдельным research.

## In Progress
- [ ] **#90 worktree/merge lifecycle — остались T6 и T7** (воркер `audit-worktree`, ctx:55%, ЖДЁТ квоту Codex до **5 августа**). Смержены: T1 `2ad44dc`, T2 `6b08652`, T3 `4badfa3`, T4 `92da149` (#91), T5 `2980fd5` (#92). Осталось: **T6** — атомарные переходы spawn/switch/task под общим локом, задача **#93**; **T7** — hash-suffix для slug + exact-set skill sync, задача **#94**. План: `docs/tasks/90/plan.md`, аудит: `docs/tasks/90/audit.md`. **T3 так и не проходил Codex-ревью** — при возобновлении отревьюить diff `4badfa3` первым делом
- [ ] **Follow-up из ревью #98 T3** (нашёл `grok-backend` на Opus, `docs/tasks/98-grok-runtime-audit/review-t3-opus.md`): **F1** — одна нероутируемая модель от прокси роняет СТАРТ сервера (`main.py:44` не обёрнут, ValueError летит в lifespan до auto-resume; батч атомарный → валидные модели тоже теряются). Асимметрия: недоступный прокси = мягкий фоллбэк, доступный с одним неизвестным id = фатально. **F2** — `get_model_spec('')` кидает, а `_hydrate_row` (`manager.py:783`) кладёт пустую строку при NULL model → `to_dict` роняет ВЕСЬ `/api/sessions`. Сейчас таких строк 0, латентно. **F3** — `_cache_ttl_case` держится на порядке ключей словаря: добавят рантайм ниже `unknown` → ELSE привяжет чужой TTL молча
- [ ] **tg_bridge split P5** — refactor-tg worker (Opus 4.8, ctx:12%) has research+plan done, awaiting impl approval. Split into tg_bot/tg_stream/tg_render/tg_topics
- [ ] **CLAUDE.md 32 285 байт при лимите Codex 32 768 — запас 483 байта.** Следующая же запись выйдет за лимит и Codex обрежет файл ПОСРЕДИ фразы. Либо перевод на английский (кириллица = 2 байта/символ), либо вынос граблей в `docs/`

## Ждут решения юзера
- [ ] **Codex-квота снова выбрана — до 2026-08-04 12:41.** Сбрасывалась 28.07 утром (окно показало 0%), к вечеру исчерпана повторно. Все Sol-воркеры стоят: `audit-worktree`, `grok-quota`, `fix-idle-inbox`, `frontend`, `prompt-engineer`, `feat-skill-index` + воркеры других проектов. **Claude при этом РАБОТАЕТ** (см. грабли про `spend_limit_reached`) → тяжёлое можно вести на Opus 5
- [ ] **Grok: включать ли в `pipeline.yaml` роль.** Сейчас registry-only, выбирается вручную по модели. Решение отложено до повторного боевого прогона с рабочим MCP (первый прогон #98 показал, что MCP до воркера не доходил)
- [ ] **`report_bug` гадит в рабочий чекаут** — пишет в `BUGS.md` и оставляет незакоммиченным → блокирует ВСЕ мержи (сегодня словил дважды: репорт от `legal-outreach` и от `terrain-dev` из polus). Варианты: report_bug коммитит свою запись сам / BUGS.md выносится из рабочего дерева
- [ ] **Перевод остатка CLAUDE.md на английский** — файл чисто агентский (юзер его не читает), кириллица = 2 байта/символ → двойной запас по 32 KiB-лимиту Codex. Делать ОТДЕЛЬНЫМ шагом после архивации, не смешивая
- [ ] **R8: orchestration.md (255 строк)** — НЕ резать вслепую по статье Anthropic. Сначала замер следа инструкций, как в fullcycle-audit
- [ ] **Правило в «Грабли»**: «сузил валидацию на shared runtime → прогони по всем живым sessions.scope из БД, не только по фикстурам» (от fix-repo-path) — ЗАПИСАНО, подтверждение получено постфактум
- [ ] **Личные скиллы из ~/.claude/skills в пайплайн** — какие реально нужны воркерам? Не все скопом. Задача #89 дала механизм (оглавление), осталось решить состав

## Требуют рестарта (сервер перезапущен 2026-07-28 19:07 — накопилось ПОСЛЕ)
Всё смерженное ПОСЛЕ 19:07 не в рантайме: `#98 T1/T2/T3` (fail-closed MCP-изоляция, типизированный usage-контракт, явная маршрутизация моделей), кнопка «Разбудить после сброса» v2 (`35ca920`), правки промптов (`0bc7d5f`, `58d98c6` — подхватываются на следующем ходу, рестарт НЕ нужен).
- [ ] **После рестарта — проверить 3 бага из BUGS.md**, помеченных restart-marker: TG diff images (с 08.06), TG expandable deadlock (вероятно уже починен 5fba15d), auto_resume model overwrite
- [ ] **После рестарта — проверить AGENTS.md у Sol-воркеров**: у `frontend` и `prompt-engineer` файла НЕТ ВООБЩЕ (были Claude-воркерами, зеркало не создавалось), у `audit-fullcycle` лежит старая копия 61 643 байта. Должно самовылечиться на реконнекте — ПОДТВЕРДИТЬ
- [ ] **seedon-orchestrator Fable 5 → Opus 5** — burning 4× limit, DB update needed + restart
- [ ] **TG expandable deadlock** — important=True on expandable caused total TG outbound deadlock. REVERTED. Needs different approach (debounce/separate queue). NOTE: topic_status half of this is now fixed (a566371)
- [ ] **auto_resume overwrites DB model** — live server rewrites `sessions.model` from in-memory on shutdown/persist. Observed 2026-07-25: bulk UPDATE to Opus 5 was silently reverted for loaded agents. Workaround = re-run UPDATE and restart. Root cause still unfixed
- [ ] **Measure codex-sleep fix** — 7 days or 30 Sol review jobs, then decide if a PreToolUse sleep guard is still needed (baseline: 74 sleeps / 1579 Codex bash calls = 4.69%)

## Next
- [ ] **Opus 5 canary metrics** — research recommended measuring before fleet-wide trust: ≤+15% median agentic steps, ≤+25% cost & 5h-points per completion vs Opus 4.6/4.8 baseline. Not yet measured — we switched everything at once on user's order
- [ ] **Admission budget for Opus 5** — research advises ≤8 new Opus tasks per 5h window, ≤2 concurrent Claude sessions until a real A/B exists
- [ ] **gamedesign-researcher unloadable** — `role 'researcher' not resolvable in pipeline 'default'` on every startup; role was deleted when merged into full-cycle. Either migrate the session's role or archive it
- [ ] **send_message auto-switch (#80)** — task_id param for auto switch_branch before delivery. Priority HIGH
- [ ] **Sound notification on idle (#79)** — Web Audio API + browser Notification when agent finishes
- [ ] **Auto-learning из ошибок (#76)** — Self-Harness: weakness mining → harness proposal → validation
- [ ] **OpenRouter Fusion (#78)** — multi-model deliberation API for code review
- [ ] **Design review скилл** — impeccable + taste-skill for frontend workers
- [ ] **merge_worker показывать diff** — changeset перед мержем
- [ ] **Раздробить app.js (4500+ строк)** — модули: chat.js, tools.js, tasks.js, files.js, agents.js, sse.js
- [ ] **TG verbosity** — фильтрация tool/status по уровню TG_VERBOSITY=low|medium|high
- [ ] **VPS parsing cost guard** — предупреждать/блокировать turn'ы дороже $X

## После ближайшего рестарта orchestra

- [x] ~~Снять хардкод `_roleIcons`~~ — **ОТМЕНЕНО** (решение оркестратора, 04.08).
      `/api/role-icons` вызывается с `.catch(()=>{})`, то есть хардкод — не вторая копия
      истины, а ЕДИНСТВЕННЫЙ запасной путь при отказе эндпоинта. Удалять нельзя.
- [ ] **Клиентская половина #37** — heartbeat на HEAD `/api/models` (сейчас 405; раньше
      рестарта нельзя: получим 405 без `X-Orchestra-Build` и молча убьём баннер #15).

## Ideas
- [ ] **Codex как streaming tool** — видеть прогресс codex в реальном времени
- [ ] **Cross-server messaging** — связь между Orchestra на разных серверах
- [ ] **Emergency failover** — автопереключение на API ключи если подписка слетела
- [ ] **Best-of-N solving** — N воркеров, reviewer выбирает лучший (или OpenRouter Fusion)

- [ ] `tests/test_frontend.py`: `expect(chat).to_contain_text("🟠 High")` — подстрочное сравнение, мутация `High`→`Highest` его не роняет (найдено в #145, вне объёма задачи). Сделать ассерт точным.
- [ ] График usage: ~161 ЗАКОННЫЙ ноль (провайдер ответил `utilization: 0`, но без `resets_at`) не рисуется ни на фронте, ни на бэке — оба слоя ведут себя одинаково с прежнего кода. Чинить одной задачей на два слоя; подробности в `docs/tasks/150/report.md` (найдено в #150).
