# V-837 — очистка управляемых копий снятых скиллов

## Причина и принадлежность файлов

`_retired_skill_hashes()` находил удаление по новому пути `.orchestra/pipelines/default/prompts/skills/<name>.md`, затем перечислял blob-ы только по этому пути. Он не проходил Git rename до старого `pipelines/default/prompts/skills/`, откуда были скопированы некоторые файлы.

Проверка живых файлов дала следующие результаты SHA-256:

- `/home/kesha/orchestra/.codex/skills/codex-debate/SKILL.md` совпадает с историческим blob `2b5e38baab643d4c5e39cf035e6c23e222592193` по новому пути.
- `/home/kesha/projects/University/.claude/skills/codex-debate/SKILL.md` совпадает с blob `849f8c3d8ccb152a6bc1cdb1c4abd3b3dd7b0d8d` из старого `pipelines/default/prompts/skills/codex-debate.md`.
- `/home/kesha/projects/VPN-Service/.codex/skills/codex-debate/SKILL.md` совпадает с blob `45da3205de5aa4ba47f4cef11d1aa86f8860e47a` из того же старого пути.
- `/home/kesha/orchestra/.claude/skills/explainer-video/.SKILL.md.2465765.76455e54.tmp` совпадает с blob `3420a123b39f3ed7662986d3b5cf9e0c20721063` исторического `explainer-video.md`; имя временного файла также соответствует шаблону атомарной записи `_copy_skill_file()`.
- `/home/kesha/orchestra/.claude/skills/codex-debate/SKILL.md` не совпадает ни с одним найденным историческим blob. Ближайшая историческая версия отличается изменёнными frontmatter description и заголовком с пометкой владельца о заморозке ревью. Принадлежность инжектору не доказана, файл сохраняется.

Пути `/opt/cog-second-brain/{.claude,.codex}/skills/codex-debate` не менялись.

## Изменение

Исторические hash-ы теперь извлекаются с `git log --follow`, включая имена путей на каждом коммите. Поэтому точные копии из legacy-пути распознаются без ослабления hash-проверки. На штатном refresh чистятся неотслеживаемые файлы с историческим содержимым и осиротевшие прямые дочерние файлы формата `.SKILL.md.<pid>.<8-hex>.tmp` только в каталоге снятого скилла. Tracked-файлы, symlink-каталоги, изменённое содержимое и временные файлы другого формата остаются на месте.

Refresh вызывается из `AgentSession._ensure_backend()` через `_refresh_skills()` при подключении backend; без worktree используется `cwd`, в том числе для оркестратора. После рестарта достаточно следующего подключения/переподключения сессии, чтобы механизм обработал соответствующий home (`.claude` или `.codex`). Живые файлы в этой задаче вручную не удалялись.

## Проверки

`uv run --frozen python -m pytest tests/test_manager.py -k 'skill' tests/test_unified_html_skill.py tests/test_laptop_skill_delivery_572.py -q` — 42 passed, 158 deselected.

Новые тесты проверяют чтение хэша до переезда файла, очистку старой точной копии, удаление orphan temp по формату имени, сохранение чужого формата, tracked копии/temp и содержимого за symlink-каталогом.

Проверены контрольные хэши реальных путей: `_retired_skill_hashes()` содержит точные хэши root Codex, University, VPN-Service и видео temp. Для проверки регрессий после коммита тестов временно отключались `--follow` и защита `rel in tracked`: тест на старый blob, изменившийся до перемещения пути, упал на отсутствии его хэша; тест tracked-копии упал, потому что файл был удалён. Мутации восстановлены; итоговый набор из 42 тестов зелёный, рабочее дерево чистое.
