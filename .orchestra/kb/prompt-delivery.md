# prompt-delivery

Что агент РЕАЛЬНО видит в промпте: сборка ролей из слоёв и модулей, доставка правок, зеркала.

## Established

- Собранный промпт роли = `base.md` + `roles/<role>.md` + модули из `pipeline.yaml`; проверяется
  одним вызовом `build_system_prompt(DEFAULT_PIPELINE, role)` (`app/pipeline.py`) · замер 19.08:
  orchestrator 49 782 Б, sub-orchestrator 49 080, worker 24 901, full-cycle 53 352, reducer 9 434 ·
  2026-08-19, #prompt-cleanup
- Запускать сборку в воркте только интерпретатором главного чекаута
  (`/home/kesha/orchestra/.venv/bin/python` + `sys.path.insert(0,'.')`): `uv run` создаёт в воркте
  ПУСТОЙ `.venv` и падает `ModuleNotFoundError: yaml` · 2026-08-19, #prompt-cleanup
- Дубль текста доказывается счётчиком вхождений в СОБРАННОМ промпте, а не наличием двух файлов ·
  `p.count('## Background jobs') == 2` у orchestrator и sub-orchestrator до правки (`base.md` +
  `modules/background-jobs.md`) · 2026-08-19, #prompt-cleanup
- Списки `modules:` у ролей прибиты дословно в `tests/test_default_pipeline.py:191-206`: любое
  добавление или удаление модуля роняет тест и требует правки теста в том же коммите ·
  2026-08-19, #prompt-cleanup
- Содержание политики ревью прибито якорями `tests/test_default_pipeline.py:512-530` (в том числе
  `**Sol review is mandatory regardless of size**` и `**targeted Opus cross-family review**`):
  снять обязательность ревью нельзя, не правя этот тест · 2026-08-19, #prompt-cleanup
- Слово `Pre-mortem` запрещено в промптах оркестраторов негативным тестом
  `TestPremortemReachesWorkingRolesOnly.test_orchestrator_roles_do_not_receive_the_step`; пишешь
  правило про самопроверку в `orchestration.md` — не используй это слово · 2026-08-19, #prompt-cleanup
- `CLAUDE.md` читается агентом каждый ход целиком: 144 306 Б на 19.08 до чистки; потолок зеркала
  `AGENTS.md` для Codex — `project_doc_max_bytes` в `~/.codex/config.toml`, на этой машине
  262 144 Б · 2026-08-19, #prompt-cleanup

## Rejected

- «`CLAUDE.md` обрезается зеркалом, поэтому надо срочно резать» — на 19.08 неверно: потолок
  262 144 Б против файла 144 306 Б, обрыва нет. Резать надо ради читаемости и стоимости хода,
  а не ради обрыва · 2026-08-19, #prompt-cleanup
- «Каталог памяти рантайма (`~/.claude/projects/.../memory/`) — рабочее место для знаний» —
  на этой машине каталога не существует (`ls` → No such file or directory), и прочитать его
  агент не может · 2026-08-19, #prompt-cleanup

## Gaps

- Сколько токенов реально стоит фиксированная часть хода (промпт + `CLAUDE.md` + скиллы) при
  99% cache_read — не мерили ни разу; все оценки в байтах · 2026-08-19, prompt-engineer
- Доезжают ли правки промптов до УЖЕ ЖИВЫХ сессий без реконнекта и с какой задержкой — известно
  частично (re-injection на resume/compact), сквозного замера на живом агенте нет ·
  2026-08-19, prompt-engineer
- «Грабли» в `CLAUDE.md` (92 920 Б, 64% файла) на дубли построчно не проверялись ·
  2026-08-19, prompt-engineer

## Источники

- .orchestra/tasks/prompt-cleanup/audit.md — аудит противоречий в правилах и промптах, 19.08.2026
- .orchestra/tasks/203/ — доставка модулей по ролям, утечки в чужие роли
- .orchestra/tasks/220/, .orchestra/tasks/137/ — перечитывание личной памяти на resume/compact
