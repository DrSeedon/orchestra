## Tests

`uv run pytest tests/ -v` не дошел до запуска тестов: `uv` попытался писать кеш в `/home/maxim/.cache/uv` и упал на read-only FS.

Повтор с `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -v` собрал 97 тестов, но завис на первом `tests/test_api.py::TestDashboard::test_root_returns_html`. Узкий запуск с `-o faulthandler_timeout=5` показывает зависание в `TestClient(app).__enter__` из `tests/test_api.py:27`, до выполнения самого запроса.

Контрольный прогон без API-тестов прошел: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_db.py tests/test_session.py tests/test_workspace.py tests/test_manager.py -v` - 77 passed in 1.46s.

## Summary

Проект выглядит как рабочий прототип, но сейчас его нельзя принимать как надежный: полный test suite не завершается, а API-тесты зависают на startup fixture. Самые опасные дефекты не в SQL, а в async lifecycle и браузерном рендере: есть XSS через `marked.parse(...)`, гонки вокруг активного SDK-клиента и stale rendering при переключении scope/agent. Архивирование воркеров фактически не соответствует обещанному контракту: имя архива не сохраняется, запись и логи удаляются, а tools потом все равно обещают читать архив. Тесты покрывают happy path, но почти не проверяют реальные конкурентные сценарии, а один concurrency-test содержит assertion, который всегда проходит.

## Замечания

blocking: app/static/js/app.js:400 - XSS. Контент из agent logs прогоняется через `marked.parse(...)` и вставляется в `innerHTML` без sanitizer; то же повторяется для `tool_result` и обычного bot text на строках 431 и 433. Любой агент/tool может вернуть `<img onerror=...>` или HTML с handler-атрибутами, и UI выполнит это в браузере. Фикс: подключить DOMPurify и рендерить `DOMPurify.sanitize(marked.parse(content))`, либо отключить raw HTML в markdown и для tool output использовать `textContent`.

blocking: app/session.py:147 - гонка в `_on_debounce`: pending копируется/очищается, потом код делает `await self._client.disconnect()` вне `_lock` и только после этого ставит `status = RUNNING`. Если в этот промежуток приходит новый `send()`, он видит сессию idle, ставит новый debounce, и второй debounce может disconnect-нуть клиента, которым уже пользуется `_run_turn`. Фикс: защищать `_pending`, `_client` и status одним lock; выставлять running до await; новые сообщения во время running класть в очередь и запускать следующий turn только после завершения текущего.

blocking: app/session.py:124 - сообщение во время `RUNNING` считается успешно отправленным, даже если `_client.query(message)` падает. Исключение только логируется warning, API возвращает `{"ok": true}`, а сообщение теряется. Фикс: при failed inject возвращать ошибку или класть сообщение обратно в `_pending` с retry после текущего turn.

blocking: app/manager.py:142 - `ensure_loaded()` не синхронизирован. Два одновременных `/send` или `/context` для одной unloaded DB-сессии могут создать два `AgentSession` с одним id и два SDK client connection; в `self.sessions` останется последний, первый станет leaked live client. Фикс: per-session async lock по `(name, scope)`, повторный `get_by_name()` внутри lock, cleanup клиента при неудачной загрузке.

blocking: app/static/js/app.js:444 - refresh loop не является latest-wins. Если пользователь меняет orchestrator/agent во время активного refresh, новый `refresh()` просто возвращается из-за `refreshInProgress`, старый запрос не abort-ится и потом может отрендерить sessions/logs старого scope в уже очищенный UI нового scope. Фикс: snapshot `scope`/`selectedAgent` в начале, abort старого запроса до guard, и перед commit в DOM проверять request sequence id.

blocking: app/manager.py:129 - worktree cleanup вызывает `remove_worktree(session.scope, session.worktree_path)`, хотя `remove_worktree()` ожидает `repo_path`. Если `scope != repo_path` (API это позволяет), `git worktree remove` запускается в не-репозитории, silently warning, а worktree остается на диске. Фикс: хранить `repo_path` в session DB или вычислять git common dir из worktree, и тестировать remove при `scope != repo_path`.

blocking: app/session.py:264 - архивирование воркера сломано на уровне контракта. `stop()` меняет `self.name`, но `save_session()` на update не пишет `name`, а `SessionManager.remove()` затем вызывает `delete_session()`, который каскадно удаляет logs. При этом `tools.py:139` и `worker_prompt.md:21` обещают архивное имя и читаемые логи. Фикс: выбрать один контракт: либо delete действительно удаляет без обещаний архива, либо stop/archive не удаляет row/logs, обновляет `name`, и UI/tools читают архив.

blocking: tests/test_api.py:27 - весь API suite зависает на `with TestClient(app) as c`. Это не “медленный тест”, это CI-blocker: полный `pytest tests/ -v` не дает результата. Фикс: изолировать app factory вместо импортируемого singleton, сбрасывать global `manager` между тестами, и добавить startup timeout/regression test на lifespan/TestClient.

suggestion: app/db.py:118 - `get_logs(... after_id=0, limit=200)` возвращает первые 200 логов по возрастанию id. Для долгой сессии начальная загрузка UI на `app/static/js/app.js:466` никогда не покажет последние сообщения, а `get_worker_logs` с описанием “recent logs” вернет старье. Фикс: отдельный режим recent с `ORDER BY id DESC LIMIT ?` и reverse перед отдачей, cursor оставить только для polling after last id.

suggestion: app/tools.py:103 - `get_worker_logs` умеет читать только активные sessions из `_manager.sessions`; импорт `get_session_by_name` не используется. Это прямо конфликтует с сообщением kill/archive, где обещано читать логи по archived name. Фикс: добавить `scope` в tool schema или искать DB rows по имени во всех known scopes/DB, затем читать logs по DB id.

suggestion: app/tools.py:72 - `list_workers()` строит список archived только по scopes активных sessions. После рестарта без активных воркеров архивные записи в DB исчезают из результата. Фикс: сделать DB-запрос по всем worker sessions, затем overlay active state из memory.

suggestion: app/static/js/app.js:470 - `localMessages` keyed только текстом сообщения. Два одинаковых сообщения во время running, или совпадение локального текста с replayed log content, ломают дедупликацию: одно сообщение может исчезнуть, другое внезапно отрендериться дублем. Фикс: использовать client-generated temporary id/timestamp и подтверждать конкретный pending bubble, а не строку content.

suggestion: app/static/js/app.js:163 - `contextCache` keyed только по `session.name` и не очищается при смене orchestrator scope. Одинаковые имена агентов в разных scope покажут stale context percentage до завершения нового запроса. Фикс: ключ `${scope}:${name}` и clear по scope switch.

nit: app/static/js/app.js:14 - `$$` объявлен, но не используется. Удалить, чтобы не плодить dead code.

nit: tests/test_session.py:136 - `assert len(session._pending) >= 0` всегда true и не проверяет очередь. Этот тест дает ложное чувство покрытия concurrency. Фикс: проверять конкретный контракт: вызван ли `query`, появился ли pending item, не потерялось ли сообщение после завершения текущего turn.

## Вердикт

Не принимать как refactor v1.1. Сначала починить зависающий API test suite, XSS, async races вокруг `_client`/debounce/load и привести archive/worktree lifecycle к одному честному контракту. После этого нужны целевые тесты на concurrent send, parallel ensure_loaded, long-log initial load, scope switch during refresh и XSS escaping.

## Round 2

### Tests

`timeout 60s env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -v` все еще не завершается: собрано 97 tests, затем зависание на `tests/test_api.py::TestDashboard::test_root_returns_html`.

Узкий запуск `timeout 15s env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_api.py::TestDashboard::test_root_returns_html -vv -s -o faulthandler_timeout=5` подтверждает тот же hang в `TestClient(app).__enter__` на `tests/test_api.py:27`.

Контрольный прогон без API-тестов проходит: `timeout 60s env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_db.py tests/test_session.py tests/test_workspace.py tests/test_manager.py -v` - 77 passed in 1.50s.

### Original Findings

FIXED: app/static/js/app.js:400 - XSS через markdown-render. `DOMPurify.sanitize(marked.parse(...))` добавлен на stream/text/tool_result paths, `DOMPurify` подключен в template до `app.js`.

STILL BROKEN: app/session.py:147 - debounce race. Disconnect/reconnect теперь под `_lock`, но осталась handoff-гонка: `_on_debounce` выставляет `status = RUNNING`, выходит из lock, и только потом создает `_turn_task`. Любой `send()` в этот промежуток попадет в `RUNNING`, увидит `_is_connected == False`, не положит сообщение в `_pending` и silently вернет success.

STILL BROKEN: app/session.py:124 - failed inject во время `RUNNING` все еще глотается. Код по-прежнему делает `logger.warning(f"inject failed: {e}")` и возвращает success, не retry-ит и не сообщает API об ошибке.

FIXED: app/manager.py:144 - `ensure_loaded()` получил per `(scope, name)` lock и double-check внутри lock. Это закрывает основной double-start/leaked-client сценарий из Round 1.

STILL BROKEN: app/static/js/app.js:444 - refresh loop все еще не latest-wins. Guard `if (refreshInProgress) return` стоит до abort, scope/agent не snapshot-ятся, и старый request все еще может коммитить DOM после переключения.

FIXED: app/workspace.py:64 - `remove_worktree()` теперь пытается восстановить реальный repo из `.git` pointer файла, так что `manager.remove(... scope ...)` больше не обязан работать только при `scope == repo_path` для нормального git worktree.

STILL BROKEN: app/session.py:266 / app/tools.py:145 - archive contract починен только для active `kill_worker`: `stop()` сохраняет row/logs и имя обновляется. Но archived lookup все еще зависит от scopes активных sessions, а не от всей DB; после рестарта без активной сессии в том же scope архивный worker снова "not found".

STILL BROKEN: tests/test_api.py:27 - API suite все еще висит на `TestClient(app).__enter__`. Это остается blocker для CI.

FIXED: app/db.py:119 - initial logs теперь берутся `ORDER BY id DESC LIMIT ?` с reverse, cursor path `after_id > 0` остался ascending.

STILL BROKEN: app/tools.py:103 - `get_worker_logs` теперь умеет DB lookup, но только по `for scope in set(s.scope for s in _manager.sessions.values())`. Это не "archived workers too" в общем случае; без активной сессии в нужном scope архив не находится.

STILL BROKEN: app/tools.py:72 - `list_workers()` по-прежнему строит archive только по scopes активных sessions. После рестарта/пустого manager архивные DB rows не показываются.

STILL BROKEN: app/static/js/app.js:470 - `localMessages` все еще keyed только текстом content. Два одинаковых сообщения или совпадение с replayed log content продолжают ломать dedupe.

STILL BROKEN: app/static/js/app.js:216 - `contextCache` формально стал `${scope}:${name}`, но `fetchAgentContext()` использует mutable `currentScope` после await. Ответ на request из старого scope может записаться под новым scope и обновить текущий display, если имя агента совпало.

FIXED: app/static/js/app.js:13 - unused `$$` удален.

STILL BROKEN: tests/test_session.py:136 / tests/test_session.py:234 - всегда-true assertion не исправлен по сути. `assert session._pending or session.status == AgentStatus.RUNNING` проходит потому что прямо перед этим уже asserted `RUNNING`; отдельный `assert True` в `TestConcurrentSend` вообще остался.

### New Issues

blocking: app/session.py:124 - `send()` во время freshly-started RUNNING turn может потерять сообщение еще до debounce. `start(initial_message)` создает `_client`, ставит `RUNNING`, но `_is_connected` станет true только внутри `_run_turn`; любой send до connect/logical receive просто логирует user_message и возвращает без queue/query. Фикс: все sends, которые нельзя гарантированно inject-нуть, должны уходить в `_pending`.

blocking: app/main.py:126 - `GET /api/sessions/{name}/context` вызывает `ensure_loaded()` для stopped/error DB rows. Теперь, когда archive rows сохраняются, простой выбор archived worker в UI может перезапустить убитую сессию ради context usage. Фикс: не auto-start stopped/error sessions; для них возвращать cached/zero context из DB state.

suggestion: app/manager.py:31 - `_load_locks` никогда не чистится. При большом числе unique `(scope, name)` это простой memory leak в long-running server. Фикс: удалять lock в `finally`, если он не locked и session уже loaded/not found, или использовать bounded/weak registry.

suggestion: app/templates/dashboard.html:6 - UI теперь зависит от CDN для DOMPurify, но в коде нет fallback. Если CDN недоступен, первый bot/tool render падает на `DOMPurify is not defined`. Фикс: vendor static asset локально или guard/fallback к `textContent`.

### Verdict

Round 2 частично улучшил ситуацию, но принимать нельзя. Из 15 исходных пунктов реально закрыты 5; 10 остаются broken или only-partial. Главные blockers сейчас: полный API suite висит, сообщения все еще теряются в RUNNING/handoff состояниях, frontend refresh/context остаются stale-racy, archive lookup не работает без активного scope.
