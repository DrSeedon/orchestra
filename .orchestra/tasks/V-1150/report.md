# V-1150 — Codex compact: ожидание, поздняя публикация, доставка

31.10.2026. Реализация в выданной копии, без детей, live providers, чтения
private histories/credentials, отправки реальных сообщений, выкладки или рестарта.
Полностью прочитаны оба переданных документа V-1148; они не изменены.

Приёмочная доработка после замечаний родителя: wording assertions заменены
проверками данных/каналов, добавлены supported-lifecycle immediate controls и
исправлена подтверждённая гонка immediate publication. Результаты первой версии
ниже сохранены как история проверок; актуальный subset указан отдельно.

В копии нет `.git`. Ветка результата задана брокером:
`task-V-1150/fix-codex-compact-delivery`. Commit/merge/push/archive выполняет
платформа/родитель. SHA HEAD здесь определить нельзя; точная идентичность
возвращаемых production/test файлов — `source-sha256.txt`. Родителю следует
сверить её с фактическим возвращённым HEAD перед независимой приёмкой.

## Изменения и граница API

| Файл / символы | Изменение поведения |
|---|---|
| `app/backend_codex.py`: `CODEX_COMPACT_TIMEOUT_SECONDS`, `_CompactOperation`, `compact_context`, `_release_compact` | Один общий бюджет ACK/S/C/T увеличен с 120 до 600 s. Operation сохраняет собственные usage, окно и callback публикации. После выхода caller поздний matching terminal вызывает отдельное reconciliation; исходный outcome и снимок ошибки не переписываются. |
| Там же: `send`, `retarget_model`, reducer usage | Монотонное поколение контекста меняется при начале нового user turn и retarget модели, включая переключение туда-обратно. Usage compact не пишет user last-call cache. Cumulative totals/window меняются только при совпадении context/thread/transport generation. |
| `app/session.py`: `_publish_codex_compact_context`, `_compact_codex_context` | Общая публикация immediate/late context через существующие `_persist` и `_log`. Late success требует ACK, started, compaction evidence, successful terminal, отсутствия fatal error и актуального backend/thread/model/turn/transport. Missing usage означает `known=false`, tokens/percentage=0, не прежние totals. |
| Там же: `require_current_snapshot` | Immediate result проверяет owner slot и session/model/turn/native backend snapshot до context publication, после handoff await и после persistence drain. Устаревший native success остаётся success в diagnostics, но не перезаписывает новую context/summary и не публикуется как успех текущей сессии. |
| Там же: reconciliation доставки | После terminal снова используется штатный `_flush_pending`, если предыдущая попытка была отвергнута во время незавершённого compact. Более новый контекст сохраняется. Новая автоматическая попытка запрещена после manual stop; работающий turn не затрагивается. Hibernate перепланируется только на idle без pending; durable deliveries будятся штатным механизмом. |
| Там же: `_fire_precompact_timer` | `compact_result.ok=false` теперь даёт `precompact timer failed`, а не `compacted`. |
| `app/mcp_stdio.py`: `compact_worker` | Transport budget 120 → 660 s; описание больше не обещает 30–60 секунд. Формат результата и отрицательный результат сохранены. |
| `app/static/js/app.js`: `compactAgent`, SSE handler, `_refreshContextAfterCompact`, `formatContext` | Только ручной compact получает 660000 ms вместо общего mutation default 5000 ms. Полученный status `compact done (native Codex):` инвалидирует существующий context cache и читает существующий endpoint. `known=false` отображается как unknown. Старые SSE после смены scope/agent/load generation отсекаются прежними guards. |
| `CHANGELOG.md` | Рукописная запись V-1150. |

Новых публичных endpoint, схем, обязательных prompt dependencies, платных fallback
или изменений CLI/auth нет. Публичная сигнатура backend `compact_context()` и
контракты HTTP/MCP-ответов сохранены. Внутренний session hook
`_compact_reconciler` захватывается operation один раз при старте и очищается;
отказанная новая попытка не заменяет observer старого owner. Reconciliation
не изображает новый user turn и не генерирует его terminal.

## Почему 600 секунд

Переданный агрегат V-1148: 11 explicit compact, все действительно сжались;
9 caller timeouts при 120 s; matching terminal 103.179–226.683 s. Это конечная
выборка, не provider SLA. Общие 600 s дают примерно 2.65 × наблюдавшийся максимум,
при этом ожидание остаётся конечным. ACK входит в тот же бюджет; heartbeat,
retryable error и другие уведомления его не продлевают. Definitive error,
failed/interrupted terminal, EOF и cancellation завершают caller немедленно.
660 s у ручных transport callers оставляют 60 s на HTTP/ответ после backend.
Общие таймауты прочих HTTP-запросов не изменены, POST не повторяется.

После этих 600 s исход по-прежнему unknown, пока не получены доказательства.
Owner сохраняется до terminal/закрытия транспорта. Повторный compact и hibernate
не обходят этот guard; обычный user send сохраняет прежнюю возможность работы.
Native automatic compaction внутри user turn не использует этот deadline.

## Нетривиальные ограничения

- ACK сам по себе не доказывает compact. Missing evidence/ACK, fatal error,
  failed/interrupted и transport close не публикуются как успех.
- Retired tagged usage по-прежнему отфильтрована. У late terminal нет гарантии
  измерения нового размера; usage после retirement не возвращает known=true.
- При более новом user turn/model/backend/thread/transport старое завершение не
  перезаписывает context. Разрешение lifecycle и пробуждение очереди отделены от
  права публикации старого context: иначе отказанный start сам блокировал бы
  восстановление сохранённой очереди.
- Manual interrupt остаётся отдельным явным действием. Timeout/cancellation
  caller не отправляют автоматический interrupt и не теряют сообщения.
- Observer работает в существующем reader lifecycle и памяти процесса; новый
  cross-process протокол восстановления или durable registry не добавлен.
- Реальный latency, HTTP/browser rendering и activation после idle watcher здесь
  не измерялись. 600 s не гарантируют, что любой будущий provider compact уложится.

## Регрессии и фактические проверки

Новые `tests/test_codex_compact_delivery_1150.py`,
`tests/test_codex_compact_immediate_1150.py`, `tests/test_codex_compact_ui_1150.py`
и `.cjs` дают **49 сценариев**. Python
переиспользует настоящий JSONL reader/request/send/events harness и настоящий
AgentSession permit/listener/queue; side effects DB/process/provider изолированы.
Существующие acceptance/test файлы не правились.

Синтетический clock управляет expiry настоящего `asyncio.timeout` без ожидания
минут. Он проверяет порядок и бюджет, не притворяется измерением provider latency.
Покрыты observed 227 s success, bounded timeout, eventual terminal, timeout/cancel
с поздней context/status publication и неизменностью старого ответа, missing
ACK/evidence/usage, fatal error, failed/interrupted/EOF, retired usage, newer turn
и model roundtrip, backend/thread/transport replacement, last-call overlap после
того, как listener уже принял user usage, direct/queued delivery, отказанный start
с сохранением очереди и последующим recovery, manual-stop guard, critical auto
late success, timer success/failure и 480 s native in-turn compact с heartbeat и
продолжением user output.

JS-регрессия исполняет настоящий SSE handler, compact button и context functions
в Node VM с изолированными UI adapters; это behavioral execution, не source/prose
assertions. Она проверяет long-call budget, новый status поверх старой ошибки,
инвалидацию context cache, unknown и stale-stream guards. Это не браузерный тест.

Runner: provisioned **uv 0.11.28**, стандартная `.venv`, frozen lock, actual
`tests/conftest.py`, без замены runner/lock/фикстур. Итоговая расширенная команда
первой версии из `commands.md`: **437 passed, 131 deselected, 119.11 s**.
Это все переданные backend/compact regression modules, релевантные session
compact/Codex/hibernate/interrupt и MCP Codex tests; полный host/browser suite
остаётся родителю. Node syntax check `app/static/js/app.js` прошёл.

Локальная mutation-проверка первой версии поймала **5 из 5** возвращённых дефектов: 120 s budget,
отключённый late observer, запись old compact usage в user last-call cache,
отключённый retry сохранённой очереди и 5000 ms browser compact budget. Для каждой
мутации штатный pytest дал ожидаемый failure соответствующего behavioral test;
source восстановлен побайтно в `finally`. Безопасная verbatim-сводка —
`mutation-results.txt`, полные красные выводы — `private/mutation-*.txt`.
Проверка SHA подтвердила совпадение восстановленных production/test байтов с
финальным зелёным прогоном 437 tests. Это собственная проверка работника, не
независимое судейство родителя. Чистый повтор новых регрессий после восстановления:
**39 passed, 25.14 s** (`private/restored-tests.txt`).

До финального зелёного прогона были промежуточные ошибки тестового harness
(импорт sibling test без `tests.`, отсутствующая JS adapter variable, импорт MCP
после подмены `subprocess.Popen`), исправлены в новых тестах. Исправлен также
пойманный новым тестом пропуск transport generation при обновлении shared window.
Наблюдались и краткие wall-clock падения неизменённых старых тестов: baseline
211 passed/1 failed; следующий набор 288/2; ещё один 410/1. Конкретные failures и
полные stdout/stderr сохранены в `private/`; финальный повтор прошёл без их правки.

Instruction contract **не прошёл**: `CLAUDE.md` в этой broker copy обычный файл,
не symlink на AGENTS.md. Он и правила не менялись; родителю нужен штатный прогон
в полном worktree. Это отдельный незелёный check, не замаскированный pytest.

Точный абсолютный путь реально импортированного `app/__init__.py` сохранён в
`private/import-path.txt`; проверено, что это app данной копии. Путь с runtime
user/host не переносится в публичные артефакты. `validation.txt` и
`source-sha256.txt` содержат безопасную идентичность и результат проверки форм
секретов (канонические `publication_secrets.HUB_SECRET_SHAPES`, без чтения
инвентаря credentials), Python syntax и отсутствия runtime-user literals.

Verbatim stdout/stderr всех прогонов находятся в игнорируемом `private/`, вместе с
сырыми промежуточными ошибками. `.gitignore` исключает также test tmp/catalog/cache
каталоги. Перед archive родителю следует сохранить эти private доказательства
отдельно; не публиковать сырые пути/host identities. V-1079/V-1148 не переписаны.

## Приёмочная доработка: wording и immediate freshness

Новые тесты больше не охраняют суффикс `late reconciliation`, английскую строку
unknown, полное предложение MCP failure или редакцию timer label. Проверяются:

- Единственная публикация на status channel с существующим frontend wire prefix
  `compact done (native Codex):`; отрицательные плечи запрещают такую публикацию.
  Late usage/context и snapshot, переданный на persist boundary, сравниваются по
  данным; исходный timeout/cancel и remote terminal остаются отдельными фактами.
- Unknown display использует translation adapter и не показывает старые цифры;
  конкретный translation key и английский текст не зафиксированы.
- MCP обязан обработать error payload и сохранить sentinel ошибки, а не выдать
  success или raw result. Человеческое предложение не сравнивается.
- Timer сохраняет фактический `compact_result.ok/error`, публикует тот же JSON
  result на status channel; native failure также присутствует на error channel.
  Это проверка результата/канала, не произвольного слова в timer label.

Guard модели конкретен: `AgentSession.change_model()` под `_lifecycle_lock`
отказывает при `_compacting` до вызова retarget. Новый разрешающий control
проверяет этот отказ и последующее успешное завершение того же compact
(`app/session.py:4148`, guard на строке 4152 текущей копии).

Но `routes.clear_session`, `rollback_session` и `restart_cli` могут сменить
runtime у IDLE сессии, пока `_compacting=true`. Первые два проверяют RUNNING,
restart использует lifecycle lock, который compact освобождает после старта.
Handlers находятся в `app/routes/sessions.py:1837`, `:1868`, `:1904`.
Это реальный supported overlap, а не изменение полей тестом: новые regressions
вызывают эти handlers, настоящий `_disconnect_backend` и native JSONL lifecycle;
заменён только OS-signal leaf fake process и внешние DB/delivery side effects.

До исправления result-stage controls дали **3 failed, 1 passed, 6 deselected,
38.96 s** (`private/immediate-before.txt`): старый compact вернул ok после
clear/rollback/restart. Исправление rechecks snapshot после result/handoff/drain.
Матрица 3 lifecycle transitions × 3 await boundaries проверяет сохранность нового
context, model/thread/summary, отсутствие лишнего persist/status success и
неизменный native `outcome=success`, `remote_outcome=completed` в diagnostics.
Новые fields/endpoints или протокол восстановления не добавлены.

Приёмочный subset после исправления: **64 passed, 235 deselected, 31.68 s**
(`private/review-revision-tests.txt`): все 49 новых controls и 15 релевантных
session tests. Новый full-repeat не запускался; host/full/browser у родителя.
Результат 437 tests относится к первой версии и не выдаётся за прогон нового HEAD.

Отдельная mutation доработки отключает только enforcement immediate snapshot
guard: **9 failed, 40.08 s**, все 3×3 behavioral controls отвергли дефект
(`private/mutation-immediate_freshness.txt`, безопасная сводка
`review-mutation-results.txt`). Source восстановлен побайтно. Первые пять
мутаций повторно не запускались: их исторические результаты не выдаются за
независимую приёмку текущего коммита.

Чистый повтор после восстановления source: **49 passed, 72.53 s**
(`private/review-restored-tests.txt`). Все новые regressions выполнены штатным
frozen uv/conftest; source/tests затем фиксируются актуальным manifest.
Старый manifest первой версии сохранён в `private/initial-green-source-sha256.txt`.

Текущий exact Git HEAD в broker copy по-прежнему отсутствует: `.git` не выдан,
новый commit создаётся платформой только после завершения turn. `source-sha256.txt`
идентифицирует именно возвращаемые байты; фактический SHA коммита должен приложить
родитель из broker result. Вымышленный SHA или ручной commit не создавались.

## Передача родителю

Результат на диске и тесты готовы для commit платформой. Требуются независимая
приёмка точного возвращённого HEAD, host/browser suite, merge/push/archive и
дальнейшая activation обычным idle watcher. Рабочий Python процесса здесь не
проверялся; deployment/restart/live compaction не выполнялись.
