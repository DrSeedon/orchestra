# kb-index-injection — личная память

- **Промпт агента собирается в `ROLE_SYSTEM_PROMPT` (`app/manager.py`), а не в
  `build_system_prompt` (`app/pipeline.py`).** Второй — ЧИСТАЯ статика из файлов пайплайна
  и намеренно ничего не знает про проект. Всё, что зависит от `scope`, БД или диска
  проекта, добавляет первый. Класть туда динамику — единственный способ получить
  обновление без рестарта.
- **Тот же `ROLE_SYSTEM_PROMPT` зовут ДВА пути**: спавн (`_create_session_locked`) и
  переинжект первого хода после resume/compact (`session.py` → `manager.assemble_prompt`).
  Если правка попала в него — она доедет до живого агента сама. Если нет — только рестартом.
- **Воркеру `scope` раньше не передавали** (`ROLE_SYSTEM_PROMPT(pipeline, role)`), и это
  выглядит как защита от утечки чужих блоков. Это не так: списки других оркестраторов и
  воркеров закрыты `if is_orch` ВНУТРИ функции. Передавать scope воркеру безопасно.
- **Тесты проекта надо гонять через `uv run --frozen python -m pytest`.** Голый
  `python -m pytest` падает на `ModuleNotFoundError: dotenv` в `tests/conftest.py:153`.
- **Перед тем как назвать тест «сломал я», откати дерево и прогони его.** На 06.09.2026
  на `main` уже красные: потолок 16 KiB в `test_knowledge_instruction_source.py` и два
  теста про `docs/portfolio/**` в `test_orchestra_layout_430.py`. Способ: `git stash push -u
  -m '<уникальный-тег>'`, запомнить SHA из `git stash list --format='%H %gs'`, прогнать,
  вернуть через `git stash apply <sha>` и удалить запись.
