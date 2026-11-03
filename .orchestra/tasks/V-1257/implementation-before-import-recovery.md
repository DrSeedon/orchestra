# V-1257 — Phase A ready for root review; activation/smoke pending

Учтены решения владельца 03.11.2026 14:52 и 15:31. Реализован один ограниченный маршрут `hub-gemini-4-argon` → Hub `antigravity/gemini-4-argon`, только для новой роли `specialist` в default pipeline с существующими task/scope. Скоуп: дизайн, синтез/сравнение документов, финансовые и правовые рассуждения на публичном или синтетическом тексте. Обычная работа с терминалом/репозиторием остаётся на Sol; native Codex orchestration не изменена. Это не заявление о работающем Gemini до активации.

- Один канонический guard проверяет сохранённую/current role/task/pipeline/scope при создании, смене модели, доставке, connect/start/send и восстановлении; backend перечитывает текущую идентичность. Имя, reason, tag или payload change-model не дают разрешения. Старый `designer` и обычные worker-роли не получают Argon.
- Та же specialist-инструкция доходит до сокращённого Hub-промпта на первом и каждом последующем ходе. Нет нового grant store, публичной permission schema, миграции очередей/работников, смены модели этого worker или расширения до других моделей.
- Сохранены task ownership, privacy/file policy, история/recovery и общий лимит Hub-ходов. Antigravity включён в существующий capacity gate: измеренное исчерпание блокирует; отсутствующая телеметрия видна как unknown и проходит по существующей политике #227. Это не доказательство доступной квоты.
- Источник оплаты разрешён владельцем на уровне задачи: имеющийся платный Hub pool без наших дополнительных списаний. Нет Google API, DostupAI, Carbon, purchased overage, Nano Banana/auxiliary image generator или другого платного fallback.
- Метаданные окна/модальностей/цены не выдуманы: window=0 означает unknown для Hub, modalities не объявлены, цены отсутствуют. Effort high проверяется по живому каталогу; Antigravity не получает неподтверждённый runtimeMode. Видео, image/audio/PDF ingestion, большой контекст, long-decode и Google-app integration остаются непроверенными в Hub. Публичная транскрипция — текстовый вход, не проверенный просмотр видео.

## Реальная проверка

Использован только provisioned `uv 0.11.28`, `uv run --frozen python -m pytest`, default `.venv`, offline/synthetic fixtures. Параллельных тестовых процессов не было; nice=10, OOM score=1000. Фиктивная Git identity задавалась только окружению тестового процесса для его временного task store; учётные записи/config не менялись.

| Проверка | Фактический результат | Артефакт |
|---|---|---|
| Финальный новый specialist-набор | **68 passed**, 14.71 s; включая исправленный durable queue case | phase-a-role-verified.log |
| Расширенный routing/pipeline/privacy/history набор | 605 passed, 1 ошибка собственной fixture (перепутан return tuple); исправлена и затем проверена новым набором | phase-a-specialist-verified.log |
| Последующие общие повторные прогоны | Не завершены: общий timeout 55 s, exit 124; зелёный итог им не присваивается | phase-a-release-check.log, phase-a-remaining-verified.log |
| Pipeline static check | PASS (`scripts/check_pipeline_manifest.py --check`) | pipeline-static-check.log |
| Phase B patch | PASS, dry-run без применения | phase-b-patch-check.log |

Промежуточные красные проверки/ошибки fixture и холодного импорта сохранены в implementation-notes.md и логах. Замороженные Sol-only acceptance не изменялись. Полный репозиторный набор и реальный Gemini smoke не запускались; общего финального зелёного прогона всех 606 cases одним запуском нет. Проверенные остальные cases прошли в расширенном прогоне на том же production-коде; это не повод скрывать прерванные повторные прогоны. Абсолютный импорт app проверен внутри workspace; в публичном final-artifact-checks.log сохраняется его безопасный относительный путь и hash абсолютного пути вместо данных хоста.

## Артефакты и следующая активация

`phase-a-review.patch` и `phase-a-source-manifest.json` описывают 15 изменённых source/test/rule путей. В полном CHANGELOG сохранена точная V-1256 concise-delivery запись; colleague-owned prompts только восстановлены byte-for-byte с public HEAD, без правок. Контекст source HEAD: **b9d893ec8babd4b2052ac1f497962e1966206bcb**; хеши предоставленных файлов и восстановленных публичных зависимостей — supplied-source.sha256 / public-restored-source.json. Model-review не тронут.

1. Root принимает точный Phase A код/проверки. В текущем pipeline новая роль **на Sol исключительно как activation stage**; UNKNOWN Gemini model не внесён в live manifest.
2. Только обычный owner idle watcher активирует Python. Root проверяет новый живой registry; ручного рестарта/выкатки здесь нет.
3. Затем root применяет отдельный **phase-b-specialist.patch**, выбирающий Gemini только этой новой роли. Existing workers/queues не мигрировать.
4. Через обычный admitted `spawn_worker` — один новый task-bound specialist на безопасной отдельной smoke-задаче (не retarget этого hubsol worker). Записать маленький self-contained HTML/CSS/SVG файл без внешних ресурсов; проверить точную selection/импорт файла и отсутствие auxiliary model/API calls. Пока это не выполнено, рабочий маршрут и Hub file capabilities операционно не подтверждены. Качество модели, видео и большие окна этим smoke не измеряются.

В этой private copy нет `.git`: commit/import выполняет broker на managed branch `task-V-1257/gemini-design` после окончания хода. **Actual imported HEAD пока недоступен**; его сообщает штатный broker после импорта, выдуманного commit SHA здесь нет. Не выполнялись commit/push/clone, deployment, restart, inference, child-worker запуск или обращения к защищённым данным.
