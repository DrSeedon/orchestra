# V-1228 — «90-минутный мастер-класс Anthropic по Claude Managed Agents»: источник и применимость к Orchestra

RESEARCH ONLY: ничего не внедрено, правила/код не менялись, платных API/inference-вызовов не было. Видео не просмотрено, транскрипт не получен (§4).

## 1. Идентификация

**Точный первоисточник НЕ установлен; есть сильный кандидат.**
- Пост https://t.me/s/vibecoding_tg/4245 → https://youtu.be/YL-vgQepS2I: «Anthropic Engineers Reveal How to Build AI Agents with Claude Opus 5.5», 1:34:46, 15.10.2026, канал **Dev Docs Explained** (@WatchNCode) — **не Anthropic**; спикеры не названы; авторские главы: 00:00 intro, 07:45 «Opus 5.5 architecture», 23:40 skills/loops/memory graphs, 54:00 dreaming & orchestration, 1:10:23 «Reverse engineering».
- **Кандидат-оригинал:** воркшоп «Claude Managed Agents», AI Engineer World's Fair 2026 (SF), канал AI Engineer, 11.10.2026; спикеры **Priyanka Phatak** (руководит инженерной командой CMA) и **Gabe Cemaj** (MTS Anthropic). Части 1–4: https://www.youtube.com/watch?v=Uv0nAf_7tyU (17:40), https://www.youtube.com/watch?v=FGftGOzfohc (35:36), https://www.youtube.com/watch?v=qJtcEDc_WJU (26:31), https://www.youtube.com/watch?v=QSeaZ6qHyXs (18:58); всего 98:45.
- Косвенно «за»: реаплоад на 4 дня позже и на ~4 мин короче; его 7:45 точно совпадает с главой ч.1 «Decoupling the brain from the hands»; 23:40 и 54:00 в пределах ~1 мин от начала setup ч.2 (17:40+6:10) и начала ч.3 (53:16); все темы поста есть в официальных главах. «Против»: главе «Reverse engineering» нет соответствия (там Q&A ч.3 про AWS/модели); подписей «Opus 5.5 architecture»/«memory graphs» в официальных главах нет. Содержание ч.2 подтверждено официальным репо (research desk, EDGAR skill, NVDA, rubric/grader, shared memory, deployments — `research-desk/WORKSHOP.md`, шапка «AI.Engineer World's Fair»).
- Смежные, НЕ источник поста: «Ship your first Managed Agent» https://www.youtube.com/watch?v=19HDQ9HppOA (канал Claude, 26.05.2026, Isabella He); «Memory and dreaming for self-learning agents» https://www.youtube.com/watch?v=RtywqDFBYnQ (канал Claude, 08.05.2026); вебинар https://claude.com/resources/webinars/ship-your-first-claude-managed-agent (Isabella He + Eric Liu/Notion; видео за формой, memory/dreaming не упомянуты).

## 2. Механизмы Anthropic и Orchestra

Метки: **Ф** — факт документации/кода; **А** — заявление Anthropic/клиента (несравнимо с нами); **В** — наш вывод. Польза для Orchestra везде **НЕ ИЗМЕРЕНА**; цена — оценка.

1. **Сессия = append-only журнал вне контекста; brain/hands разделены; восстановление `wake(sessionId)` → `getSession` → продолжение с последнего события.** Ф: engineering-пост, разделы «Session», «Recovery». А: p50 TTFT −60 %, p95 −90 % (в описании AIE ч.1 — «~90 %»).
   Orchestra (Ф, код): журнал в БД читается агентом (`search_logs`/`get_log_context`, `app/mcp_stdio.py:1959,1998`) и компактом (`app/agentic_compact.py`); доставки durable (`message_deliveries.py`, `initial_deliveries.py`, `restart_inbox.py`, `fan_barrier.recover_deadlines`). Восстановление хода: нативное состояние провайдера + `resume_session_id` (`app/session.py:932`), Codex `thread/resume` (`app/backend_codex.py:903,912`); прерванный рестартом ход получает wake-текст, а без нативного id — переигрывание сообщений срезанного хода (`manager.restart_notice_text`, `app/manager.py:476`, V-919); фоновые `run` переживают рестарт (`bg_jobs.py:307,1423`).
   Граница (В): у них единственный источник продолжения — их журнал; у нас — нативная история CLI + наш журнал/переигрывание. Частоту и объём реальных потерь продолжения я не измерял; AGENTS.md называет риск и процедуру восстановления (cut_names), это не замер. **Вердикт: не брать (миграция архитектуры, вне задачи).**
2. **Учётные данные недоступны песочнице: vault + egress-прокси подставляют секрет; git-токен в remote.** Ф: тот же пост, «Credentials»; AIE ч.1 9:05, ч.2 23:53.
   Orchestra: **частичное сходство** только на hub-пути — в hub-копию не входят `.git`/remote/токены, связь через `.orchestra-outbox.jsonl` (`app/hub_outbox.py`; условия моей роли). Это исключение секретов из пакета, а **не** подстановка на egress; учётки провайдера и окружение хоста хаба я не проверял, и отсутствие `.git` не доказывает отсутствие всех секретов. Локальные воркеры: docstring `_acceptance_command_from_caller` (`app/mcp_stdio.py:1686`) описывает threat model «shell с полным sudo» — это документ, не моя проверка привилегий. **Вердикт: не брать сейчас (архитектурная развилка владельца).**
3. **Outcomes: markdown-rubric; grader в отдельном контексте; `satisfied`/`needs_revision`/`max_iterations_reached`/`failed`/`interrupted`; `max_iterations` 3 по умолчанию, ≤20.** Ф: docs define-outcomes. А: «до +10 п.», +8,4 % docx / +10,1 % pptx (internal); Wisedocs «50 % быстрее» (клиент).
   Orchestra: детерминированный аналог `acceptance.pin_task_oracle`/`evaluate_pinned_oracle` (`app/acceptance.py:240,349`) — команда + манифест тестов, SHA-256, `oracle_input_mutated`, запуск платформой при мерже (`app/merge_operations.py` ~2047–2110). Граница: судья — тест, не модель; автоповтора нет. **Вердикт: модельного грейдера не брать** — model review заморожен владельцем 20.09.2026 (`modules/orchestration.md:103`, `report-format.md:12`); это не предложение снять заморозку.
4. **Advisor** (Ф: docs multiagent-orchestration, «Give the session an advisor»): модель, которую primary thread консультирует посреди хода — план, выход из тупика, «review work before finishing»; отдельный тред, совет приходит событием, сбой не валит ход, не может быть слабее агента. Это **консультант, не грейдер** outcomes (тот оценивает артефакт по rubric). Но использование «проверь работу перед завершением» пересекается с замороженным model review. **Вердикт: не предлагать**.
5. **Memory store:** `/mnt/memory/<slug>`, описание и instructions (≤4096 зн.) в system prompt, `read_only`/`read_write` на уровне ФС, ≤8 store на сессию, ≤10 000 записей, неизменяемые версии (30 дн.), redact, `content_sha256`-предусловие. Ф: docs memory.
   Orchestra: аналог в иной форме — `.orchestra/workers/<name>.md` целиком в промпте (`app/prompting.py:157`), KB только индексом тем (`app/kb_index.py`), версии/аудит — git, конкуренция — мерж. Нет ro/rw-разделения на уровне хранилища. **Вердикт: уже есть аналог; `content_sha256` для git-файлов не нужен.**
6. **Skills:** версии, `version: latest`, загрузка по требованию, правка как живого артефакта. Ф: `research-desk/WORKSHOP.md` Act 2/4. Orchestra: `prompting.inject_skills_to_worktree_report` (`app/prompting.py:338`) копирует skills роли при каждом (пере)подключении; по требованию грузит CLI; нумерации версий нет, источник — git. **Вердикт: уже есть.**
7. **Multiagent:** изолированные треды над общей ФС, 1 уровень делегирования, ≤20 predefined, 25 дочерних тредов, follow-up подагенту, dynamic workflows, бюджет. Ф: docs multiagent-orchestration. Orchestra: `spawn_worker` (worktree), `app/fan_barrier.py`, `dynamic_workflow`/`app/workflow_scheduler.py`; sub-orchestrator заморожен (`pipeline.yaml:86`). Граница: у нас изоляция по worktree, у них общая ФС. **Вердикт: уже есть.**
8. **Deployments (агент+расписание+ресурсы, новая сессия на запуск).** Ф: WORKSHOP.md Act 6. Orchestra: `bg_create` `cron`/`cron_command` (`app/mcp_stdio.py:3705`, `app/bg_jobs.py`) будит существующего агента. **Вердикт: уже есть (в другой форме).**
9. **«Допущения harness устаревают с моделями»** (context resets для Sonnet 4.5 стали лишними на Opus 4.5). Ф/А: engineering-пост, «Core premise». Orchestra: политика компакта (`agentic_compact.py`, `session._compact_prompt`) отмерена на Sonnet/Opus 5.x (KB V-643/V-961/V-963); перепроверки при смене модели нет. **Кандидат К1 (§3).**

## 3. Dreaming и наш опыт

- **Что есть у Anthropic (Ф, docs dreams):** асинхронная задача; вход — store + 1–100 транскриптов; выход — НОВЫЙ store, вход не меняется; `instructions`; ход наблюдаем как сессия; результат проверяют и подключают или выбрасывают. Цена ~линейна от числа/длины сессий. А: Harvey «~6x completion» — клиентская цифра без условий, не переносится.
- **V-1114 (KB `knowledge-base.md`) — НЕ испытание Dreaming:** консолидация существующей памяти, одна память, одна модель, потолок точности 40/40, т. е. выигрыш там недостижим по дизайну. Из него следует только узкое: (а) **выявлен риск** — сжатие без доступа к источникам в этом стенде теряло редкие точные детали (**hurt**); (б) консолидация со ссылками и пакетом источников — **no observed effect** при потолке. Совпадение с Dreaming — принцип «оригинал остаётся» (их новый store = наш cue).
- **Синтез из транскриптов** (основное отличие Dreaming) у нас **не испытывался**: доказанной пользы нет, но и вывода «не работает» нет. #454 — другой корпус и модель, exploratory post-hoc оценка; переносим только сигнал: проверять сохранение отмен/условий, а не его числа.
- Об устройстве их memory: изученные docs не описывают разделение «канонические правила / KB / память», как у нас; сравнивать по этому признаку не могу. Ноль поведенческих ошибок в V-1114 не доказывает, что их удерживает именно наш слой правил.
- **Вердикт:** регулярный автоматический «сон» не вводить без опыта; кандидат К2 ниже.

**Кандидаты (оба класс C — нужно «да» владельца, траты подписки; польза НЕ ИЗМЕРЕНА):**

| | Что | Важность (В) | Цена (оценка) | Проверка |
|---|---|---|---|---|
| К1 | При смене основной модели повторить стенд V-963 (цепочка компактов) на ней | средняя: компакт — путь всех долгих сессий | ~1 день, подписка | контраст старая/новая модель на тех же входах; доля сохранённых фактов, обрушения |
| К2 | Офлайн-синтез кандидатов находок из N завершённых журналов задач → в отчёт задачи, без автопромоции в KB; новый store рядом, оригинал не трогать | низкая–средняя: дублирует ручное извлечение | 1–2 дня, подписка | эталоны с отменами/условиями (метод #454, свежий корпус); принимать, только если не хуже ручного пути по отменам и полноте |

## 4. Проверки и ограничения

- Целевой pytest (до правки отчёта, повторно не запускался): uv 0.11.28, 9 файлов (`acceptance`, `merge_target_oracle_386`, `agentic_compact_650`, `compact_carry_963`, `fan_barrier`, `hub_outbox_validation_v1222`, `kb_index_injection_522`, `optional_worker_memory_v1069`, `laptop_skill_delivery_572`) → **162 passed in 146.26s**, exit 0; `app` импортирован из точной рабочей копии исполнителя; абсолютный путь сохранён в локальном `raw/app-import.txt`. Подтверждает поведение цитируемых символов, не их применимость к механизмам Anthropic. Дословно — `raw/pytest.log`, `raw/app-import.txt`.
- Не выполнено: полный тест-набор (код не менялся); просмотр видео; транскрипты (`get_transcript` → 400 FAILED_PRECONDITION; player ANDROID_VR/IOS → LOGIN_REQUIRED; watch-страница — бот-стена; videohighlight.com — без транскрипта); вебинар claude.com (форма); живые API/Console/dreams (не авторизованы). Отчёты V-1114/#454/V-963 в моей копии отсутствуют — использованы резюме KB.

## 5. Индекс источников (fetch 02.11.2026)

| URL | Версия / статус |
|---|---|
| https://t.me/s/vibecoding_tg/4245 | ok, текст поста + ссылка |
| https://www.youtube.com/watch?v=YL-vgQepS2I | метаданные ok через youtubei next/search; видео/транскрипт — нет |
| https://www.youtube.com/watch?v=Uv0nAf_7tyU , https://www.youtube.com/watch?v=FGftGOzfohc , https://www.youtube.com/watch?v=qJtcEDc_WJU , https://www.youtube.com/watch?v=QSeaZ6qHyXs | метаданные и главы ok; транскрипт нет |
| https://www.youtube.com/watch?v=19HDQ9HppOA , https://www.youtube.com/watch?v=RtywqDFBYnQ | метаданные ok (смежные) |
| https://www.anthropic.com/engineering/managed-agents | ok; «Scaling Managed Agents», 08.04.2026, Lance Martin, Gabe Cemaj, Michael Cohen |
| https://claude.com/resources/articles/new-in-claude-managed-agents | ok; 19.05.2026 |
| https://claude.com/resources/webinars/ship-your-first-claude-managed-agent | страница ok, видео за формой |
| https://platform.claude.com/docs/en/managed-agents/dreams | ok; research preview; beta `dreaming-2026-04-21` + `managed-agents-2026-04-01`; версия страницы не указана |
| https://platform.claude.com/docs/en/managed-agents/memory | ok; beta `agent-memory-2026-07-22` |
| https://platform.claude.com/docs/en/managed-agents/define-outcomes | ok; beta `managed-agents-2026-04-01` |
| https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration | ok; `multiagent_20261001` |
| https://github.com/anthropics/cwc-workshops/tree/4c34ec4863dfdc6b0ba3a473bd3408eb38660c22 | commit 16.10.2026; прочитаны `agents-that-remember/README.md` (blob 33ecf19b4f82326911121c77c1539e98a6ab4616, sha256 93dbc376028cd441ea38710574e2d722624e8d3b04d578ee05b7170dd39f225d) и `research-desk/WORKSHOP.md` (blob 5b17a9a7929b6c995f177b056381e48228df4b74, sha256 507b8f26318ad90138bad9046c43c5e4188663b4b70f54427ec891a859f21265) |

Страницы docs не имеют ревизий; их содержимое могло измениться после 02.11.2026 — копии не сохранены (чужой текст).

**Raw (локально, игнорируется `.orchestra/tasks/V-1228/.gitignore` → `/raw/`):** `raw/PROVENANCE.txt` (URL и статус каждого файла), `raw/INDEX.sha256` (полные SHA-256 исходных ответов YouTube, файлов репо, pytest.log, извлечённых метаданных), `raw/youtube-metadata.json` (title/date/channel/description/длина 7 видео, извлечено из ответов youtubei), `raw/pytest.log`, `raw/app-import.txt`. Полные ответы YouTube (≈4 МБ) и клон репо в задачу не копировались; они во временном `/tmp/v1228-raw.mOKf/` (может быть удалён), хеши — в индексе.
