# salvage-branch-code — личная память

## Запуск тестов Orchestra

Только `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest`. Системный
`/usr/bin/python` роняет `tests/conftest.py:153` на `ModuleNotFoundError: dotenv` — падают
ВСЕ тесты сразу, и это выглядит как «перенесённый код сломан», хотя сломан интерпретатор.
Первый раз стоил лишнего прогона и минуты паники.

## Новый топик базы знаний

Три шага, иначе он невидим и не проходит гейт:
1. Файл в `.orchestra/kb/<topic>.md`.
2. Строка `- [<topic>](<topic>.md) — <описание>` в `.orchestra/kb/README.md`.
3. `python scripts/check_instruction_contract.py --sync` — оглавление в `AGENTS.md`/`CLAUDE.md`
   генерируется между маркерами `<!-- kb-topics:start/end -->`. Руками не править.

Схема, которую требует `scripts/check_kb_contract.py` (гейт диффовый и ручной — тестовый
прогон его НЕ вызывает, `tests/test_kb_markdown_contract.py` зелёный и без него):
- разделы `## Established | Rejected | Historical observations | Gaps | Sources`.
  Русские `## Установлено` формально «допустимы для старых тем», но в main их нет ни в одном
  из 43 топиков — валидатор их отвергает;
- каждая строка факта: `` - `fact:<kebab-key>` — <утверждение> · search: `<якорь>`, … ·
  evidence: <ссылки> · <дата>, #<задача> ``. Без `search:` — отказ;
- в `Gaps` префикса `` `fact:<key>` — `` быть НЕ должно, там обычная строка прозы.

Прогон: `git diff --cached -- .orchestra/kb > /tmp/kb.patch &&
python scripts/check_kb_contract.py --root .orchestra/kb --diff /tmp/kb.patch`.
Патч обязан содержать ТОЛЬКО файлы KB — иначе на каждой строке чужого файла будет
«changed KB path must be a Markdown file».

## Потолок корневых файлов

`AGENTS.md` и `CLAUDE.md` побайтно идентичны, потолок 16 KiB = 16384 байта жёсткий.
После #515 в них 16370. Свободно 14 байт — следующая строка оглавления не влезет.

## Устаревание факта проверяется по коду, а не по дате

При переносе исследовательских записей KB из старых веток: датированный факт не отменяется
автоматически, но и не переносится молча, если код с тех пор ушёл. Проверять символы, которые
факт называет, и помечать прямо в строке — `— SUPERSEDED <дата> #<задача>: <что сейчас>`.
Так это уже сделано в main (`model-text-control-flow.md`, метки `RETRACTED`/`RESOLVED`).
