# V-1270 — команды и сырые результаты

Рабочая папка: выданная broker-копия Orchestra. Записаны только task artifacts. Ниже — существенные фактически выполненные команды и результаты; длинные исходники не копируются.

## Версия upstream

```bash
curl -fsSL https://api.github.com/repos/govijr/terminal-mac/commits/main | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"sha":d["sha"],"date":d["commit"]["committer"]["date"],"url":d["html_url"]},indent=2))'
```

```json
{
  "sha": "7009117f9e910c3dd4b4bd863e8bc331bd3c9d96",
  "date": "2026-11-03T11:52:08Z",
  "url": "https://github.com/govijr/terminal-mac/commit/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96"
}
```

```bash
curl -fsSL 'https://api.github.com/repos/govijr/terminal-mac/git/trees/7009117f9e910c3dd4b4bd863e8bc331bd3c9d96?recursive=1' | python3 -c 'import json,sys; d=json.load(sys.stdin); print("truncated:",d.get("truncated")); print("\n".join(x["path"] for x in d["tree"] if x["type"]=="blob"))'
curl -fsSL https://api.github.com/repos/govijr/terminal-mac/releases/latest | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({k:d.get(k) for k in ("tag_name","name","published_at","prerelease","draft","html_url")},indent=2)); print("assets:",*[x["name"] for x in d.get("assets",[])],sep="\n")'
```

Обе команды exit 0; tree `truncated: False`. Release output:

```text
tag_name: v0.2.0-6
name: terminal-mac 0.2.0.
published_at: 2026-11-03T12:34:42Z
prerelease: false
draft: false
html_url: https://github.com/govijr/terminal-mac/releases/tag/v0.2.0-6
assets:
get.sh
terminal-mac-0.2.0-6-macos-arm64.zip
terminal-mac-0.2.0-6-macos-arm64.zip.sha256
```

## Чтение исходников

Фактический способ: `curl -fsSL` для Package.swift/docs/VALIDATION.md и stdlib `python3` (`urllib.request.urlopen(url, timeout=20).read().decode()`) для остальных pinned raw sources, с нумерацией строк и выборкой regex/ranges. Source bytes оставались в памяти. Все raw URLs, размеры и SHA-256 24 файлов terminal-mac — [source_inventory.json](source_inventory.json). Хеши получены `hashlib.sha256(data).hexdigest()`. Это инвентаризация, не product tests.

Существенные фактически выполненные локальные поиски/чтения:

```bash
rg -n -i 'computer.?use|screenshot|playwright|browser.?use' app --glob '*.py' --glob '!backend_codex.py' --glob '!backend_grok.py'
rg -n 'mcp_servers_custom|mcp_servers|def .*mcp' app/session_turns.py app/session.py app/tool_scoping.py app/runtime_registry.py
rg -n 'read_image|image_url|mimeType|type.*image|ImageContent' app/backend_claude.py app/backend_codex.py app/harness/llm.py app/backend_hub.py app/static/js/tool-renderers.js
sed -n '240,390p' app/harness/mcp.py
sed -n '390,485p' app/harness/loop.py
sed -n '125,175p' app/runtime_registry.py
sed -n '319,362p' app/runtime_registry.py
sed -n '2785,2845p' app/backend_codex.py
sed -n '355,430p' app/manager.py
sed -n '390,470p' app/harness/llm.py
sed -n '840,928p' app/routes/sessions.py
```

Для важных contracts проверены полные определения функций, не только grep. Хеши 22 файлов Orchestra сохранены. `.git` нет, git-команды не выполнялись.

Финальный source-only пересчёт MCP: в полученном через urllib `AgentServer.swift` взят блок между `static let tools:` и `func run()`, затем `re.findall(r'\["name": "([a-z]+)"', block)`. Raw результат — [public-source-checks.log](public-source-checks.log): **8** (`screenshot`, `click`, `move`, `drag`, `scroll`, `type`, `key`, `status`). Swift/MCP не запускался.

## Offline probe

```bash
python3 -I .orchestra/tasks/V-1270/check_bundle_contracts.py > .orchestra/tasks/V-1270/checks.log
```

Exit 0. Публикационная копия stdout — [checks.log](checks.log), **sanitizedpublicationcopy**: только source path заменён на `app/harness/mcp.py`, добавлена явная пометка; все исходные PASS/RESULT и прочие строки сохранены. Точный оригинал и SHA сохранены root приватно по его сообщению; здесь они не проверялись. Исходный probe: 6/6 PASS. Только AST-извлечённая чистая `_extract_text` и AST-инспекция `_hub_factory`; `app`/DB/provider не импортируются. Изображение — явный sentinel. Это **не требуемый uv/pytest check** и не MCP/runtime acceptance.

Read-only runner inventory (`ls -la .git .venv/bin/python "$HOME/.local/share/orchestra/tools/uv/0.11.28/bin/uv" .orchestra/tasks/V-1270 2>/dev/null`) вернул 2: `.git`, `.venv/bin/python` и task dir тогда отсутствовали; provisioned uv присутствовал. Никаких uv sync/install/замены lock. Product pytest/full suite не запускались: product не менялся, устанавливать зависимости запрещено. Системный Python использован только для source retrieval и research probe; его результат не выдан за required check.

## Официальные документы / ошибки чтения

Через web open/search прочитаны GitHub repository, Apple SLA Tahoe PDF/индекс, Kitty graphics protocol и iTerm2 images protocol. Apple developer HTML дал ссылки `.md`; web click вернул:

```text
Failed to fetch https://developer.apple.com/documentation/virtualization/running-macos-in-a-virtual-machine-on-apple-silicon.md: (400) Unsupported content-type: text/markdown
Failed to fetch https://developer.apple.com/documentation/virtualization/installing-macos-on-a-virtual-machine.md: (400) Unsupported content-type: text/markdown
```

Те же URLs затем успешно прочитаны напрямую urllib (exit 0); также `vzmacguestprovisioningoptions.md`. Sample сейчас macOS/Xcode 27, provisioning требует guest macOS 27+. Демо/sample не исполнялся, образ macOS не скачивался.

Для Linux-кандидата выполнен:

```bash
curl -fsSL https://api.github.com/repos/microsoft/playwright-mcp/commits/main | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["sha"],d["commit"]["committer"]["date"],d["html_url"])'
```

```text
176c8ea1832d5d0b36963af38191ac0088abdac6 2026-11-03T17:08:25Z https://github.com/microsoft/playwright-mcp/commit/176c8ea1832d5d0b36963af38191ac0088abdac6
```

README сначала прочитан на main, затем на pinned commit (хеш в inventory). Проверены Node.js 18, headless/isolated, browser_snapshot/browser_take_screenshot. Установки/запуска не было.

Login-shell при чтении checks.log один раз сообщил:

```text
/etc/profile.d/claude-hub-shims.sh: fork: retry: Resource temporarily unavailable
```

Shell и probe exit 0; далее login=false. Тяжёлые процессы не запускались. При создании этого commands.md первая apply_patch была отвергнута из-за пропущенного `+` в строке `draft: false`; файл тогда не создан, следующая корректная patch успешна. Полный список SKIPPED/UNTESTED — в report.md.

Финальная локальная инспекция (`python3` stdlib): разрешение reference/local links в report.md, повторный SHA-256 22 source files, ast.parse probe и скан task artifacts по извлечённому AST присваиванию `HUB_SECRET_SHAPES` из `app/publication_secrets.py`. Сам модуль не импортировался, credential/environment inventory не вызывалась. Raw результат — [validation.log](validation.log), exit 0, findings 0. Это проверка артефактов, не product/runtime suite.

## Publication correction по запросу root

Только правка task artifacts стандартной библиотекой: source path в checks.log заменён на относительный и добавлена пометка sanitizedpublicationcopy; исходный suffix с PASS/RESULT проверен побайтовым сравнением в памяти. Повторно проверены все 8 task artifacts на идентифицирующие account/host paths и формы credentials. Неидентифицирующие системные пути `/usr/bin/python3` и `/etc/profile.d/claude-hub-shims.sh`, публичные guest paths и шаблоны CLI сохранены. Исходный probe, product source checks/hashes, pytest, model calls и network не повторялись; private folder root не открывалась. Результат publication audit дописан в validation.log.
