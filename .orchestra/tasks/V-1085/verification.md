# V-1085 — фактически выполненная проверка

Дата: 2026-10-25 UTC.

## Публичные источники

- Сбор из `https://elevenlabs.io/docs/llms.txt`: 592 страницы API Reference, все HTTP 200, 400 уникальных method/path после удаления дубликатов двух справочников. Метаданные/SHA-256: [sources/api-inventory.json](sources/api-inventory.json).
- 94 ссылки-источника report.md проверены HTTP GET: финальные ссылки HTTP 200. [sources/report-link-check.json](sources/report-link-check.json) хранит результаты/время. Help Center direct fetch вернул 403 bot protection, хотя web tool читал исходную страницу; в итоговом report ссылка заменена работающим официальным docs mirror. Другие способы доступа к личным данным не использовались.
- В source inventory `contains_deprecated_marker` означает наличие deprecated-текста/поля, а не автоматическую deprecated-классификацию route. Legacy routes определены по разделу официального индекса. `/speech-engine/upstream` — протокол нашего сервера: направление указано отдельно.
- Это проверка существования документов, не платных endpoints и не качества/стоимости результата генерации.

## Локальные проверки

`node .orchestra/tasks/V-1085/verify-artifacts.mjs` проверяет JSON inventory, уникальность routes, результаты link check, существование локальных ссылок, определения Markdown references, структуру таблиц/code fences, JSON curl-примера и placeholders вместо credentials. Дополнительно проверены строки формы private keys/provider tokens. Все проверки офлайн, источники/личные файлы не запрашиваются.

Python-пример проверен **только синтаксически** через `ast.parse`, без `urlopen`/импорта кода примера и без сетевого вызова:

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
uv run --frozen python - <<'PY'
import ast
from pathlib import Path
report = Path('.orchestra/tasks/V-1085/report.md').read_text()
blocks = report.split('```python\n')[1:]
for block in blocks:
    ast.parse(block.split('```', 1)[0])
print(f'Python snippets parsed offline: {len(blocks)}; no examples executed; app not imported')
PY
```

Результат: exit 0; `Python snippets parsed offline: 1; no examples executed; app not imported`. Использован provisioned **uv 0.11.28**, он создал стандартную `.venv` с Python 3.12.3 и установил 76 зависимостей замороженного проекта из кеша. Lock/pyproject не менялись; ElevenLabs SDK не устанавливался. Системный `uv` dispatcher не использовался; interpreter запущен именно provisioned uv в `.venv`, не самостоятельным системным Python.

Офлайн Markdown/JSON validator: **PASS**, exit 0 (итоговый запуск после правок).

Pytest и `scripts/run_tests.py` не запускались: исполняемый код Orchestra не менялся; нельзя представлять syntax/document checks как продуктовые тесты. `app` не импортировался, абсолютный путь импортированного `app` не применим.

## Остаточные ограничения

- Личная проверка аккаунта/Sergey — переданное root свидетельство 25 Oct, не повторена работником. Реальные списания/остаток/сэмплы не измерены.
- Таймкоды, fallback, recovery и API entitlement проверены по contract, а не исполнением; рекомендации для реализации не являются её тестами.
- Публичные pricing/terms/overview/reference местами противоречат друг другу; конкретные противоречия сохранены в report.md. HTTP 200 не разрешает их автоматически.
- В private worker copy коммит запрещён. После завершения платформа импортирует изменённые task artifacts в `task-V-1085/research-elevenlabs-api` и коммитит их. Локальный commit SHA и merge не заявляются.
