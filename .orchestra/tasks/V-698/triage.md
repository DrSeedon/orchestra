# V-698 — TODO triage

Триаж сделан по исходному `TODO.md` в `main` SHA `71a008fe`. Пункт — каждая верхнеуровневая строка `- [ ]`/`- [x]` и `- **…**`; вложенные пункты внутри маркированных абзацев отдельно не считались. Исходный номер строки сохранён для перехода к полному тексту в этом коммите. Проверки живого процесса и его данных выполнены только на чтение; состояние main для рестартных пунктов сверено с `af2446b6`. Для свежих красных тестов приведены буквальные выводы текущих точечных прогонов в `evidence/`; остальные исторические основания доступны по указанному Git-снимку/артефакту.

Вердикты: FIXED — в текущем main дефекта нет; OBSOLETE — предмет исчез/разовое событие; OPEN-DEFECT — актуальное поведение/дефект оставлен в TODO; NEEDS-OWNER — требует решения владельца; NOTE — находка или идея, не активная задача. В колонках области/размера/рестарта/живых данных/независимости значения заполнены только у OPEN-DEFECT.

| № | Строка исходного TODO.md | Короткое название | Вердикт | Доказательство | Область | Размер | Нужен рестарт | Трогает живые данные | Независим |
|---:|---:|---|---|---|---|---|---|---|---|
| <a id="t001"></a>1 | L3 | Обновить Actions, всё ещё объявляющие Node 20 (снятие рантайма уже состоялось) | OPEN-DEFECT | evidence/node20_runtime_probe.txt; evidence/node20_deprecation.txt; .github/workflows/ci.yml:36,39 | CI | S | нет | нет | да |
| <a id="t002"></a>2 | L4 | Подпись полосы гейта квот не переводится: в английском интерфейсе пилюля гейта чит… | OPEN-DEFECT | app/quota_gate.py:272-280 | Dashboard / i18n | S | нет | нет | да |
| <a id="t003"></a>3 | L5 | Даты и деньги в английском интерфейсе форматируются по-русски: «вт, 6 окт., 19:15»… | OPEN-DEFECT | app/static/js/analytics.js:652-663; app/static/js/usage.js:46 | Dashboard / i18n | S | нет | нет | да |
| <a id="t004"></a>4 | L6 | Миграция раскладки проекта при старте прячет незакоммиченные файлы проекта в stash… | OPEN-DEFECT | app/orchestra_layout.py:1162 onward (stash precedes migration; restore follows success) | Project layout migration | L | да | да | да |
| <a id="t005"></a>5 | L7 | V-620 переименовал _CODEX_REVIEW_DEFAULT_MODEL в app/mcp_stdio.py на gpt-6-luna, но | FIXED | evidence/red_mcp_codex_review.txt — 20 passed | — | — | — | — | — |
| <a id="t006"></a>6 | L11 | tests/test_logs_sync.py::TestRoute::test_chat_snapshot_is_never_served_from_http_c… | FIXED | evidence/red_logs_sync.txt — 1 passed | — | — | — | — | — |
| <a id="t007"></a>7 | L14 | prompt_template_hash не видит модули, поэтому правка любого правила в prompts/modu… | FIXED | .orchestra/tasks/V-577/report.md (recorded in 71a008fe:TODO.md:L14) | — | — | — | — | — |
| <a id="t008"></a>8 | L15 | Контракт «замороженные acceptance-тесты не ослаблять» ведётся двумя независимыми к… | NEEDS-OWNER | 71a008fe:TODO.md:L15 (original detailed record) | — | — | — | — | — |
| <a id="t009"></a>9 | L16 | tests/test_tailwind_css.py::test_committed_css_matches_current_sources красный на… | FIXED | evidence/red_tailwind_css.txt — 1 passed | — | — | — | — | — |
| <a id="t010"></a>10 | L17 | 13 тестов зависят от окружения запускающего: без DASHBOARD_*/ORCHESTRA_* (чистый s… | NOTE | .orchestra/tasks/V-624/report.md (recorded in 71a008fe:TODO.md:L17) | — | — | — | — | — |
| <a id="t011"></a>11 | L18 | tests/test_tg_bridge.py::TestLimitsCommand (test_limits_uses_important_file_delive… | NOTE | .orchestra/tasks/V-624/report.md (recorded in 71a008fe:TODO.md:L18) | — | — | — | — | — |
| <a id="t012"></a>12 | L19 | Гейт мутации при мерже (app/merge_test_gate.py) передаёт pytest УДАЛЁННЫЕ тест-фай… | OPEN-DEFECT | app/merge_test_gate.py:225,574-577 | Merge test gate | M | да | нет | да |
| <a id="t013"></a>13 | L20 | cog-second-brain снова сломает раскладку при первой же ретро. | NEEDS-OWNER | .orchestra/tasks/V-632/report.md (recorded in 71a008fe:TODO.md:L20) | — | — | — | — | — |
| <a id="t014"></a>14 | L21 | bg_create(type="run") исполняет команду в cwd сервиса /home/kesha/orchestra, а не… | OPEN-DEFECT | app/bg_jobs.py:1054-1058 (local subprocess call has no cwd) | Background jobs / cwd | M | да | да | нет |
| <a id="t015"></a>15 | L22 | Загрузить Python-правки пакета стабильности в живой сервис после отдельной команды… | FIXED | commit e2e83139; evidence/restart_commit_audit.txt — merged to main before 05.10 process start | — | — | — | — | — |
| <a id="t016"></a>16 | L27 | Хроника сессий — тоже сырьё, и её надо пропустить через конвейер «сырьё → знание»… | NOTE | 71a008fe:TODO.md:L27 (original detailed record) | — | — | — | — | — |
| <a id="t017"></a>17 | L32 | Починить два checkout'а, на которых падает миграция layout. | NEEDS-OWNER | 71a008fe:TODO.md:L32 (original detailed record) | — | — | — | — | — |
| <a id="t018"></a>18 | L33 | Оценить потерю данных от обнуления файлов 13.09. | OBSOLETE | 71a008fe:TODO.md:L33 (original detailed record) | — | — | — | — | — |
| <a id="t019"></a>19 | L34 | Канал алерта на упавшую Orchestra. | NEEDS-OWNER | 71a008fe:TODO.md:L34 (original detailed record) | — | — | — | — | — |
| <a id="t020"></a>20 | L38 | Два правила гейта мержа противоречат друг другу: «домержи main, если ветка отстала… | OPEN-DEFECT | 71a008fe:TODO.md:L38; current prompt pair to reconcile | Merge policy prompts | S | нет | нет | да |
| <a id="t021"></a>21 | L39 | Заведение задач в проекте orchestra мертво: canonical=502, legacy=504. | FIXED | evidence/red_task_project_identity.txt — 2 passed | — | — | — | — | — |
| <a id="t022"></a>22 | L43 | gpt-5.4 мёртв у провайдера, но всё ещё в реестре. | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t023"></a>23 | L44 | CODEX_REASONING_EFFORTS (app/backend_codex.py:82) расходится с реальностью в обе с… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t024"></a>24 | L45 | AGENTS.md доезжает до модели целиком (203 311 Б при потолке 262 144), но вырос вдв… | FIXED | evidence/root_instruction_size.txt — 12662 bytes, below the 16 KiB limit | — | — | — | — | — |
| <a id="t025"></a>25 | L46 | Регистрация Astra автоматически делает её легальной моделью codex_review | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t026"></a>26 | L47 | Надбавка за контекст >272K на подписочные кредиты не документирована. | NOTE | 71a008fe:TODO.md:L47 (original detailed record) | — | — | — | — | — |
| <a id="t027"></a>27 | L48 | Не измерено и стоит измерить: | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t028"></a>28 | L52 | 89% недельного лимита выжигает ORCHESTRA, интерактив — 11%. | NOTE | 71a008fe:TODO.md:L52 (original detailed record) | — | — | — | — | — |
| <a id="t029"></a>29 | L53 | Первая версия этого замера дала «70% жрёт интерактив» и ОТОЗВАНА — двойной счёт. | NOTE | 71a008fe:TODO.md:L53 (original detailed record) | — | — | — | — | — |
| <a id="t030"></a>30 | L54 | «turn_usage теряет 18–25% трафика» — ОТОЗВАНО ПОЛНОСТЬЮ, дефекта нет. | NOTE | 71a008fe:TODO.md:L54 (original detailed record) | — | — | — | — | — |
| <a id="t031"></a>31 | L55 | Счётчик у аккаунта ОДИН, его делят обе машины. | NOTE | 71a008fe:TODO.md:L55 (original detailed record) | — | — | — | — | — |
| <a id="t032"></a>32 | L56 | Коэффициенты на дедуплицированных данных (50 окон, R² 0.808): | NOTE | 71a008fe:TODO.md:L56 (original detailed record) | — | — | — | — | — |
| <a id="t033"></a>33 | L57 | Чтение кеша в подписке ≈ бесплатно | NOTE | 71a008fe:TODO.md:L57 (original detailed record) | — | — | — | — | — |
| <a id="t034"></a>34 | L58 | Метод she-llac у нас НЕ воспроизводится, и это проверено. | NOTE | 71a008fe:TODO.md:L58 (original detailed record) | — | — | — | — | — |
| <a id="t035"></a>35 | L59 | Лимит в пересчёте на API-доллары: ×164 на нашем профиле. | NOTE | 71a008fe:TODO.md:L59 (original detailed record) | — | — | — | — | — |
| <a id="t036"></a>36 | L60 | Методический урок, правило наше собственное и было нарушено: | NOTE | 71a008fe:TODO.md:L60 (original detailed record) | — | — | — | — | — |
| <a id="t037"></a>37 | L64 | Главная находка НЕ про калибровку ревью: 2 дефекта дизайна из 3 вообще НЕ ДОШЛИ до… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t038"></a>38 | L65 | Один дефект был ПОЙМАН в ревью плана и потерян между планом и кодом. | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t039"></a>39 | L66 | Ноль из трёх дефектных диффов получили чистый APPROVED. | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t040"></a>40 | L67 | Больше раундов не помогает — на #409 замерено. | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t041"></a>41 | L68 | Правило-STOP как чистый промпт НЕ проходит порог: 2/3 попаданий при 0/6 ложных. | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t042"></a>42 | L69 | Цена правила названа честно и неполно: 234 токена o200k_base — это размер текста с… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t043"></a>43 | L70 | Гипотеза-преемник, не проверенная: механическая квитанция идентичности/владения на… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t044"></a>44 | L71 | Лексические триггеры (_id, key, email) непригодны | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t045"></a>45 | L75 | V-629: сохранение раскладки защищает грязные данные. | FIXED | .orchestra/tasks/V-629/report.md (recorded in 71a008fe:TODO.md:L75) | — | — | — | — | — |
| <a id="t046"></a>46 | L76 | Ноутбук: добавить --timeout-graceful-shutdown 5 в ExecStart юнита orchestra | NEEDS-OWNER | 71a008fe:TODO.md:L76 (original detailed record) | — | — | — | — | — |
| <a id="t047"></a>47 | L77 | Оркестратор dev-lead на ноутбуке не переводится на другую модель: | NEEDS-OWNER | 71a008fe:TODO.md:L77 (original detailed record) | — | — | — | — | — |
| <a id="t048"></a>48 | L78 | Ноутбучные проекты без файлов каталога: пустые чипы проектов. | NEEDS-OWNER | 71a008fe:TODO.md:L78 (original detailed record) | — | — | — | — | — |
| <a id="t049"></a>49 | L79 | Тест-сервер uvicorn запускает migrate_v621() и коммитит в рабочий checkout. | FIXED | commit c963aa26 (recorded in 71a008fe:TODO.md:L79) | — | — | — | — | — |
| <a id="t050"></a>50 | L80 | Общий .orchestra/projects.yaml конфликтует при каждой синхронизации ноутбука с VPS. | FIXED | commit 4321ff7a; .orchestra/tasks/V-621/report.md (scope-local catalog replaces shared laptop file) | — | — | — | — | — |
| <a id="t051"></a>51 | L81 | Миграция V-621 сделала служебный коммит в ноутбучном checkout Orchestra | NEEDS-OWNER | commit 1525b636 (recorded in 71a008fe:TODO.md:L81) | — | — | — | — | — |
| <a id="t052"></a>52 | L82 | Общий стек git stash уносит работу воркеров. | OPEN-DEFECT | 71a008fe:TODO.md:L82 (preserved incident and shared-stash observation) | Git worktree safety | M | нет | да | да |
| <a id="t053"></a>53 | L83 | Полный прогон тестов убивается собственным сторожем выхода | FIXED | commit 6d7b5793; .orchestra/tasks/V-624/report.md (restart guard no longer kills full pytest) | — | — | — | — | — |
| <a id="t054"></a>54 | L84 | test_i18n_dashboard::test_dictionary_reaches_marked_attributes шаткий в полном про… | OPEN-DEFECT | evidence/test_i18n_marked_attributes.txt — 1 passed alone; ordering interaction remains untested | Test isolation | S | нет | нет | да |
| <a id="t055"></a>55 | L85 | Квотный гейт тормозит только НОВЫЕ ходы воркеров, а оркестраторы жгут пул без огра… | NEEDS-OWNER | 71a008fe:TODO.md:L85 (original detailed record) | — | — | — | — | — |
| <a id="t056"></a>56 | L86 | Воркер на adhoc-ветке с готовой работой по задаче не мержится штатно (seedon, 23.0… | FIXED | commit 63fd7ac2; .orchestra/tasks/V-631/report.md (explicit task merge for taskless sessions) | — | — | — | — | — |
| <a id="t057"></a>57 | L87 | ОТКРЫТО: Codex CLI обновлён до 0.156.1 (23.09, ради GPT-6), а импорт истории закре… | OPEN-DEFECT | evidence/red_codex_history_pin.txt — 1 failed; evidence/codex_history_runtime_version.txt — CLI 0.156.1 vs pin 0.153.4 | Codex history import | M | да | да | да |
| <a id="t058"></a>58 | L88 | ОТКРЫТО: совместим ли наш рендерер истории с Claude CLI 2.1.258. | NOTE | 71a008fe:TODO.md:L88 (original detailed record) | — | — | — | — | — |
| <a id="t059"></a>59 | L90 | Приёмка «поиск старых путей возвращает ноль» НЕВЫПОЛНИМА и вредна — я задал её в п… | NOTE | 71a008fe:TODO.md:L90 (original detailed record) | — | — | — | — | — |
| <a id="t060"></a>60 | L94 | На ноутбуке юзера Hermes v0.20.1 пишет навыки и память БЕЗ апрува, и это его насто… | NEEDS-OWNER | 71a008fe:TODO.md:L94 (original detailed record) | — | — | — | — | — |
| <a id="t061"></a>61 | L95 | Идея на A/B, не на внедрение: единый вычислительный namespace («контекст как перем… | NOTE | 71a008fe:TODO.md:L95 (original detailed record) | — | — | — | — | — |
| <a id="t062"></a>62 | L98 | Ловить rate_limit_event и сохранять НЕокруглённую utilization. | NEEDS-OWNER | 71a008fe:TODO.md:L98 (original detailed record) | — | — | — | — | — |
| <a id="t063"></a>63 | L101 | tests/test_api.py::TestTaskProjectIdentity — два теста красные с 28.08. | FIXED | evidence/red_task_project_identity.txt — 2 passed | — | — | — | — | — |
| <a id="t064"></a>64 | L102 | tests/test_tailwind_css.py::test_committed_css_matches_current_sources красный на… | FIXED | evidence/red_tailwind_css.txt — 1 passed | — | — | — | — | — |
| <a id="t065"></a>65 | L105 | ЗАКРЫТО V-695 (см. CHANGELOG, .orchestra/tasks/V-695/report.md). | FIXED | .orchestra/tasks/V-695/report.md (recorded in 71a008fe:TODO.md:L105) | — | — | — | — | — |
| <a id="t066"></a>66 | L106 | Codex usage fetch failed: с пустым текстом — 15 раз за 01–04.10 (error_watch V-647). | OPEN-DEFECT | app/routes/system.py:872; historical report in 71a008fe:TODO.md:L106 | Codex usage snapshot | S | да | нет | да |
| <a id="t067"></a>67 | L107 | P1. Сообщение, влитое в идущий ход Codex, НЕ переживает обрыв этого хода — и теряе… | OPEN-DEFECT | 71a008fe:TODO.md:L107 (incident record; Codex active-turn message path) | Codex message delivery | L | да | да | да |
| <a id="t068"></a>68 | L109 | Нет единого события приёмки, поэтому спор «какая модель лучше» решается памятью, а… | NEEDS-OWNER | 71a008fe:TODO.md:L109 (original detailed record) | — | — | — | — | — |
| <a id="t069"></a>69 | L110 | Привязка задачи не встаёт при спавне роли sub-orchestrator, и мерж потом отбивается. | OPEN-DEFECT | 71a008fe:TODO.md:L109 (spawn_worker task-binding incident) | Worker/task lifecycle | M | да | да | да |
| <a id="t070"></a>70 | L111 | Подпроцессы MCP не наследовали выбор состояния — ПОЧИНЕНО e86fc63f, ждёт рестарта. | FIXED | commit e86fc63f; evidence/restart_commit_audit.txt — ancestor of main; process started 05.10 | — | — | — | — | — |
| <a id="t071"></a>71 | L112 | Нет проверки, что дашборд вообще инициализируется. | FIXED | evidence/dashboard_initialization.txt — test_no_js_errors passed; tests/test_frontend.py:1018-1028 | — | — | — | — | — |
| <a id="t072"></a>72 | L113 | merge_worker в состоянии PENDING читается агентами как провал, потому что объяснен… | OPEN-DEFECT | 71a008fe:TODO.md:L112 (PENDING result rendering incident) | Merge status delivery | S | да | нет | да |
| <a id="t073"></a>73 | L114 | merge_worker отбивал 409 SESSION_IDENTITY_CHANGED в цикле, из которого нет выхода… | FIXED | .orchestra/tasks/V-575/report.md (recorded in 71a008fe:TODO.md:L114) | — | — | — | — | — |
| <a id="t074"></a>74 | L115 | Красный на main, не связан с правками фронта: tests/test_frontend.py::test_photo_b… | FIXED | evidence/red_chat_photo_gallery.txt — 1 passed | — | — | — | — | — |
| <a id="t075"></a>75 | L116 | __pycache__ под .orchestra/ не игнорируется: правило-исключение перебивает общий ш… | OPEN-DEFECT | evidence/orchestra_pycache_ignored.txt — .gitignore:26 excludes .orchestra/** | Git ignore rules | S | нет | нет | да |
| <a id="t076"></a>76 | L117 | Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит — ПОЧИНЕНО #V-5… | FIXED | .orchestra/tasks/V-582/report.md (recorded in 71a008fe:TODO.md:L117) | — | — | — | — | — |
| <a id="t077"></a>77 | L118 | ИЗУЧИТЬ: два приёма приёмки из cloudflare/security-audit-skill — годятся ли они на… | NOTE | 71a008fe:TODO.md:L118 (original detailed record) | — | — | — | — | — |
| <a id="t078"></a>78 | L119 | РЕСЕРЧ: можно ли перебирать стратегии оркестрации по своей истории, как Dream-RSI… | NOTE | 71a008fe:TODO.md:L119 (original detailed record) | — | — | — | — | — |
| <a id="t079"></a>79 | L120 | Наша история мержей — готовый источник правил для промптов, и мы его ни разу не вы… | NOTE | 71a008fe:TODO.md:L120 (original detailed record) | — | — | — | — | — |
| <a id="t080"></a>80 | L121 | merge_worker(task_outcome="continue") — ловушка: прогон задачи остаётся открытым,… | OPEN-DEFECT | 71a008fe:TODO.md:L121; repeated as item 154 at L225 | Worker/task lifecycle | M | да | да | нет |
| <a id="t081"></a>81 | L122 | Astra недоступна нашему аккаунту, но остаётся маршрутом по умолчанию для сложных з… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t082"></a>82 | L123 | ЖДЁТ РЕСТАРТА ВЛАДЕЛЬЦА — семь готовых правок и два мёртвых воркера (на 12.09.2026). | FIXED | evidence/restart_commit_audit.txt — all seven changes are in main before 05.10 process start | — | — | — | — | — |
| <a id="t083"></a>83 | L124 | Тест-гейт мержа гоняет тесты в ВЕТКЕ ВОРКЕРА, а исправление красноты лежит в main… | NOTE | commit f5713f4d (recorded in 71a008fe:TODO.md:L124) | — | — | — | — | — |
| <a id="t084"></a>84 | L125 | Горячая правка .env для квоты в боевом процессе НЕ работала — ИСПРАВЛЕНО fbc9e40d,… | FIXED | commit fbc9e40d (recorded in 71a008fe:TODO.md:L125) | — | — | — | — | — |
| <a id="t085"></a>85 | L126 | Квотные переменные оператора надо гасить ДО импорта app, а не в фикстуре. | FIXED | commit 52f7c97d (recorded in 71a008fe:TODO.md:L126) | — | — | — | — | — |
| <a id="t086"></a>86 | L127 | merge_worker падал «cannot derive target-relative merge paths» из-за детектора пер… | FIXED | commit bec4f378 (recorded in 71a008fe:TODO.md:L127) | — | — | — | — | — |
| <a id="t087"></a>87 | L128 | Красный на main, не связан с #V-546: tests/test_merge_test_gate.py::test_browser_i… | FIXED | evidence/red_merge_gate_inventory.txt — 1 passed | — | — | — | — | — |
| <a id="t088"></a>88 | L129 | tests/test_work_acceptance.py::test_failed_acceptance_still_blocks_new_work_withou… | FIXED | evidence/red_acceptance_path.txt — 1 passed | — | — | — | — | — |
| <a id="t089"></a>89 | L130 | P1. Картинка тяжелее 10 МБ не доходит в Telegram и роняет весь альбом — ПОЧИНЕНА в… | FIXED | .orchestra/tasks/V-544/report.md (recorded in 71a008fe:TODO.md:L130) | — | — | — | — | — |
| <a id="t090"></a>90 | L131 | P1 (остаток от #V-544). PHOTO_INVALID_DIMENSIONS размером не ловится. | OPEN-DEFECT | 71a008fe:TODO.md:L131; current file-delivery path noted there | Telegram file delivery | M | да | да | да |
| <a id="t091"></a>91 | L132 | #V-544 ждёт офлайн-миграции живой БД (действие владельца). | FIXED | evidence/live_state_readonly.txt — live tg_file_deliveries CHECK allows 2097152000 bytes; no 52428800 limit | — | — | — | — | — |
| <a id="t092"></a>92 | L133 | Потолок документа через локальный Bot API ИЗМЕРЕН (#V-544, 11.09.2026): | FIXED | .orchestra/tasks/V-544/control-run-200mb.txt (recorded in 71a008fe:TODO.md:L133) | — | — | — | — | — |
| <a id="t093"></a>93 | L134 | P1. Утечка pidfd — ПОЧИНЕНА в коде (#V-543, коммит 180a5a4f), в живом процессе при… | FIXED | commit 180a5a4f (recorded in 71a008fe:TODO.md:L134) | — | — | — | — | — |
| <a id="t094"></a>94 | L138 | P2. Бакет anthropic_fable собирается, но недостижим — Fable-воркеры гейтятся по чу… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t095"></a>95 | L139 | merge_worker рапортует SUCCEEDED при мерже ветки В САМУ СЕБЯ и нулевом переносе ко… | OPEN-DEFECT | 71a008fe:TODO.md:L139; merge_worker target/commit outcome reproduction | Worker lifecycle / git state | L | да | да | да |
| <a id="t096"></a>96 | L140 | switch_worker_branch не атомарен: ветку переключает, привязку теряет | OPEN-DEFECT | 71a008fe:TODO.md:L140; switch_worker_branch failure case | Worker lifecycle / git state | L | да | да | да |
| <a id="t097"></a>97 | L141 | stop_worker рапортует «interrupted and set to idle», не остановив ход | OPEN-DEFECT | 71a008fe:TODO.md:L141; stop_worker completion case | Worker lifecycle / git state | L | да | да | да |
| <a id="t098"></a>98 | L142 | Рестарт оставляет Codex-тред с открытым писателем и сессию в RUNNING, которого нет… | OPEN-DEFECT | app/backend_codex.py:376; app/session.py:1994 | Codex restart recovery | L | да | да | нет |
| <a id="t099"></a>99 | L143 | Отказ session has no bound task не различает две ситуации. | OPEN-DEFECT | app/tm.py:1432 | Task API errors | S | да | нет | да |
| <a id="t100"></a>100 | L144 | Потолок MAX_DIFF_INSERTIONS = 2000 (app/diff_budget.py:16) не различает код и ресё… | NEEDS-OWNER | 71a008fe:TODO.md:L144 (original detailed record) | — | — | — | — | — |
| <a id="t101"></a>101 | L145 | У воркера, упёршегося в потолок диффа, нет легального выхода | OPEN-DEFECT | app/diff_budget.py:16; 71a008fe:TODO.md:L145 | Diff budget / worker recovery | M | да | да | да |
| <a id="t102"></a>102 | L146 | Прямые коммиты оркестратора в main не привязываются к задачам. | NEEDS-OWNER | 71a008fe:TODO.md:L146 (original detailed record) | — | — | — | — | — |
| <a id="t103"></a>103 | L147 | Исчерпанная квота Codex даёт пустое падение вместо внятной ошибки | OPEN-DEFECT | app/backend_codex.py:1379,1963; 71a008fe:TODO.md:L147 | Codex quota errors | M | да | нет | да |
| <a id="t104"></a>104 | L148 | Мелкие замечания ревью аудита 01.09, не закрытые в трёх раундах | OPEN-DEFECT | app/routes/system.py:2414; app/limit_wake.py:44; app/message_deliveries.py:70 | Usage/quota subsystem | L | да | нет | да |
| <a id="t105"></a>105 | L151 | Наш компакт физически не может опередить клишный: он запрещён во время хода, а кон… | NEEDS-OWNER | 71a008fe:TODO.md:L151 (original detailed record) | — | — | — | — | — |
| <a id="t106"></a>106 | L152 | Событие клишного компакта разбирается по НЕ ТОМУ регистру ключей — в журнале всегд… | FIXED | app/backend_claude.py:1494-1498 accepts compact_metadata snake_case and legacy camelCase | — | — | — | — | — |
| <a id="t107"></a>107 | L155 | RAG-бэкфилл на merge_worker ненадёжен | NOTE | 71a008fe:TODO.md:L155 (original detailed record) | — | — | — | — | — |
| <a id="t108"></a>108 | L156 | Устаревшие копии скиллов в Claude-worktree | OPEN-DEFECT | 71a008fe:TODO.md:L156 (worktree copy behavior; stale skill report) | Worktree prompt sync | M | да | нет | да |
| <a id="t109"></a>109 | L157 | TG media buffer race | OPEN-DEFECT | app/tg_bridge.py:625; tests/test_audit0901_tg.py:99-125 | Telegram media delivery | M | да | нет | да |
| <a id="t110"></a>110 | L158 | TG дубли expandable+image | OPEN-DEFECT | 71a008fe:TODO.md:L158 (duplicate renderer paths) | Telegram media delivery | M | да | нет | да |
| <a id="t111"></a>111 | L159 | Pending tm_sync_log без fire в CLI-контексте | OPEN-DEFECT | 71a008fe:TODO.md:L159 (_fire_sync pending-write case) | Task sync bookkeeping | M | да | да | да |
| <a id="t112"></a>112 | L160 | Тест-изоляция: test_default_equals_upstream загрязняет 106 тестов | NOTE | 71a008fe:TODO.md:L160 (original detailed record) | — | — | — | — | — |
| <a id="t113"></a>113 | L161 | График usage: ~161 законный ноль не рисуется | OPEN-DEFECT | 71a008fe:TODO.md:L161; .orchestra/tasks/150/report.md | Usage chart | M | да | нет | да |
| <a id="t114"></a>114 | L162 | tests/test_frontend.py | OPEN-DEFECT | tests/test_frontend.py: (assertion named at 71a008fe:TODO.md:L162) | Frontend test oracle | S | нет | нет | да |
| <a id="t115"></a>115 | L163 | Панель «Context» справа застывает на значении момента выбора агента | OPEN-DEFECT | app/static/js/app.js:2603,2862-2918,3216 | Context panel | M | нет | нет | да |
| <a id="t116"></a>116 | L166 | Номера задач пересекаются между контурами | NEEDS-OWNER | 71a008fe:TODO.md:L166 (original detailed record) | — | — | — | — | — |
| <a id="t117"></a>117 | L167 | 32 коммита VPS не публиковались в origin | NEEDS-OWNER | 71a008fe:TODO.md:L167 (original detailed record) | — | — | — | — | — |
| <a id="t118"></a>118 | L168 | 21 задача на паузе у спящих воркеров | NEEDS-OWNER | 71a008fe:TODO.md:L168 (original detailed record) | — | — | — | — | — |
| <a id="t119"></a>119 | L169 | Личные скиллы из ~/.claude/skills в пайплайн | NEEDS-OWNER | 71a008fe:TODO.md:L169 (original detailed record) | — | — | — | — | — |
| <a id="t120"></a>120 | L170 | Grok: включать ли в pipeline.yaml роль. | NEEDS-OWNER | 71a008fe:TODO.md:L170 (original detailed record) | — | — | — | — | — |
| <a id="t121"></a>121 | L173 | #436 — жизненный цикл ревью пишется полями, а не восстанавливается из прозы (заказ… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t122"></a>122 | L174 | Из того же разбора #435, к работе НЕ ведёт, но переспрашивать не надо: сравнить Lu… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t123"></a>123 | L175 | Dynamic Workflows в Оркестре: v0 = wf_run (вариант A), затем quota-роутер из LaneB… | FIXED | commit 360c846b; scripts/wf_run.py:1 | — | — | — | — | — |
| <a id="t124"></a>124 | L176 | Семь красных тестов карты квот на main | FIXED | evidence/quota_map_api.txt — 17 passed; evidence/red_quota_frontend_files.txt — 51 passed | — | — | — | — | — |
| <a id="t125"></a>125 | L177 | Раздробить app.js | NOTE | 71a008fe:TODO.md:L177 (original detailed record) | — | — | — | — | — |
| <a id="t126"></a>126 | L178 | merge_worker показывать diff | NOTE | 71a008fe:TODO.md:L178 (original detailed record) | — | — | — | — | — |
| <a id="t127"></a>127 | L179 | Sound notification on idle | NOTE | 71a008fe:TODO.md:L179 (original detailed record) | — | — | — | — | — |
| <a id="t128"></a>128 | L180 | TG verbosity | NOTE | 71a008fe:TODO.md:L180 (original detailed record) | — | — | — | — | — |
| <a id="t129"></a>129 | L181 | VPS parsing cost guard | NOTE | 71a008fe:TODO.md:L181 (original detailed record) | — | — | — | — | — |
| <a id="t130"></a>130 | L184 | Озвучка роликов через ElevenLabs: отложено, «как дойдут руки, чтобы качественно бы… | NEEDS-OWNER | .orchestra/tasks/V-694/report.md (recorded in 71a008fe:TODO.md:L184) | — | — | — | — | — |
| <a id="t131"></a>131 | L185 | Codex как streaming tool | NOTE | 71a008fe:TODO.md:L185 (original detailed record) | — | — | — | — | — |
| <a id="t132"></a>132 | L186 | Cross-server messaging | NOTE | 71a008fe:TODO.md:L186 (original detailed record) | — | — | — | — | — |
| <a id="t133"></a>133 | L187 | Best-of-N solving | NOTE | 71a008fe:TODO.md:L187 (original detailed record) | — | — | — | — | — |
| <a id="t134"></a>134 | L189 | При следующем рестарте: переназначить sessions.parent_name ТРЁМ воркерам seedon | FIXED | evidence/live_state_readonly.txt — all three seedon rows have parent_name=seedon-orchestrator | — | — | — | — | — |
| <a id="t135"></a>135 | L191 | Залипшая merge-операция 8503eb08-ada9-401f-8ddf-034a601cd60c (skillstate-bench, #4… | NOTE | commit 8503eb08 (recorded in 71a008fe:TODO.md:L191) | — | — | — | — | — |
| <a id="t136"></a>136 | L193 | bg_create(type="run") НЕ переживает рестарт, хотя описание тула это обещает. | NOTE | commit 44411585 (recorded in 71a008fe:TODO.md:L193) | — | — | — | — | — |
| <a id="t137"></a>137 | L195 | Текст ошибки task #N has multiple session bindings вводит в заблуждение | NOTE | 71a008fe:TODO.md:L195 (original detailed record) | — | — | — | — | — |
| <a id="t138"></a>138 | L197 | ConcurrentTaskUpdateError при параллельной записи канона НЕ чинится в #426 — план… | OPEN-DEFECT | 71a008fe:TODO.md:L197 (ConcurrentTaskUpdateError evidence) | Canonical task finalization | L | да | да | нет |
| <a id="t139"></a>139 | L199 | Antigravity как пятый рантайм — технически можно, юридически НЕЛЬЗЯ (#506, 03.09). | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t140"></a>140 | L200 | Побочные находки #506, если тема вернётся: | OBSOLETE | .orchestra/pipelines/default/prompts/modules/model-routing.md:4-5,16-18,28-29 (model ban / route policy) | — | — | — | — | — |
| <a id="t141"></a>141 | L202 | Оставшиеся вопросы из #507 требуют отдельного обсуждения: | NEEDS-OWNER | commit 20260909 (recorded in 71a008fe:TODO.md:L202) | — | — | — | — | — |
| <a id="t142"></a>142 | L203 | Общего фильтра live tool results у нас нет (#507). | NEEDS-OWNER | 71a008fe:TODO.md:L203 (original detailed record) | — | — | — | — | — |
| <a id="t143"></a>143 | L204 | Что из #507 подтвердилось в НАШУ пользу, не переделывать: | NOTE | 71a008fe:TODO.md:L204 (original detailed record) | — | — | — | — | — |
| <a id="t144"></a>144 | L206 | Внешний отзыв на Gemini 3.8 Flash и Antigravity (03.09, канал sh/ИИ, посты 1292–12… | NOTE | 71a008fe:TODO.md:L206 (original detailed record) | — | — | — | — | — |
| <a id="t145"></a>145 | L207 | DeepSWE как бенчмарк скомпрометирован (тот же источник, 03.09): | NOTE | 71a008fe:TODO.md:L207 (original detailed record) | — | — | — | — | — |
| <a id="t146"></a>146 | L210 | migrate_orchestra_layout.py --repair НЕ чинит смешанное состояние, а отсылает сам… | OPEN-DEFECT | scripts/migrate_orchestra_layout.py; 71a008fe:TODO.md:L210 | Layout migration tools | M | нет | да | нет |
| <a id="t147"></a>147 | L211 | check_orchestra_paths.py падает на контуре с чужой историей и не даёт третий крите… | OPEN-DEFECT | scripts/check_orchestra_paths.py; 71a008fe:TODO.md:L211 | Layout migration tools | M | нет | да | нет |
| <a id="t148"></a>148 | L213 | Отказ гейта воркеру не оставлять голым отказом: называть Луну (замер seedon, 03.09). | NOTE | 71a008fe:TODO.md:L213 (original detailed record) | — | — | — | — | — |
| <a id="t149"></a>149 | L215 | Ревью-гейт мержа (#462, приехал с ноутбука 04.09) блокирует одобренную работу, есл… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t150"></a>150 | L217 | Мост МОЛЧА глотает сообщения из темы, не привязанной ни к одному агенту — владелец… | OPEN-DEFECT | app/tg_bridge.py; 71a008fe:TODO.md:L217 (five-message incident) | Telegram topic routing | M | да | да | да |
| <a id="t151"></a>151 | L219 | codex_review(mode="implementation") жёстко подставляет "main", когда у вызывающего… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t152"></a>152 | L221 | Миграция раскладки docs/ → .orchestra/ (03.09) сломала замороженные тесты, которые… | NEEDS-OWNER | .orchestra/tasks/2/ (recorded in 71a008fe:TODO.md:L221) | — | — | — | — | — |
| <a id="t153"></a>153 | L223 | POST_COMMIT_PARTIAL / ConcurrentTaskUpdateError: canonical head changed при мерже,… | OPEN-DEFECT | 71a008fe:TODO.md:L223 (POST_COMMIT_PARTIAL reproduction) | Canonical task finalization | L | да | да | нет |
| <a id="t154"></a>154 | L225 | Тупик привязки: merge_worker(task_outcome="continue") у legacy-клиента оставляет О… | OPEN-DEFECT | 71a008fe:TODO.md:L225; same task-run issue as item 80 | Worker/task lifecycle | M | да | да | нет |
| <a id="t155"></a>155 | L227 | Детектор «слепого ревью» судит по СОДЕРЖИМОМУ текста и объявляет состоявшееся ревь… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t156"></a>156 | L229 | Красный тест на main (HEAD 7fb6dc66): отказ смены модели теряет машинный код причи… | FIXED | evidence/handoff_effect_classification.txt — 11 passed; old node id no longer exists | — | — | — | — | — |
| <a id="t157"></a>157 | L231 | Из ресёрча #508 (артефакт .orchestra/tasks/508/research.md, прочитан целиком) — то… | NOTE | .orchestra/tasks/508/research.md (recorded in 71a008fe:TODO.md:L231) | — | — | — | — | — |
| <a id="t158"></a>158 | L239 | Метод: полнотекстовый поиск по logs.content считает СВОЁ ЖЕ расследование за случа… | NOTE | .orchestra/kb/evidence-methods.md:79-86 (measurement and interpretation) | — | — | — | — | — |
| <a id="t159"></a>159 | L241 | Штатный путь «смержил → просто напиши воркеру новую задачу» ведёт прямо в отказ 40… | OPEN-DEFECT | app/routes/sessions.py:2338; 71a008fe:TODO.md:L241 | Task API errors | S | да | нет | да |
| <a id="t160"></a>160 | L243 | /tmp (tmpfs 7.7 ГБ) забивается артефактами агентов до 100% и рвёт ВЫВОД инструмент… | NOTE | .orchestra/kb/evidence-methods.md:88-96 (measurement and limits) | — | — | — | — | — |
| <a id="t161"></a>161 | L245 | Миграция раскладки 03.09 осиротила ~18 веток: у каждой внутри СВОЯ копия переезда… | NEEDS-OWNER | .orchestra/tasks/450/codex-review-impl.md (recorded in 71a008fe:TODO.md:L245) | — | — | — | — | — |
| <a id="t162"></a>162 | L247 | app/knowledge_pipeline.py лежит в main БЕЗ вызывающих и без тестов, но с взведённы… | OBSOLETE | commit 9a1735f1695519a445f393802c2154bd37337e38 deletes app/knowledge_pipeline.py | — | — | — | — | — |
| <a id="t163"></a>163 | L249 | Убийство воркера НЕ удаляет его домашний каталог CLI — за месяц это 12.7 ГБ на сис… | FIXED | app/manager.py:1180,1199-1200 removes archived session managed home | — | — | — | — | — |
| <a id="t164"></a>164 | L251 | codex_review(target_worker=…) в режиме implementation рождает квитанцию, которую н… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t165"></a>165 | L253 | Гейт kill_worker считает КОММИТЫ, а не содержимое, и поэтому требует force там, гд… | NEEDS-OWNER | 71a008fe:TODO.md:L253 (original detailed record) | — | — | — | — | — |
| <a id="t166"></a>166 | L255 | Два теста на main красные и это не чужая ветка. | FIXED | evidence/red_chat_reserved_slot.txt — 1 passed; evidence/merge_operation_replay.txt — 1 passed | — | — | — | — | — |
| <a id="t167"></a>167 | L257 | reconcile_legacy_tasks роняет СТАРТ всего сервиса при рассинхроне идентификаторов… | OBSOLETE | commit eda5417930f8 (recorded in 71a008fe:TODO.md:L257) | — | — | — | — | — |
| <a id="t168"></a>168 | L259 | Потолок корневых инструкций всё ещё пробит — на 657 байт, и это уже не про KB. | FIXED | evidence/root_instruction_size.txt — 12662 bytes, below 16 KiB | — | — | — | — | — |
| <a id="t169"></a>169 | L261 | bg_create(type="run") не принимает cwd и запускает команду из каталога СЕРВЕРА, по… | OPEN-DEFECT | app/bg_jobs.py:1054-1058; referenced .orchestra/tasks/57/baseline-cancel.log is absent from Git history | Background jobs / cwd | M | да | да | нет |
| <a id="t170"></a>170 | L263 | Кэш состояний Codex рос без ограничения и без уборки; 06.09 вычищено 102 ГБ, но ме… | FIXED | app/manager.py:1180,1199-1200 (remove archives session and cleans its managed home) | — | — | — | — | — |
| <a id="t171"></a>171 | L265 | Рестарт Orchestra МАССОВО оставляет треды Codex с залипшим писателем, и повторные… | OPEN-DEFECT | app/backend_codex.py:376; 71a008fe:TODO.md:L265 | Codex restart recovery | L | да | да | нет |
| <a id="t172"></a>172 | L267 | Развилка #504 T4 ждёт владельца: классификатор «НЕ ВЫПОЛНЕНО» по XML-подобной проз… | NEEDS-OWNER | .orchestra/tasks/504/review-implementation.md (recorded in 71a008fe:TODO.md:L267) | — | — | — | — | — |
| <a id="t173"></a>173 | L269 | Ветка с готовой работой протухает быстрее, чем её успевают принять, и «почему ворк… | NOTE | 71a008fe:TODO.md:L269 (original detailed record) | — | — | — | — | — |
| <a id="t174"></a>174 | L271 | ЗАКРЫТО ЧАСТИЧНО #536 (08.09, коммит 4f87cecc): залипший писатель теперь ВИДЕН и д… | OPEN-DEFECT | app/backend_codex.py:376; app/session.py:1994; 71a008fe:TODO.md:L271 | Codex restart recovery | L | да | да | нет |
| <a id="t175"></a>175 | L273 | Парсер находок ревью не понимает формат, который пишет наш собственный ревьюер, —… | OBSOLETE | .orchestra/pipelines/default/prompts/modules/orchestration.md:82-89 (model review frozen) | — | — | — | — | — |
| <a id="t176"></a>176 | L275 | Провал send_message ГЛУШИТ авто-репорт: результат воркера лежит в логах и не доход… | OPEN-DEFECT | 71a008fe:TODO.md:L275 (send_message failure and missing recipient) | Worker result delivery | M | да | да | да |
| <a id="t177"></a>177 | L277 | Красные тесты test_manager.py были не дефектом кода, а протёкшей переменной окруже… | FIXED | tests/conftest.py:87-99 clears ORCHESTRA_TASK_PREFIX in autouse test isolation | — | — | — | — | — |
| <a id="t178"></a>178 | L279 | Третья протечка env в тесты: QUOTA_GATED_LANES=claude красит 12 тестов гейта. | FIXED | tests/conftest.py:29-34 clears quota environment before importing app | — | — | — | — | — |
| <a id="t179"></a>179 | L281 | Права в /api/sessions/{name}/message включаются полем ТЕЛА запроса, поэтому отключ… | OPEN-DEFECT | app/routes/sessions.py:1010-1013 | Message authorization | L | да | да | да |
| <a id="t180"></a>180 | L283 | Замер «горел ли кеш» и контрольная точка для проверки эффекта #V-540. | NOTE | commit 20260908 (recorded in 71a008fe:TODO.md:L283) | — | — | — | — | — |
| <a id="t181"></a>181 | L285 | Наша телеметрия квот выбрасывает всё, кроме двух старых полей, — поэтому отдельног… | NEEDS-OWNER | 71a008fe:TODO.md:L285 (original detailed record) | — | — | — | — | — |
| <a id="t182"></a>182 | L287 | Строка tm_projects с id orchestra указывает НЕ на тот проект, который имеет в виду… | OPEN-DEFECT | .orchestra/tasks/V-576/namespace-map.md (recorded in 71a008fe:TODO.md:L287) | Task/catalog model | M | да | да | нет |
| <a id="t183"></a>183 | L289 | portfolio_attention_events.delivered_at не пишется НИКОГДА, хотя таблица заводилас… | OBSOLETE | commit de5d62a523ca678e666c5bd03f97519bdf73b338 removes portfolio_attention_events in V-576 | — | — | — | — | — |
| <a id="t184"></a>184 | L291 | Снимок истории чата грузится целиком при каждом переключении, потому что у /api/se… | OPEN-DEFECT | app/routes/sessions.py:713-720 (GET logs sets Cache-Control: no-store) | Chat snapshot transfer | M | да | нет | да |
| <a id="t185"></a>185 | L293 | Значок темы в Telegram залипает на «выполняет ход» после рестарта: агент простаива… | OPEN-DEFECT | app/tg_bridge.py:3025-3036; 71a008fe:TODO.md:L293 | Telegram topic status | S | да | нет | да |
| <a id="t186"></a>186 | L295 | Lite-профиль инструментов по ролям: воркер получает только то, что ему разрешено (… | NOTE | 71a008fe:TODO.md:L295 (original detailed record) | — | — | — | — | — |
| <a id="t187"></a>187 | L297 | Ресерч на потом: забрать из харнеса MiniMax Code сторож зацикливания и динамически… | NOTE | 71a008fe:TODO.md:L297 (original detailed record) | — | — | — | — | — |
| <a id="t188"></a>188 | L299 | На изучение: разделение труда «дешёвый исполнитель кликает, модель думает» в брауз… | NOTE | .orchestra/tasks/V-584/audit_screens.py (recorded in 71a008fe:TODO.md:L299) | — | — | — | — | — |
| <a id="t189"></a>189 | L301 | На изучение: Ouroboros (Q00/ouroboros) — прямой аналог Orchestra, у которого стоит… | NOTE | 71a008fe:TODO.md:L301 (original detailed record) | — | — | — | — | — |
| <a id="t190"></a>190 | L307 | Jev (TypeSafe System One) — где он у нас применим, с ценой по нашим объёмам (разве… | NOTE | 71a008fe:TODO.md:L307 (original detailed record) | — | — | — | — | — |
| <a id="t191"></a>191 | L317 | Серии одинаковых вызовов инструментов: это НЕ наш харнес и не совсем «одинаковые»… | NOTE | .orchestra/kb/runtimes.md:125-133 (measurement and corrected grouping) | — | — | — | — | — |
| <a id="t192"></a>192 | L319 | Ресёрч: SoL-Pi (NVlabs) — автоматический подбор обвязки агента, заявлено −45…49% т… | NOTE | 71a008fe:TODO.md:L319 (original detailed record) | — | — | — | — | — |
| <a id="t193"></a>193 | L321 | Ресёрч: Laya — локальная замена Jev для типизированных решений (прислано 21.09.2026). | NOTE | 71a008fe:TODO.md:L321 (original detailed record) | — | — | — | — | — |
| <a id="t194"></a>194 | L323 | Красный на main: tests/test_model_catalog_frontend.py::test_catalog_free_filter_an… | FIXED | evidence/red_model_catalog_frontend.txt — 1 passed | — | — | — | — | — |
| <a id="t195"></a>195 | L325 | 37 браузерных тестов и tests/test_audit0901_sysquota.py::test_lane_label_prints_th… | FIXED | evidence/red_quota_frontend_files.txt — 51 passed; evidence/red_sysquota_label.txt — 1 passed | — | — | — | — | — |
| <a id="t196"></a>196 | L327 | После V-653 миграция V-576 создаёт attention_events и на существующей базе v3, есл… | FIXED | evidence/startup_migration_attention_events.txt — 1 passed | — | — | — | — | — |

## Счёт

| Вердикт | Пунктов |
|---|---:|
| FIXED | 44 |
| OBSOLETE | 27 |
| OPEN-DEFECT | 47 |
| NEEDS-OWNER | 28 |
| NOTE | 50 |
| **Всего** | **196** |

Fresh targeted checks used `/home/kesha/orchestra/.venv/bin/python -m pytest`; no code or test files were changed.
