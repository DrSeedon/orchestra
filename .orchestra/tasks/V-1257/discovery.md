# V-1257 — DISCOVERY DONE; implementation blocked pending root acceptance

Historical checkpoint: root subsequently accepted option A and owner funding authority on 2026-11-03. Implementation now proceeds under implementation-notes.md; this original discovery report is retained as evidence, not a current approval request.

Argon найден в живом каталоге. Узкий допуск пока нельзя безопасно свести к добавлению одной модели: не подтверждены оплата и возможности конкретного Hub-драйвера, а существующий допуск не получает контекст дизайна. Исходники не изменены. Работник остаётся hubsol. Запусков Gemini и новых платных вызовов — 0.

## Точная идентичность

Источник: read-only `mcp__t3_code.orchestrator_capabilities({})`, 03.11.2026 UTC; сохранённый полный объект провайдера и объект делегирования — catalog-evidence.json. Идентификаторы тредов и настройки аккаунтов не сохранялись.

| Поле | Подтверждено |
|---|---|
| Hub model ID / display name | `gemini-4-argon` / `Gemini 4 Argon` |
| Hub provider instance / driver kind | `antigravity` / `antigravity`; display `Antigravity` |
| Effort | `reasoningEffort`: low, medium, high; default/current high |
| Ограничения каталога | `constraints: []`; это не успешный запуск |
| Provider-level child support | `canRunChildTask: true`, `canRunCrossProviderChildTask: true` |
| Допуск в delegate_task | Нет Argon ни в одной из 8 категорий; запуск не проверялся |
| Hub runtime modes | В объекте Antigravity нет `runtimeModes`; full-access для него не подтверждён |
| Orchestra сейчас | Argon отсутствует в `SELECTABLE_MODEL_SPECS` и `HUB_MODELS`; Hub-работники допускаются только на `hub-gpt-6.1-sol` |
| Orchestra runtime/provider для будущего маршрута | Предлагается сохранить `hub` / `multicode`, сопоставив с Hub `antigravity` / `gemini-4-argon`; нового native runtime не требуется |

Это точный ID Hub, а не доказанный API ID Google. Подмена на `gemini`, `gemini-pro`, старые `agy-*` или native CLI не разрешена.

## Возможности, польза, ограничения и оплата

Транспорт Orchestra уже умеет ограниченную копию файлов → Hub workspace → provider/model selection → импорт результатов; effort берётся из каталога. Результаты HTML/CSS/SVG и дизайн-текст потенциально могут идти тем же путём. В Hub нет поля с перечнем инструментов Argon, поддержкой чтения/записи файлов, изображений, браузера, screenshot QA или генерации растров. Ни одной такой способности на текущем маршруте не измерено. Предполагаемая польза — отдельный вариант модели для дизайн-задач и разгрузка Sol после допуска; улучшение качества или скорости не установлено.

Google подтверждает Argon в Antigravity app/CLI, на платных Pro/Ultra и подходящих Enterprise-планах. Публичные документы описывают инструменты и артефакты, но не доказывают совместимость Hub-адаптера. Генерация картинок в Antigravity использует отдельную модель Nano Banana 2; не включать её автоматически в исключение. Источники и короткие дословные выдержки: public-source-evidence.md.

**Кто платит за этот Hub-маршрут — неизвестно.** Каталог не содержит payer/plan/quota/credit-overage metadata. Комментарий в `app/models.py` относит существующие Hub-модели к пулу Multicode, а `HubBackend._turn_end()` пишет `cost_usd=0` и `billing_mode="free"`; это локальный учёт, не подтверждение источника оплаты Antigravity. Google допускает overage-кредиты и отдельный Enterprise API. Нужна безопасная аттестация владельца Hub о покрытии маршрута имеющимся пулом и отсутствии неразрешённого платного fallback/overage. Секреты и сведения об аккаунтах не нужны.

`app/hub_pool.py` перечисляет claude/codex/grok, а `provider_for_model()` распознаёт только Claude/Codex. Простое добавление Antigravity в registry обойдёт проверку его ёмкости. Источник и семантика квоты Antigravity пока неизвестны; нельзя выдумать проценты или разрешить расход по отсутствию данных.

## Минимальный план после принятия root

1. Подтвердить оплату и получить read-only описание возможностей именно Hub-драйвера: разрешённый runtime mode, файловые инструменты, image inputs и доступные ограничения инструментов. До этого регистрацию можно обсуждать, включение маршрута остаётся заблокированным. Без inference сейчас; безопасный smoke/sample требует отдельного допуска.
2. Добавить ровно одну спецификацию в `app/models.py` и одно сопоставление в `app/backend_hub.py`. Возможный внутренний ID **только как предложение**: `hub-gemini-4-argon` → (`antigravity`, `gemini-4-argon`); display `Hub: Gemini 4 Argon`, runtime `hub`, provider `multicode`. Не добавлять общие Gemini-алиасы, не объявлять image modality/context/price без доказательств и не открывать остальные Hub-модели. Если неизвестный context нельзя честно представить текущим ModelSpec, отдельно согласовать метаданные вместо выдуманного лимита.
3. Принять контракт design-only (развилка ниже), затем передать проверяемый контекст в канонический gate на spawn, смене модели, каждой доставке, backend connect/start/send, восстановлении и replay очереди. Не ослаблять `ensure_hub_worker_allowed` до общего разрешения Argon. Ошибка допуска сохраняет входы, историю и recovery latch; отсутствие/невалидность разрешения закрывает исключение.
4. Подключить подтверждённую квоту Antigravity к существующему admission. При отсутствии подтверждения не отправлять дизайн-задачу; не переходить на другой API/модель. Сохранить file/secret policy, ownership, изоляцию, лимит одновременных Hub-ходов и существующую политику Sol для остальной работы. Не мигрировать старые строки/работников/очереди.
5. После реализации — offline mock-проверки разрешающего и запрещающего плеча, scope/task mismatch, неизвестного billing/capability/quota, старых данных и восстановления, без реальных CLI. Замороженные тесты не менять: если утверждённое исключение конфликтует с контрактом V-1240, предъявить root конкретный конфликт. Изменение model-routing согласовать отдельно; communication/orchestration/worker-lifecycle/orchestrator prompts принадлежат research-delivery, model-review заморожен.

## Развилка контракта — нужна root/owner

В `AgentSession` сохраняются role/pipeline/task_id/model_reason; `TaskStore` schema v2 допускает description/tags, но не типизированное разрешение дизайна. `scope` означает путь проекта, `owned_dirs` ограничивает переносимые файлы, а не вид задачи. `validate_model_reason()` стирает причины для моделей кроме protected local Luna. Gate сейчас принимает **только model**, поэтому он не может различить дизайн и обычный код, в том числе при recovery.

Возможны два варианта: (A) согласовать специальную pipeline-role для дизайна и её полномочия, связать её с текущей задачей и передавать в gate на всех границах; физически новые поля могут не понадобиться, но семантика разрешения будет новой и роль сама по себе не гарантирует характер последующих сообщений; (B) согласовать явное сохраняемое разрешение, привязанное к задаче/назначению, с правилами выдачи и повторной проверки. Это изменение публичного контракта, не мелкая правка alias. В поставленной копии нет pipeline.yaml, поэтому наличие пригодной текущей дизайн-роли не подтверждено. **Выбора за root не делал.** Prompt, имя работника, слова “design/creative” в reason или произвольный tag не заменяют разрешение.

## Фактическая проверка

`uv 0.11.28`, предусмотренный broker PATH; `uv run --frozen python -m pytest tests/test_hub_sol_only_v1240.py tests/test_hub_effort.py -q` (добавлены только локальные basetemp/cache paths). Реальные провайдеры не вызываются. Лог: checks.log. **118 passed, 4 failed, 6.98 s**, exit 1. Все 4 сбоя требуют отсутствующего `.orchestra/pipelines/default/pipeline.yaml`: queued delivery recovery; retarget effort; две параметризации pipeline effort. Полный зелёный прогон и эта часть восстановления не подтверждены. Manifest/тесты не подменялись; другой интерпретатор не использовался. Абсолютный импорт app записан в artifact-checks.log.

Хеши проверенных исходников до/после — source-before.sha256 / artifact-checks.log; исходники сохранены. Доказательства кода с номерами строк — source-evidence.txt. Новых production/runtime изменений нет; реализация, реальный smoke и оценка качества ожидают принятия root и снятия указанных неизвестных.
