# V-1122 evidence index

Все пути здесь относительно task directory. Дата получения публичных материалов: 2026-10-29 UTC. Файлы — данные исследования; инструкции и код upstream не исполнялись.

| Файл / группа | Происхождение и смысл |
|---|---|
| `environment.txt` | Реальный stdout date, наличия `.git`/`app`, provisioned uv version; без приватного cwd |
| `sentinelx-cloud-{core,installer,protocol}.metadata.json` | Фильтрованный stdout GET `https://api.github.com/repos/pensados/<repo>`: даты, состояние, лицензия, активность; поля с личными данными авторов не запрашивались для сохранения |
| `*.commits.json` для cloud repo | GET `/repos/pensados/<repo>/commits?per_page=3`, commit SHA/date/subject |
| `*.tree.json` для cloud repo | GET `/repos/pensados/<repo>/git/trees/<head SHA>?recursive=1`, paths/type/size и flag truncated |
| `sentinelx-core.metadata.json`, `sentinelx-core-mcp.metadata.json` | Реальные GitHub API error bodies: `Not Found`, `status: 404`. Соответствующие пустые commits/tree files — исходный пустой stdout неудачных GET, **не** проверенный пустой репозиторий |
| `homonyms.json` | GET `https://api.github.com/search/repositories?q=SentinelX&per_page=20&sort=stars`, фильтрованные публичные repo descriptions/датировки, не полный аудит 1 021 результата |
| `public-code-fetch.stdout.txt` | Реальный stdout `collect-public-code.sh`: pinned raw URL и SHA-256 пронумерованного содержимого на момент загрузки; stderr отдельно |
| `public-code-extra-fetch.stdout.txt` | Дополнительные pinned URL: licenses и protocol source; stderr отдельно |
| `public-code/*.txt` | Numbered snapshots выбранных исходников, а не clone/archive или runnable checkout. 11 upstream personal/example path lines заменены явными пропусками, line numbers сохранены. LICENSE каждого из трёх repo также здесь |
| `public-code-manifest.stdout.json` | Реальный stdout `prepare-evidence.py`: original-numbered SHA-256, retained SHA-256, omitted line numbers для каждого snapshot. Raw hashes относятся к нумерованному выводу, не к bytes HTTP response |
| `remote-auth-policy-search.stdout.txt`, `critical-search.stdout.txt`, `installer-search.stdout.txt`, `edit-upload-audit-search.stdout.txt` | Сохранённый stdout `rg` по public snapshots для проверенных критических путей. Поиск выполнен до исключения home-path примеров; private paths среды worker в эти выводы не входят |
| `orchestra-code-search.stdout.txt`, `orchestra-backends.stdout.txt`, `orchestra-state-delivery.stdout.txt` | Фактический stdout `rg` / numbered `sed` по доступной копии исходников Orchestra. Это не changelog и не live-process evidence |
| `orchestra-source-manifest.json` | Сохранённый исходный snapshot SHA-256/size 14 сопоставленных local source files, без absolute paths. Verifier только читает его и сверяет текущие файлы. Не Git commit pin; `.git` отсутствует |
| `runner.stdout.txt`, `runner.stderr.txt` | Provisioned uv 0.11.28, frozen project lock, default `.venv`, CPython 3.12.3; подготовка среды до сообщения-продолжения. App и чужой код не импортировались |
| `public-pages.stdout.json` | Реальный stdout public-pages collector: metadata-only HTTP responses, без cookies/credentials и хранения HTML. Три HTTP 403 сохранены как ошибки, 18 HTTP 200. GitHub snapshots и web retrieval — отдельные источники |
| `artifact-check.stdout.txt`, `artifact-check.stderr.txt` | Последний offline integrity check: parse local research scripts, pinned links/files/line bounds, source hashes, private-path/secret-shape checks. Это **не** тест безопасности SentinelX или live E2E |
| `verifier-correction.diff` | Узкая правка verifier: удалены проверки длины/формулировок отчёта, запись manifest заменена сравнением с сохранёнными hashes. При расхождении выводятся все затронутые relative paths и expected/current hashes, snapshot не обновляется |
| `verifier-revision-baseline.stdout.txt`, `verifier-freeze-check.stdout.json` | Реальные логи SHA-256 до правки и запуска verifier; побайтовая проверка неизменности manifest и полного report до/после, exit code verifier |
| `verifier-mismatch-check.stdout.txt` | Отрицательная offline-проверка: in-memory read одного исходника дополнен newline, файлы приложения не менялись. Verifier отказал с exit code 1, указав relative path и expected/current hashes; manifest и report остались побайтово прежними. Это синтетическое расхождение, не обнаруженный drift после sync |
| `privacy-current-observation.stdout.json`, `privacy-correction.diff` | Последующее точечное уточнение privacy: публичный GET 200 подтвердил Last updated 18 октября 2026 и country-not-IP для пользователя и агента. Дата первой публикации не установлена; прежнее упоминание 10 мая удалено из report. Исходный public-pages snapshot не переписывался |
| `privacy-correction-baseline.stdout.txt`, `privacy-correction-check.*.txt`, `privacy-correction-freeze-check.stdout.json` | Реальные логи offline verifier после уточнения report и побайтовой неизменности ранее сохранённого source manifest и самого verifier. Выводы исследования и приложение не менялись |

Точные внешние URL и anchors с интерпретацией — в `../report.md`. Public OpenAI listing и Help Center были прочитаны web retrieval; raw urllib GET этих страниц вернул 403, что явно зафиксировано. ChatGPT install URL через web выдавал публичную оболочку; logged-in app manifest/tools не получены. Пользовательская browser session не использовалась.

Выполненные локальные проверки исследовательских скриптов:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
bash -n .orchestra/tasks/V-1122/collect-public-code.sh
UV_OFFLINE=1 UV_NO_SYNC=1 uv run --frozen python .orchestra/tasks/V-1122/verify-artifacts.py
```

Скрипт `verify-artifacts.py` работает offline на сохранённых данных, не запускает source snapshots и не импортирует app. Проверок длины, заголовков или буквальных формулировок отчёта в нём нет; извлечение GitHub URL служит только проверке pins/files/line bounds. При исправлении verifier новый source manifest не генерировался: используется сохранённый snapshot первоначального исследования, а его неизменность проверена отдельно. Полный report также сохранён без изменения выводов.

`prepare-evidence.py` уже выполнен один раз: повторное его выполнение изменило бы смысл original-numbered hash на hash текущего уже очищенного снимка, поэтому без новой загрузки upstream повторять его не следует.

Не запускались pytest/full suite приложения: RESEARCH ONLY, app sources не менялись. Не запускались foreign tests, model/API inference, OAuth/enrollment, services или туннель.
