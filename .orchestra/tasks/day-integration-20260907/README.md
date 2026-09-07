# Итоговая интеграция своих работ за 7 сентября 2026

Разрешение владельца: «все мержи все свои штуки», сохранить исследования/примеры в Git.
Про дефекты квитанций запрос — объяснить, а не реализовать все исправления. Диагностика
Opera/codex_apps прекращена по явному указанию владельца.

## Что интегрировано

- Ранее в main: ac6a0a30 и 460b3b30 — единый html-artifacts, доступ пяти ролям,
  глобальная установка и архив старых дизайнов. Канонический HTML-скилл сохранён без
  возврата старой типографики, ELI5 и других конкурирующих требований.
- codex/design-skill-gallery, исходный f2752e8d → 55b4b737: ограничение codex_review
  исполнителями, все режимы и resume; запрет target_worker; сохранность принятия и skip.
  Источники и самостоятельные HTML двух галерей сохранены. Прежняя добавка favicon в
  старый HTML-скилл уже поглощена более новым единым скиллом и повторно не применяется.
- codex/receipt-system-audit, исходный 3d05bfbd → f6ee9e61: исследование, воспроизведения,
  проверки и исторический HTML. Отчёты сохраняют дату и границы того исследования.
- codex/html-artifacts-unified, исходный cb0b71e9 → 59c0ac4e: проверка источников harness
  engineering, применимость и диагностика MCP. Приватные конфиги/backup в Git не попали.
- Новая схема review-tools.html: инструменты, владельцы, автоматические записи, смысл
  состояний и список того, что чинить. Основная информация видна сразу; есть наведение.

Исходные ветки оставлены, их рабочие деревья чистые. Cherry-pick выбран для переноса только
своих изменений поверх актуального main 5d1e440e. Конфликты pipeline, HTML-скилла и теста
набора skills разрешены с сохранением нового единого дизайна и удалением codex-debate
только у orchestrator/sub-orchestrator. Чужие коммиты и ветки не изменялись.

## Где примеры теперь хранятся в Git

- .orchestra/tasks/design-skill-gallery/gallery.html — первая галерея, включая её примеры.
- .orchestra/tasks/design-iteration-2/example.html — принятая вторая версия с динамикой и favicon.
- .orchestra/tasks/receipt-audit/audit-v1.html — историческая первая карта аудита.
- .orchestra/tasks/day-integration-20260907/review-tools.html — новое объяснение инструментов.

Three.js сохранён с MIT-лицензией как зависимость исходников; конечные HTML самостоятельны.
Сырые страницы, браузерные дампы, приватные skill-source выгрузки и снимки рабочего стола
не добавлялись. Старые шаблоны в первой галерее — её исторические исходные превью, а не
принятый стиль или новые активные скиллы.

## Проверки

417 passed in 18.23s, stdout — tests.txt. Прогон через
/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest, nice=15, MemoryMax=2G.
Импортируемый app: /mnt/data/Projects/Python/orchestra-day-20260907/app/.

Файлы: test_review_requester_roles, test_mcp_codex_review, test_default_pipeline,
test_check_pipeline_manifest, test_codex_review_sandbox, test_mcp_stdio,
test_project_context_review_488, test_review_coverage_gate_462, test_review_receipt_start_436,
test_review_subject_absorbed_delta_509, test_unified_html_skill, test_prompting,
test_legacy_pipeline_skills, test_review_receipt_outcome_tool_436,
test_review_receipt_safety_436, test_review_receipt_storage_436,
test_review_receipt_terminal_436, test_review_authorship_493, test_codex_review_artifact.

Манифест и instruction contract прошли. Изолированы DB и внешние CLI; моделей для этого
прогона не запускали. Проверены secret-shaped строки в собственных новых текстовых
артефактах и diff. Full suite проекта не запускался; ранее установленные несвязанные
падения тестов миграции и фикстур не выдаются за исправленные.

Новый HTML проверен Playwright на 1440/390 px, наведение, отсутствие сетевых запросов и
JS-ошибок, встроенный SVG favicon; просмотрен скриншот, устранено пересечение подписи
с входящими стрелками. Результат — render-checks.json.

## Остаток

Пять дефектов из аудита не были задачей реализации: доказательство чтения, бюджет запусков,
подпись старых cross-worker квитанций, структурированные findings, миграция записей.
Отдельный запрет новых заказов оркестраторами не исправляет все эти дефекты.

Merge в main не перезапускает уже загруженный Python/MCP. Для действия нового кода
необходим обычный reconnect соответствующего MCP-процесса; сервисы самостоятельно
не перезапускались. Push и деплой на VPS не входят в это разрешение на merge.

Дополнение по ранее обнаруженному хвосту ELI5 на VPS: после проверки, что его уже нет в
пайплайне и native-копии не tracked, обе копии сохранены в
/home/kesha/.orchestra/skill-archive/stale-eli5-20260907T130237976759Z/ вне выдачи CLI.
