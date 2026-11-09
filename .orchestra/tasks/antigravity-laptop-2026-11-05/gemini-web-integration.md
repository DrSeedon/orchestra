# Gemini Web / Harness integration — 2026-11-05

Источник задачи: прямой бриф Максима через implementation sub-agent. Разрешены
четыре web-модели, импорт cookies только ранее проверенного аккаунта через RAM/stdin,
защищённый auth-файл на VPS, один живой запрос Argon и restart только orchestra.service.
Commit/push/смена ветки запрещены. Исходный пилот и подтверждение владельца — рядом.

Решение: изолированный helper-процесс с gemini-webapi==2.1.1; основной read-only
runtime не меняется. Выбор Python: GEMINI_WEB_PYTHON, текущий Python при наличии
пакета, data/gemini-web-pilot/.venv, затем пользовательский pilot venv.
Авторизация: GEMINI_WEB_AUTH_FILE либо ORCHESTRA_HOME/gemini-web/auth.json,
иначе каталог БД/gemini-web/auth.json. Каталог 0700, файл 0600, атомарная замена.
Readiness локальная: доступность auth/helper; сетевое подтверждение principal
происходит перед каждой генерацией. Fallback на другую модель/аккаунт отсутствует.

Ошибка, найденная при реализации: context_length=0 (неизвестное окно web-модели)
попадало в HarnessBackend._max_context как нулевой бюджет. Исправлено: при
неизвестном окне используется существующий DEFAULT_CONTEXT, без выдуманной
оценки окна в каталоге. Web API не раскрывает токены: usage.cost=0,
prompt/completion_tokens=0 с token_counts_available=false, это не замер токенов.

Unit-проверки на хабе: 31 passed; дальнейшие результаты будут дописаны после VPS.
Расширенный первый прогон: 81 passed, 1 failed —
tests/test_models.py::test_selectable_models_match_the_curated_catalog ожидает
старый закрытый набор без уже существующих antigravity/* и новых gemini-web/*.
Приёмочная проверка не ослаблялась; исходное расхождение проверяется отдельно.
Проверка исходного app/models.py из HEAD подтвердила: 17 лишних по старому
тесту маршрутов, все google-antigravity, до наших изменений.
Дополнительный прогон catalog API: 57 passed, 4 setup errors — изолированный
TaskStore тестов не может инициализироваться без Git author identity в окружении
хаба. Для повторного прогона задаются только временные GIT_AUTHOR/COMMITTER_*
переменные команды; настройки Git и рабочая ветка не меняются.
После исправления окружения тестов найдено второе место с контрактом окна:
validate_model_registry разрешал неизвестное context_length=0 только Hub;
новые web-модели отклонялись при startup. Расширяется только разрешение
неизвестного окна для gemini-web, вместе с явным тестом registry/startup.
Внешний первоисточник пакета: https://github.com/HanaokaYuzu/Gemini-API/releases/tag/v2.1.1

## Результат VPS и ограничения

- 62 passed на хабе (Gemini Web, GigaChat, catalog API, harness turn usage).
- 35 passed за 3.20 s на VPS: `./.venv/bin/python -m pytest tests/test_gemini_web_harness.py -q`.
- `scripts/check_instruction_contract.py`: OK; `git diff --check`: OK.
- Проверенный импорт на VPS: `/home/kesha/orchestra/app/__init__.py`.
- Боевой Python остался `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python`;
  web-клиент запущен дочерним процессом отдельного pilot venv, версия 2.1.1.
- Свежие cookies прочитаны из Opera на ноутбуке `on-remote --pc-home` и переданы
  через захваченный stdout в RAM и SSH stdin. Значения не выводились/не писались
  во временные файлы. Назначение: `/home/kesha/orchestra/data/gemini-web/auth.json`,
  подтверждены каталог 0700, файл 0600. Файл не отслеживается Git.
- `sudo systemctl restart orchestra.service` выполнен; active, новый PID 2065841.
  В живых `/api/models` и `/api/models/catalog` доступны все четыре web-модели.
  `cut_names=[]`, прерванных ходов до/после нет; 80 idle, 3 waiting.
  `telegram-bot-api` не перезапускался: PID до/после 769.
- Выполнена ровно ОДНА реальная генерация через `GeminiWebClient.stream` из
  боевого Python: principal совпал, выбран `gemini-argon`, display `4 Argon`,
  события `text_delta`, `final`, длительность 6.231 s, cost=0.0.
  Пустой ответ транспорт отклоняет, поэтому факт получения текста подтверждён.
- **Красная проверка:** ответ не совпал строго с `OK` (`response_is_ok=false`,
  canary `success=false`, exit=1). Текст ответа в первой версии canary не был
  сохранён; причину несовпадения доказать по артефакту нельзя. Отчёт НЕ исправлялся
  задним числом, повторная генерация не делалась (в брифе разрешён один прогон).
  Это успешный транспортный запрос, но не зелёная проверка исполнения инструкции.
- Web API не раскрывает фактическую атрибуцию ответа модели, токены и срок жизни
  cookies. Выбор объекта Argon подтверждён; фактическая атрибуция неизвестна.
  Auto-refresh выключен: после истечения cookies нужен новый разрешённый импорт.

Артефакты: `gemini-web-harness-result.json`, `gemini-web-service-before.json`,
`gemini-web-service-after.json`. Unit stdout: 35 passed (VPS), 62 passed (hub).
Полный suite не запускался; отдельный старый curated-catalog тест остаётся красным
(17 исходных Antigravity-маршрутов плюс четыре добавленных Web-маршрута).
Commits, push и смена ветки не выполнялись. Чужие исходные изменения AGENTS.md
и остальные untracked-каталоги сохранены.
