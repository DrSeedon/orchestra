# V-1271 — Только ответы ИИ

**Sanitized publication copy.** При публикационной корректировке проверены 14 исходных артефактов этой папки; абсолютные account/workspace/browser-cache пути заменены на `<WORKSPACE>`, `<BROWSER_CACHE>` и `<HUB_HOME>`. Ошибки, traces и результаты прогонов сохранены; RED-логи не удалены. По сообщению root оригиналы сохранены локально в `.orchestra/private/tasks/V-1271/hub-originals/`, hash/bytes manifest — `.orchestra/private/tasks/V-1271/hub-original-manifest.json`. Эти private originals недоступны Hub и здесь не читались. Публикационная корректировка не меняла production/test и не запускала проверки; последующий comparison описан отдельно; required RED и `app.__file__ = None` остаются в силе.

Реализация ожидает решения root по timeline RED; merge пока не принят. Основание: одобренный бриф V-1271, решение владельца 12:13. Ничего не выкатывал и не перезапускал; коммит/импорт делает канонический broker после окончания хода. В копии нет `.git`, HEAD не заявляю.

## Изменение

- Кнопка «Только ответы ИИ» непосредственно над чатом; `aria-pressed`, `aria-controls`, активный цвет, focus outline. На 390 px прежние compact/restart/logout остаются в пределах экрана.
- Повторно используется `_isChatTimelineAgentText`: `text` / `assistant` / `stream` без service-флага. Проза с упоминанием инструментов остаётся видимой. Incoming user/agent, outgoing tool envelopes, tool results, thinking, status/system скрыты вместе со своими timeline-маркерами.
- Один CSS-фильтр работает для истории, lazy prepend и SSE/stream. OFF возвращает те же DOM-узлы в прежнем порядке, без запроса истории/переподключения SSE; toggle не вызывает archive collapse. Обычное ограничение размера журнала сохраняется.
- По умолчанию полный журнал; `chatAnswersOnly` использует существующий localStorage-подход UI preferences. Отказ storage не ломает переключение. Кнопка догрузки и штатные loading/error/retry controls доступны при ON; после восстановления фильтр продолжает работать.
- Production-файлы: `app/static/js/app.js`, `app/static/js/i18n.js`, `app/static/css/style.css`, `CHANGELOG.md`. Регрессия: `tests/test_chat_answers_v1271.py`. Backend/API/хранилище истории и V-1270 не менял.

## Проверки

| Проверка | Результат / raw evidence |
|---|---|
| `node --check app/static/js/app.js` и `node --check app/static/js/i18n.js` | PASS, exit 0 |
| Required `uv run --frozen python -m pytest tests/test_chat_answers_v1271.py -q -o cache_dir=.orchestra/tasks/V-1271/pytest-cache` | RED: 3 setup errors, тела не запускались. В safe copy нет `app.routes`; autouse fixture `tests/conftest.py:665` импортирует `app.routes.sessions`. `pytest-required.log` |
| Supplemental browser + existing global-name regression (команда ниже) | **5 passed in 27.29s**, `checks-final.log`; 4 новых browser cases + существующий `test_static_js_globals.py` |
| Визуал / DOM | Реальный dashboard template, CSS, рендерер, history/paging/SSE handlers, синтетические данные. `answers-390.png`, `answers-1280.png`; оба просмотрены. ON/OFF aria, отсутствие горизонтального выхода кнопок, сохранность идентичности/порядка узлов, 1 paging request / 1 SSE connection, видимый live stream и переиспользование его узла на final |

Фактическая команда успешного browser-прогона (все пути относительно корня копии):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1271/tmp"
export CHAT_ANSWERS_SHOTS="$PWD/.orchestra/tasks/V-1271"
export CHAT_ANSWERS_CHROME="$HOME/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell"
echo 1000 > /proc/self/oom_score_adj
nice -n 10 uv run --frozen python -m pytest tests/test_chat_answers_v1271.py tests/test_static_js_globals.py -q --noconftest -o cache_dir=.orchestra/tasks/V-1271/pytest-cache
```

Provisioned uv 0.11.28, locked dependencies, default `.venv`; другой Python runner не подменял required check. `app.__file__ = None`: это namespace package; путь исходников в этой publication copy — `app/` относительно корня рабочей копии. В этой копии есть frontend, backend отсутствует. Browser cases полностью offline, HTTP/SSE заменены адаптерами; `--noconftest` обходит только отсутствующие общие backend-фикстуры и не является полным required gate. Один browser за раз, закрыт fixture; свои временные каталоги удалены.

## Найденное и ограничения

- Default Playwright Chromium 1223 отсутствует (`browser-first.log`); установленный Chrome не запускается под длинным workspace TMPDIR: `Socket path too long` (`browser-chrome.log`). Успешно использован уже установленный headless-shell 1248, без загрузки браузера.
- Первый behavioral run: 2 FAIL / 1 PASS (`browser-shell.log`): тест ошибочно ожидал отдельный DOM-узел для уже объединённого tool result. Добавлены orphan-result ID для настоящей проверки самостоятельных results. Второй: те же 2 FAIL / 1 PASS (`browser-second.log`) из-за порядка vendor-скриптов тестового стенда; порядок исправлен по dashboard template. Замороженные тесты не менялись.
- После зелёного прогона обнаружен реальный overflow при первоначальном размещении в header (`toolbar-dom.json`, сравнение с/без кнопки). Кнопка перенесена над чатом; проверка соседних кнопок добавлена. При review также исключены archive collapse на toggle и сокрытие recovery controls. Итоговый прогон зелёный.
- Полный backend/frontend server suite и боевой UI не проверены: safe copy не содержит нужных Python-модулей. Root обязан повторить обычный pytest без `--noconftest` в полном checkout, существующие `tests/test_frontend.py -k chat_timeline` и `tests/test_system_chat_entry.py`, затем проверить обновлённую статику на рабочем dashboard. Мерж/публикация/закрытие остаются у root.

Unified diff внесённых правок: `.orchestra/tasks/V-1271/implementation.diff` (собран по точным изменениям, не выдаётся за diff относительно Git HEAD). Все raw paths выше находятся в `.orchestra/tasks/V-1271/`. Секретов/боевых данных в артефактах нет.

Финальная проверка синтаксиса, form-scan артефактов и SHA-256 исходников: `artifact-review.log` (PASS). Проверен итоговый diff; временные тестовые данные удалены, фоновых тестовых запусков не осталось.

## Follow-up: root timeline RED (до merge)

Root сообщил: обычные host checks новой фичи + globals + system entries — 7 PASS; существующие timeline — 1 FAIL / 2 PASS / 136 deselected. Failure: после stream → text тот же узел `data-test-label=streaming` не стал `chatNavKind=final` за исходные 8 секунд. Private root log не читался и не копировался. Merge остаётся заблокирован root; предыдущий локальный green не заменяет эту проверку.

Для сравнения восстановлен точный исходный app.js обратным применением `implementation.diff` в памяти: Git blob `82c065aaada5f9758cf829987bc888b327c7ae8e`, SHA-256 `4b83b28dfda71cb1116869c863596f6f48ce14cbb4d1e1ec7cd6317afbaa8a7a` — совпадает с названным root префиксом 82c065. Итоговый app.js SHA-256 `f3d468b28188f934fcd3edb6171455620031f5ae74322ba8b28076c43bb1cfa3`; неизменённый chat.js SHA-256 `6fed637f43c20cc3b0ed2679536cac6f580d34d9bf1320af6b8672c40af739f3`. Сравнительный offline-прогон следует ниже. Замороженные тесты, assertions и таймауты не меняются.

Первый запуск comparison probe остановился до тестовых тел: `NameError: Page is not defined` при компиляции аннотаций неизменённых frozen test functions. Исправлен только импорт Page в probe, product/test исходники не менялись. Лог: `timeline-probe-setup.log` (sanitized at publication).


### Сравнение: результат и точный предел вывода

`timeline-comparison.json` и `timeline-probe.log` — sanitized publication copies нового offline-прогона; `timeline-probe.py` — воспроизводимый probe. Он компилирует исходные функции из `tests/test_frontend.py` через AST без изменения их тел, assertions и 8000 ms timeout. Подменён только startup dashboard на существующий offline actual-source harness; baseline app.js инжектируется из памяти. Все исходники product и тестов остались неизменными.

| Вариант | Frozen tests | Результат |
|---|---|---|
| Canonical baseline app.js, blob 82c065aa…, текущий неизменённый chat.js | final-answer timeline | 1 PASS |
| Final V-1271 app.js, тот же chat.js | все 3 timeline | 3 PASS |
| Baseline + диагностически удалённые finalize hooks chat.js (только в памяти) | final-answer timeline | ожидаемый RED: Timeout 8000ms |
| Final + та же диагностическая мутация chat.js | final-answer timeline | ожидаемый RED: тот же Timeout 8000ms |

Обе RED-мутации остановились на исходном wait: `type=stream`, `kind=agent`, `textLength=255`, `streamBubble=false`, `deferred=false`, `finalMarkers=1`. Это не green по exit code: `probe exit_code=0` означает только завершение диагностического runner; две FAIL сохранены в JSON/log.

Механизм доказан для мутации: `_finalizeStreamBubble()` уже отрисовал полный текст, но без публикации `dataset.chatTimelineType='text'` / `_recomputeChatTimelineFinals()` / `_syncChatTimelineControls()` не пересчитывается marker. Основной MutationObserver наблюдает только прямые `childList` изменения `#chat`; обновление содержимого существующего stream-узла его не будит. В исходном chat.js эти три строки присутствуют; V-1271 chat.js не менял. Сама логика `_isChatTimelineAgentText` и `_recomputeChatTimelineFinals` между baseline и final также не менялась.

**Host RED не объявлен исправленным или доказанным baseline RED.** На worker actual sources он не воспроизвёлся ни с baseline, ни с final. Подтверждено только: feature delta сама по себе не воспроизводит сбой в сравнимом offline стенде; отсутствие finalize publication воспроизводит его одинаково на обоих app.js. Отличие host может быть в реально обслуживаемом chat.js, runtime state либо startup/reload; это ещё гипотеза, а не факт о host.

Конкретный следующий шаг root: в том же failing page до закрытия сохранить хэш фактически полученного `chat.js`, `String(_finalizeStreamBubble)`, `String(_completeStreamBubble)`, `_selectionTouchesStream()`, `_streamDeferredFinal !== null` и dataset/длину узла (без private prose), затем повторить тот же host-test с baseline blob 82c065aa… при том же chat.js. `_route_frontend_sources()` в существующем тесте подменяет только app.js и CSS; chat.js приходит из fixture server, поэтому проверка только app.js на диске не устанавливает его runtime-версию. Ожидаемый SHA-256 worker chat.js: `6fed637f43c20cc3b0ed2679536cac6f580d34d9bf1320af6b8672c40af739f3`.

Команда probe: provisioned uv 0.11.28, default .venv, `nice -n 10 uv run --frozen python .orchestra/tasks/V-1271/timeline-probe.py`, с workspace-local TMPDIR и уже установленным headless-shell 1248 через CHAT_ANSWERS_CHROME. Внешний wrapper захватывал stdout/stderr, заменял account/workspace/browser paths и сохранял `timeline-probe.log`; timeout wrapper 120 s, frozen waits оставлены 8000 ms. Один browser, последовательные cases, закрыт finally. Root уже сообщил 7 PASS новых/global/system host checks; повторно их не выдаю за свой запуск. Без product fix нового полного required gate здесь не заявляю; root merge decision остаётся открытым.

## HOST diagnostic runner (по запросу root)

Подготовлен `host-acceptance.py`; product и frozen tests не изменены. Проверка runner controls: provisioned uv, `uv run --frozen python -m pytest .orchestra/tasks/V-1271/test_host_acceptance_runner.py -q -o cache_dir=.orchestra/tasks/V-1271/pytest-cache` — **2 passed in 0.91s**, `host-runner-tests.log`. Self-check отдельно проверил 9 условий verdict/provenance и реальные синтетические filesystem/SQLite/process/socket boundaries; это не host acceptance.

`uv run --frozen python .orchestra/tasks/V-1271/host-acceptance.py --preflight` в Hub-копии вернул ожидаемый **RC 2 / BLOCKED**: отсутствуют `app/main.py`, `app/db.py`, `app/routes/sessions.py`. Source pins baseline/final/chat/frozen body подтверждены; `host-preflight.json`. Полный fixture server/browser diagnostic здесь не запускался и не объявляется green. Root запустит его в полном checkout.

### Как root запускает HOST comparison

Из корня полного checkout, после штатной проверки доступных ресурсов:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
echo 1000 > /proc/self/oom_score_adj
nice -n 10 uv run --frozen python .orchestra/tasks/V-1271/host-acceptance.py --run
```

`CHAT_ANSWERS_CHROME` необязателен: без него используется установленный браузер locked Playwright; если нужен другой уже установленный Chromium/headless-shell, root задаёт его путь через эту переменную. Браузер не скачивается. Runner запускает один browser и три fixture servers последовательно (baseline, final, guard); ориентир — десятки секунд плюс startup каждого server, не замер скорости. Не выносит процессы в другой cgroup. На ноутбуке применить проектные nice/MemoryMax ограничения.

- **RC 0** — исходный точный frozen final-answer test выполнился и прошёл на baseline app.js blob `82c065aaada5f9758cf829987bc888b327c7ae8e` и final app.js; тот же тест в guard-варианте ожидаемо упал именно на исходном wait 5127 / 8000 ms. HTTP-ответы и runtime-finalizer совпали с зафиксированными source hashes; source files до/после не изменились. Это диагностический bundle, а не обычный pytest summary: guard FAIL обязателен для RC 0.
- **RC 1** — одна или обе обычные baseline/final проверки упали при подтверждённой provenance и корректно сработавшем guard. Сравнить их error frames и state; merge не принимать автоматически.
- **RC 2** — setup/provenance/capture/cleanup/guard error, пропуск исполнения, неожиданный browser error, дрейф исходников либо другой HTTP/runtime hash. Это не acceptance. Отсутствие полного backend здесь даёт RC 2 до запуска server/browser.

stdout содержит RC и относительный путь к новому `.orchestra/tasks/V-1271/host-run-*/result.json`. Рядом — `baseline.json`, `final.json`, `guard.json`. Каждый запуск создаёт новый каталог; stale предыдущий JSON не читается как результат текущего запуска. Старые RED-логи сохраняются.

### Что именно проверяет runner

- Исходное тело frozen test загружается без правок и без stale `.pyc`, SHA-256 тела `25806023526988271f17539d0ca98ebb885ce082c7b35c12920d684b65c0a1ff`; assertions и 8 s wait неизменны. Оригинальные `_goto_dashboard` и route helper используются; helper дополняется одинаковой baseline/final подменой только app.js. CSS/template/chat.js в обоих случаях из текущего checkout; это сравнение app.js, не откат всего Python commit.
- Каждый case получает свежий порт от собственного listening socket, новую SQLite, HOME/state/catalog/task repository и canonical synthetic seed. Запускается настоящий `app.main:app` с lifespan; `pytest` в server не импортируется. Server не подключается к существующему dashboard и не использует ORCHESTRA_TEST_BASE. Startup ограничен отдельными 60 s; это не изменение frozen test timeout.
- Сервер получает allowlist environment без наследованных credentials/NOTIFY_SOCKET. Dotenv отключён до app imports. Python audit policy запрещает production data/private/worker-memory/.git/.env reads, SQLite вне sandbox, writes вне sandbox, native child processes и sockets вне собственного fixture port; read roots ограничены source/runtime/sandbox. Browser использует свежий context, без proxy/service workers/websockets; page network разрешён только к собственному fixture origin. Отклонённые server операции записываются счётчиками причин, без адресов/значений. Это guard для доверенного кода проекта, не отдельный kernel network namespace.
- Из browser response event читаются **фактические decoded HTTP bytes** `chat.js` и app.js: в JSON только status, byte count, SHA-256 и static path. chat.js не подменяется. Ожидаемый HTTP chat hash — `6fed637f43c20cc3b0ed2679536cac6f580d34d9bf1320af6b8672c40af739f3`. Также сверяется SHA `String(_finalizeStreamBubble)` до canary injection.
- При FAIL сохраняются только тип ошибки/относительные frames и whitelist state: timeline type/kind, answer/service flags, длины текста/stream buffers, existence/connected flags, deferred/selection state, final marker count, generation/loading/snapshot flags, guard counter. Нет DOM prose, HTML, screenshots, request/response bodies, exception messages, env dump или server stdout. Account paths не сериализуются.
- False-positive guard меняет **только в памяти guard-case** вызов recompute внутри stream finalizer; assertions frozen test не трогает. Требуются ровно один вызов finalizer, TimeoutError на исходной строке 5127, полный текст ≥200, marker agent, отсутствие незавершённого stream/deferred. PASS/skip/ошибка в другом месте не принимаются за успешный guard.
- Context/browser/собственные server PID закрываются в finally; собственные DB/HOME/tmp удаляются после сохранения безопасного state/policy. При неудачном shutdown JSON содержит fixture PID и cleanup error; никакого pkill/process-group kill.

### Фактическая локальная проверка и оставшееся

Финальный `uv run --frozen python -m pytest .orchestra/tasks/V-1271/test_host_acceptance_runner.py -q -o cache_dir=.orchestra/tasks/V-1271/pytest-cache`: **2 passed in 0.79s**, `host-runner-controls.log`. `host-runner-self-check.json`: 9 проверок verdict/provenance плюс 8 реально отклонённых синтетических operations и разрешённые sandbox file/SQLite operations. Эти controls проверяют в том числе missing/wrong HTTP SHA, wrong runtime SHA, no execution, неожиданный guard PASS, wrong guard failure line, normal FAIL → RC 1 и source drift → RC 2.

Полный host-run пока **UNRUN**: safe copy не содержит backend. Preflight проверяет только pins/наличие файлов, а self-check — controls; RC 0 от них не является HOST acceptance. Guard может отказать startup, если приложение требует файлы/CLI вне sandbox: это RC 2 с типом/frames/policy reasons, не повод ослабить guard или тест. Поведение реального lifespan, HTTP capture и guard-case на полном backend подтвердит root запуском --run. Никакой product fix не внесён без воспроизведённого дефекта; root decision по исходному RED остаётся открытым.

## Root HOST startup failure: runner correction

По сообщению root исходный HOST run завершился RC 2: baseline/final/guard не исполнили frozen test, все получили `startup_failed`, `diagnostics=[]`, `write_outside_sandbox_denied:4`, `native_process_denied:3`; source hashes до/после одинаковы. Root сохраняет оригинал run; здесь его файлы не читались. Выявлен дефект самой диагностики: SafeLog принимал только exc_info, тогда как ASGI lifespan может передавать formatted traceback через startup.failed.message; audit policy сохраняла лишь counters. Product defect и green этим не доказаны. Исправление ниже ограничено task-local runner/controls.

### Исправление startup diagnostics и явные fixture profiles

Изменены только task-local `host-acceptance.py`, его controls и task artifacts. Product/frozen test source остаются неизменными. Корень реального startup отказа пока не установлен: нужен новый root run; прежний RC 2 не назван исправленным.

- Audit denials теперь содержат event/reason, phase, bounded stack frames без linecache/source reads и безопасный target scope/shape. Для native spawn — только allowlisted program/verb и argc; argv, env, команды и произвольные пути не сохраняются. Unknown path components редактируются; private targets не раскрываются. Тот же policy по-прежнему запрещает production DB/private/credentials, source writes, native children и non-fixture sockets.
- Перехватывается сам ASGI `lifespan.startup.failed`/`shutdown.failed` и фактическое исключение. Formatted traceback без exc_info разбирается только на type/relative frames; exception message, source lines и locals отбрасываются. SafeLog также распознаёт formatted traces. Теперь отсутствие logger exc_info не теряет диагностическую причину.
- Readiness pipe несёт только короткое notice (<512 bytes); подробности сначала пишутся в собственный `server-startup.json`, затем parent копирует их в итоговый case/startup JSON. Поэтому большие traces не блокируют pipe и не обрезаются как JSON. Детали сохраняются и при нуле выполненных frozen tests.
- `full` остаётся default: исходный application lifespan и прежний readonly workspace cwd. Для сбора причин есть `--startup-only`: один изолированный startup, без браузера и frozen test. Startup RC 0 означает только ready, НЕ acceptance.
- **Явный opt-in `chat-only`**: subprocess cwd — собственный sandbox; readonly source symlink `app` нужен для относительных StaticFiles/template путей. Relative cache/state writes идут в sandbox; resolved writes через source symlink всё ещё запрещены. После canonical seed приложение получает fixture-local `synthetic_chat_lifespan`: отключены actor restore/launch, cron, bridge, migrations и остальные application startup services. App/routes/static sources и frozen test не изменяются. App import сохраняет обычный момент Uvicorn factory внутри event loop.
- Каждый case и итоговый JSON содержат startup profile/scope/injection list. Смешение profiles — RC 2. **Chat-only PASS не доказывает исправление original full-lifecycle RED.** Это отдельно обозначенный HTTP/static/frozen-body comparative diagnostic; решение по исходному host RED остаётся root.

Точные root-команды после штатной проверки ресурсов (из полного checkout):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
echo 1000 > /proc/self/oom_score_adj
nice -n 10 uv run --frozen python .orchestra/tasks/V-1271/host-acceptance.py --startup-only --startup-profile full
```

Первая команда: ожидается RC 2, если прежний startup всё ещё заблокирован, теперь с `denial_details` и `diagnostics` в новом `host-run-*/startup-result.json`; либо RC 0 только для успешного startup. Frozen executions всегда 0, это не green acceptance.

```sh
nice -n 10 uv run --frozen python .orchestra/tasks/V-1271/host-acceptance.py --run --startup-profile chat-only
```

Вторая: baseline/final/guard на одинаковом synthetic chat fixture; RC 0 только при обоих PASS + guard Timeout на исходном frozen wait + совпадении фактических HTTP/runtime SHA и неизменности sources; RC 1 — проверенный ordinary FAIL; RC 2 — setup/provenance/guard/capture/cleanup error. Если импорт или HTTP route по-прежнему требует запрещённую операцию, вернётся RC 2 с новыми безопасными подробностями; policy не ослабляется. Старые root run и RED-логи не перезаписываются, новый каталог создаётся на каждый запуск.

Локальная проверка исправленного runner:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1271/tmp"
uv run --frozen python -m pytest .orchestra/tasks/V-1271/test_host_acceptance_runner.py -q -o cache_dir=.orchestra/tasks/V-1271/pytest-cache
```

**6 passed in 0.88s**, `host-runner-startup-final.log`. `host-runner-self-check.json`: 10 verdict/provenance controls, 9 реально заблокированных synthetic operations, плюс разрешённые sandbox file/SQLite/relative writes. Дополнительные tests: formatted startup traceback без exc_info; ASGI failure capture без секретной строки; full profile действительно исполняет исходный failing service, chat-only его не запускает; metadata >64 KiB сохраняется файлом при коротком pipe notice. Подтверждены source-symlink write denial и отсутствие synthetic argv/env markers в diagnostics.

`--preflight --startup-profile chat-only` здесь ожидаемо RC 2: отсутствуют `app/main.py`, `app/db.py`, `app/routes/sessions.py`; `host-preflight.json`. Реальный full/chat-only server и browser comparison **UNRUN в Hub**; root выполнит их на полном host. Network/model probes не повторялись. Новых продуктовых фиксов нет.

## Root static HTTP 500: bounded diagnostic correction

Root сообщил: full startup RC 2 с отказами в app/routes/tg.py:23, agent_cgroups/systemctl/migration; chat-only READY, но фактически загруженный `/static/js/chat.js` — HTTP 500 / 0 bytes во всех трёх cases, app.js — HTTP 200 с правильным SHA. Original root runs сохранены root, здесь не читались. Это failure безопасного fixture до сравнения frozen body, не доказательство product regression. Устаревший observer действительно наблюдал только lifespan, пропуская HTTP exception path. Новое исправление — task-local HTTP diagnostics и отдельно обозначенный source-only HTTP fixture без app/state/cache middleware; полный сервер не объявляется исправленным.

Первый source-only HTTP run локально выполнил точные frozen bodies: baseline PASS, final PASS, guard — ожидаемый Timeout; все chat.js ответы 200, 295386 bytes, SHA 6fed637f…; `host-run-9ooe8vdp/result.json`. При проверке результата найден дополнительный дефект runner: server-policy.json отсутствовал после stop. Проверен код locked `uvicorn.Server.capture_signals`: после graceful shutdown он восстанавливает handlers и повторно вызывает `signal.raise_signal`, поэтому внешний finally не является надёжным местом сохранения диагностик. Исправление — atomic persistence в момент capture и при завершении ASGI lifespan, без изменения signal handling/policy. Старый run сохранён; финальная проверка будет отдельным новым run.

### Финальное исправление static diagnostics и простой source-only fixture

**Рекомендация: для поставленной задачи использовать `source-only`.** Это небольшой ASGI fixture в `source_application()`: реальный dashboard template + raw JS/CSS из того же pinned checkout, без импорта `app.main`, DB, startup services, API или compression/cache/state middleware. Scripts загружаются по настоящему HTTP в template order после DOM ready, вызывается только `initChatTimeline`; общий app DOMContentLoaded/polling не запускается. Это намеренно ограниченное сравнение frontend sources, НЕ full-server/lifecycle acceptance. Frozen body, assertions, wait 5127/8000 ms, baseline blob и guard прежние.

Конкретные исправления task-local runner:

- Observer теперь перехватывает static HTTP exceptions и HTTP 500 без поднятого исключения. В diagnostics сохраняются только fixed path `/static/js/chat.js` (прочая static → `<other>`), status, тип и relative traceback frames, включая ограниченные ExceptionGroup causes. Query, response body, exception message/locals не сохраняются. `traceback.walk_tb` не читает source через linecache.
- Audit denials коррелируются с static request через ContextVar, включая threadpool context. Поздний chat.js failure не теряется при достижении bounded capture limit. Root SafeLog также слушает application logging, сохраняя только безопасный trace.
- Server diagnostics atomically сохраняются при capture и завершении ASGI lifespan, а не только во внешнем finally. Это необходимо из-за проверенного поведения locked Uvicorn: `capture_signals()` повторно подаёт полученный SIGTERM после shutdown. Snapshot writes сериализованы; missing durable capture теперь даёт RC 2. Signal handling не менялся.
- Raw source handler разрешает только файлы внутри `app/static` с frontend suffixes, не пишет gzip/cache и отвергает traversal/symlink escape. Защита state/DB/process/socket осталась прежней; source-only вообще не импортирует backend. Parent всё равно проверяет фактически полученные HTTP SHA app.js/chat.js, runtime-finalizer SHA, ровно один frozen invocation и unchanged source hashes.

**Фактический итог нового локального HTTP сравнения:** `.orchestra/tasks/V-1271/host-run-f2qm5bq6/result.json`, stdout `host-source-comparison-final.log`, RC 0 только в scope `isolated source HTTP/frozen-body comparison; NO backend/middleware/startup/API acceptance`.

| Case | Frozen outcome | Фактический chat.js HTTP | Durable policy capture |
|---|---|---|---|
| Baseline app.js blob 82c065aa… | PASS | 200, 295386 bytes, SHA 6fed637f… | enabled, denials {}, diagnostics 0 |
| Final app.js | PASS | 200, те же bytes/SHA | enabled, denials {}, diagnostics 0 |
| Guard (in-memory final recompute suppression) | EXPECTED FAIL, Timeout на tests/test_frontend.py:5127 | 200, те же bytes/SHA | enabled, denials {}, diagnostics 0 |

Полный chat.js HTTP SHA всех трёх cases: `6fed637f43c20cc3b0ed2679536cac6f580d34d9bf1320af6b8672c40af739f3`. Page errors — 0 у каждого; baseline/final исходники до/после равны; guard calls=1, node textLength=255/type=text/kind=agent, stream/deferred=false. Product/frozen test файлы не менялись. В source-only не было DB/API/model/network probes: только собственный loopback source fixture и браузер.

Воспроизводимая root-команда (обычный ресурсный gate перед браузером):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
echo 1000 > /proc/self/oom_score_adj
nice -n 10 uv run --frozen python .orchestra/tasks/V-1271/host-acceptance.py --run --startup-profile source-only
```

Если требуется отдельно установить точную причину старого middleware 500 на полном host, прежняя команда `--run --startup-profile chat-only` теперь снабжена HTTP exception/correlated-denial capture и сохранением ДО shutdown. Этот full-backend путь здесь **UNRUN** и не объявляется исправленным. Source-only байты не выдаются за ответ старого app middleware: профиль и scope записаны в JSON/ stdout, смешение profiles → RC 2. Первопричина исходного ordinary full-server timeline RED и старого static middleware 500 остаётся вопросом root; локальная source-equivalence не заменяет это решение.

Runner controls: `uv run --frozen python -m pytest .orchestra/tasks/V-1271/test_host_acceptance_runner.py -q -o cache_dir=.orchestra/tasks/V-1271/pytest-cache` — **11 passed in 1.90s**, `host-runner-static-controls-final.log`. Проверено: static ExceptionGroup и 500 без exception, отсутствие private marker/body/query в diagnostics, точный raw chat SHA + отсутствие API, persistence до shutdown, concurrent atomic snapshots. 11 verdict/provenance self-controls дополнительно отвергают отсутствие durable diagnostics. Старые ROOT/private originals и RED-логи не трогались.

## MIME-only fixture correction (root-confirmed cause)

Root подтвердил на полном host: новый source-only comparison RC 0; chat-only HTTP 500 вызван не product code, а `Starlette FileResponse → mimetypes.guess_type/init/read → read_outside_fixture_roots_denied` при чтении системной MIME базы. Root сохраняет оба host runs privately; здесь они не читались. Проверен фактический stdlib текущего provisioned Python: первое `mimetypes.init(files=[])` при `_db is None` всё равно добавляет `knownfiles` и вызывает registry reader. Поэтому одного `files=[]` недостаточно. Исправление ограничено process-local MIME initialization до imports приложения, без новых разрешений audit policy.

### MIME correction: результат, checks и root-команда

`initialize_fixture_mimetypes()` вызывается в отдельном fixture server process **после установки прежней audit policy, до dotenv/app/Starlette imports**. Только process-local изменения: `knownfiles=[]`, отключён `MimeTypes.read_windows_registry`, сброшен `_db`, затем `init(files=[])`. Поэтому используются встроенные MIME defaults stdlib; ни системные mime-файлы, ни registry не читаются, в том числе при последующем reset/init. Никаких новых read/process/socket permissions. Ready и durable policy JSON содержат `fixture_mime`: source=`python-stdlib-builtins-only`, knownfiles_count=0, registry_reader_disabled=true, JS/CSS/SVG types. В injections отмечен `stdlib_mimetypes_builtins_only` одинаково для baseline/final/guard.

Фактический прогон provisioned uv 0.11.28/default .venv:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1271/tmp"
uv run --frozen python -m pytest .orchestra/tasks/V-1271/test_host_acceptance_runner.py -q -o cache_dir=.orchestra/tasks/V-1271/pytest-cache
```

**12 passed in 3.57s**, `.orchestra/tasks/V-1271/host-runner-mime-controls.log`. В `host-runner-self-check.json` под `policy.mime` сохранён meaningful negative/positive control: первое `init(files=[])` пыталось открыть только специально созданный synthetic knownfile вне test sandbox и получило ожидаемый policy denial; после новой builtin-only initialization настоящий `Starlette FileResponse` отдал synthetic JS HTTP 200 с точным телом под той же policy. Настоящие host MIME файлы не использовались даже в negative control. Дополнительный unit guard запрещает любые MimeTypes.read calls и проверяет first/later init, CSS/SVG/JS builtins.

Source pins прошли прежние controls: baseline blob `82c065aaada5f9758cf829987bc888b327c7ae8e`, final app.js `f3d468b28188f934fcd3edb6171455620031f5ae74322ba8b28076c43bb1cfa3`, chat.js `6fed637f43c20cc3b0ed2679536cac6f580d34d9bf1320af6b8672c40af739f3`, frozen body `25806023526988271f17539d0ca98ebb885ce082c7b35c12920d684b65c0a1ff`. Product/frozen tests не менялись. Исходник `install_server_policy` byte-identical по SHA-256 `73fe956dc058cd0b47f8f4eb18fe326e982afd731771fad962d12e7c028caa16`. Fingerprints и publication path scan: `host-runner-mime-review.log`.

Теперь root запускает реальный middleware-путь (после штатного resource gate):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
echo 1000 > /proc/self/oom_score_adj
nice -n 10 uv run --frozen python .orchestra/tasks/V-1271/host-acceptance.py --run --startup-profile chat-only
```

RC semantics прежние: 0 только baseline/final PASS + точный expected guard FAIL + обязательные HTTP/runtime hashes/durable capture/unchanged sources; 1 — проверенный ordinary FAIL; 2 — setup/provenance/guard failure. В Hub-копии backend отсутствует, поэтому **полный chat-only host comparison после MIME correction здесь UNRUN**; root выполнит его с реальными middleware. Новый product fix, model/network probe или ослабление guard не делались. Private originals и старые RED evidence сохранены.
