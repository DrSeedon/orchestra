# V-900 / V-901: как вести файлы правил проекта

Повод — идея владельца от 17.10.2026, 11:52, в 11:55 он её уточнил (голосом, через cog-second-brain-orchestrator). Правило записано в `.orchestra/pipelines/default/prompts/modules/project-maintenance.md`, блок «Structure of a project's rules».

## Первое применение: cog-second-brain V-51 (коммит 14eab69 в /opt/cog-second-brain)

| | до | после |
|---|--:|--:|
| CLAUDE.md, байт на ход | 133 403 | 18 585 (−86,1%) |
| AGENTS.md | отставшая копия, 120 158 Б | симлинк на CLAUDE.md |
| тематические файлы | — | 10 шт. `.orchestra/kb/rules-*.md`, вместе 171 950 Б |

Сохранность проверена скриптом: 574 строки и 263 цитаты, пропусков 0. Headless-тест: факт из тематического файла в контекст не попадает, факт из ядра находится. Доказательства лежат в `/opt/cog-second-brain/.orchestra/tasks/V-51/`.

## Ловушка `.claude/rules/`

Первая попытка V-51 положила тематические файлы в `.claude/rules/`. Claude Code загружает все `.md` из этого каталога автоматически, поэтому на ход уходило ~189 КБ (ядро 18 507 Б + 170 893 Б) вместо прежних 133 КБ. Это показал запуск `claude -p --model haiku --disallowedTools Read Bash Grep Glob`: модель верно ответила на факт, который есть только в `.claude/rules/research.md`. Отсюда запрет в правиле.

## Состояние 17.10

Две разошедшиеся копии AGENTS.md остаются: comfy-image-pipeline (105 245 / 99 053 Б) и VPN-Service (41 118 / 36 018 Б). Механизм сверки — V-902.
