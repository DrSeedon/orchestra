# V-1257 — source recovery verified; broker import and activation pending

**606 passed**, один завершённый offline-прогон на фактических файлах текущей Hub-копии после реконструкции pipeline. Лог: recovery-final-check.log, exit 0, 29.47 s wall time (не замер производительности модели). Static pipeline check и Phase B dry-run — PASS. Живых вызовов модели, рестарта, merge, закрытия/архивации worker или смены модели этого hubsol worker не было.

## Что реализовано

Один маршрут `hub-gemini-4-argon` → `antigravity/gemini-4-argon` только для сохранённой роли `specialist` в default pipeline с существующими task/scope. Скоуп владельца 03.11.2026 14:52/15:31: дизайн, синтез/сравнение документов, финансовые/правовые рассуждения на публичном или синтетическом тексте. Обычная работа с терминалом/репозиторием остаётся на Sol; native Codex orchestration не меняется.

Канонический guard повторно проверяет идентичность при create/change/send/connect/start/recovery; backend читает её заново. Reason/name/tag и поля запроса не дают допуска. Та же specialist-инструкция доставляется на первом и последующих сокращённых Hub-ходах. Нет нового grant store, public permission schema, переноса старых работников/очередей или расширения до иных моделей. Сохранены privacy/file policy, ownership, история/recovery, shared Hub slots и provider-capacity admission. Unknown quota остаётся явно unknown по существующей политике, не означает доказанную ёмкость. Window=0 — unknown; модальности/цены не выдуманы; используется каталоговый effort high без неподтверждённого runtimeMode.

Funding разрешён владельцем на уровне задачи: существующий платный Hub pool без наших дополнительных списаний. Нет Google API/DostupAI/Carbon/overage/auxiliary image-model fallback. Видео/media/PDF ingestion, большой контекст, long-decode и Google-app integration не проверены в Hub и не объявлены поддерживаемыми. Публичная транскрипция — только текстовый вход. Model-review не тронут.

## Восстановление после частичного импорта

Последний **подтверждённый root/broker import HEAD**: `d95c5f733d354878115cb823ee94654cf6931c48`. Root main: `b9d893ec8babd4b2052ac1f497962e1966206bcb`. Прежний `e835` сохранён как переданный root короткий ref; полного SHA в этой копии нет. Это не новый успешный import HEAD.

Брокер не применил pipeline и четыре colleague-owned prompt-файла. Здесь все четыре уже побайтно равны точному current main; они **не переписывались**. Сохранённый delta pipeline заново применён к точному canonical b9 и структурно проверен: только новая specialist-role и три parent can_spawn. Canonical SHA `76240fd6d9b15ae1de739306c75f9f22bec6ab0db47adc59863c2dad6e1a2a16` → Phase A SHA `69af96dc84e32751257824e8cdbad493a63d9126e88d3268a304c132363a8df6`. Он совпал с оставшейся в Hub-копии старой Phase A; это **не доказывает**, что d95 на стороне root теперь содержит pipeline.

- recovery-against-d95.patch: ровно один отсутствующий source-файл, pipeline; четыре политики не затрагиваются.
- recovery-conflict-evidence.json: canonical/returned/final SHA всех пяти конфликтов. Если брокер вновь откажет идентичным canonical файлам, диагностировать границу импорта по этим SHA; importer state не правился, искусственных source-правок для принуждения импорта нет.
- phase-a-review.patch, phase-a-source-manifest.json, recovery-source-manifest.json: полный Phase A и заново проверенные SHA фактических 15 source/test/rule путей. Исторические версии сохранены отдельно.
- phase-b-specialist.patch: заново построен от фактического Phase A, dry-run пройден, **не применён**. В manifest остаётся известный Sol исключительно как activation stage.

## Проверки и границы результата

Provisioned `uv 0.11.28`, default `.venv`, `uv run --frozen python -m pytest` по 15 named paths, serial/nice=10/OOM=1000, offline/synthetic fixtures: **606 passed**, без изменения тестовых контрактов или guard. Тестовая Git identity существует только в окружении процесса. Полный репозиторный набор не запускался. Абсолютный импорт app проверен внутри workspace; безопасный относительный путь и hash абсолютного пути — в recovery-final-artifact-checks.log. Точные пути/команда и SHA исходников сохранены в recovery-source-manifest.json / recovery-final-check.log.

Старые 498 pre-expansion, 605+1 (fixture errors), debug и 124/таймауты сохранены как история, не доказательства этого восстановления. Из 16 исторических логов 15 остались byte-identical; в публичной копии phase-a-integration.log заменён один account path после закрепления original SHA/размера и приватной локальной ссылки d95:path в recovery-private-log-reference.json. Root должен проверить этот hash и держать d95/e835 локально/приватно; worker не переписывал Git history и не публиковал raw original. Старый полный отчёт — implementation-before-import-recovery.md. checks.log не переписывался, его SHA/размер зафиксированы, account paths в нём не найдены. История результатов и ошибок не скрыта.

Дальше root подтверждает **фактический импорт** recovery delta и делает complete-host checks. Затем normal owner idle watcher активирует Python, root проверяет live registry и лишь после этого применяет Phase B. Один новый task-bound admitted specialist smoke с маленьким безопасным HTML/CSS/SVG файлом — после активации. Никаких live миграций или retarget этого worker. До smoke рабочий Gemini/file transport не подтверждён; качество модели и видео этим прогоном не измерялись.

Нового imported HEAD ещё нет в доступных worker данных: private copy без `.git`, commit/import выполняет broker после хода и сообщает фактический HEAD. Ни main, ни d95/e835/history не переписывались. Задача не объявляется полностью завершённой/влитой/активированной по одному worker-прогону.
