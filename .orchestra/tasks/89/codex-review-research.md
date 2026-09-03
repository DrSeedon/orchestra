Ну да, `9/9` выглядит убедительно ровно до момента, когда выясняется, что тестировали не worker-конфигурацию 🧪 Исследование требует доработки: F3–F4 пока не валидируют целевой runtime, а предложенный `git ls-files` не устраняет все stale-копии.

## Summary

- F2 подтверждает заметное уменьшение размера текста, но не фактическую экономию токенов; большая часть исходных измерений невоспроизводима из приложенных артефактов.
- `9/9` достаточно для статуса **LIKELY** только для трёх проверенных явных триггеров — после запуска в настоящей worker-конфигурации.
- `0/6` подтверждает поведение двух коротких no-tool запросов, но слабо характеризует обычные задачи воркера.
- F5 правильно различает канонические pipeline-файлы и untracked-копии, однако `git ls-files` не отличает committed-содержимое от перезаписанного tracked-файла.
- Файлы не изменялись.

## Findings

1. **blocking: Эксперимент запущен не в целевой worker-конфигурации**

   [research.md:85](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/research.md:85) называет испытания доказательством поведения Sol-сессий, но harness передаёт `is_orchestrator=True` ([experiment_skill_index.py:110](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/experiment_skill_index.py:110)), тогда как production factory передаёт реальное значение контекста ([runtime_registry.py:216](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/runtime_registry.py:216)). Для задачи про Sol workers целевое значение — `False`. Пока не доказано, что флаг полностью нейтрален для tool policy, permissions и prompt composition, результаты `9/9` и `0/6` нельзя переносить на worker runtime. Нужен повтор с `is_orchestrator=False`.

2. **blocking: `git ls-files` не гарантирует committed-содержимое файла**

   Предложение в [research.md:116](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/research.md:116) устраняет только stale **untracked** injections. Pipeline injection безусловно копирует файл поверх `.claude/skills/<name>/SKILL.md` ([prompting.py:182](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/prompting.py:182)) после checkout worktree ([manager.py:568](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/manager.py:568)). Если этот путь tracked, `git ls-files` продолжит его возвращать, хотя рабочее содержимое уже заменено pipeline-копией. После удаления skill из роли resolver снова объявит эту stale-копию проектной истиной. Следует читать committed blob через Git либо отдельно исключать tracked-but-modified injection; нужен тест именно на tracked path collision.

3. **suggestion: Расширить controls задачами, реально использующими инструменты**

   [research.md:95](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/research.md:95) основывает F4 на двух уникальных коротких вопросах, повторённых по три раза. Они вообще не вызывают Bash, поэтому почти не создают возможности для ошибочного обхода файлов. Даже при независимых испытаниях `0/6` оставляет одностороннюю 95% верхнюю границу false-read rate около 39%; повторение одинаковых prompts дополнительно уменьшает внешнюю валидность. Статус **LIKELY** стоит ограничить этими controls либо добавить несколько unrelated implementation/review задач с обычным чтением репозитория.

4. **suggestion: Сохранить воспроизводимые входы измерения F2**

   Из приложенных результатов независимо проверяются только `1,775` code points и `2,524` bytes трёхэлементного experiment index. Значения inline block, pipeline-only index и восьмиэлементного Seedon index в [research.md:53](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/research.md:53) существуют только как итоговые числа в тексте; harness их не вычисляет, список входов и hashes не сохранены. Арифметика процентов правильная, но основание для **CONFIRMED** со временем невоспроизводимо. Стоит записать это отдельным script output с путями и hashes.

5. **suggestion: Не называть byte/character reduction стоимостью prompt**

   F2 измеряет Unicode code points и UTF-8 bytes, тогда как размер контекста и inference cost определяются токенами. Поэтому заголовок [research.md:51](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/research.md:51) и формулировка «prompt cost» сильнее фактического измерения. До tokenizer-based сравнения корректнее говорить о размере сериализованного payload; направление выигрыша очевидно, точный процент token savings — нет.

6. **question: Как обрабатываются различающиеся дубликаты имён?**

   Pipeline precedence в [research.md:117](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/research.md:117) безопасен для идентичных копий, но при одинаковом frontmatter `name` и разных инструкциях он молча скрывает committed project workflow. Сам отчёт признаёт наличие таких имён, но не проверяет идентичность содержимого и называет правило лишь policy choice. Для детерминированности разумнее дедуплицировать идентичные файлы, а при расхождении fail loud либо закрепить pipeline override как явный контракт.

## Verdict

**❌ Needs revision — confidence 0.96.**

Два blocking-замечания мешают принять выводы и предложенный resolver как обоснованные. После worker-mode rerun и чтения committed Git blobs `9/9` разумно поддержит **LIKELY** для ясных триггеров; `0/6` всё равно останется предварительным сигналом, а не общей гарантией.

Сейчас `git ls-files` выступает как охранник со списком гостей: фамилию сверил, а кто именно прошёл внутрь — уже не его проблема.

## Round (2026-07-26T10:00:00Z)

Ну надо же, второй раунд действительно закрыл blockers, а не просто переименовал их 😏

## Summary

Оба блокера закрыты; все шесть прежних замечаний исправлены.

| Предыдущее замечание | Статус |
|---|---|
| Worker experiment использовал `is_orchestrator=True` | **FIXED** |
| `git ls-files` пропускал overwritten tracked skills | **FIXED** |
| Controls не использовали инструменты | **FIXED** |
| F2 не имел воспроизводимых измерений | **FIXED** |
| Payload reduction назывался token/cost reduction | **FIXED** |
| Pipeline precedence не имел явного контракта | **FIXED** |

Результаты подтверждают `9/9` positives, `0/8` controls, отсутствие extra reads и subagent events. Ограничения статистической уверенности сформулированы корректно.

## Findings

1. **suggestion: Сохранить hashes проигравших дубликатов**

   [research.md:131](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/research.md:131) ссылается на M1 как доказательство того, что Seedon-дубликаты отличаются от pipeline-файлов. Однако harness сначала отбрасывает их через `setdefault` ([experiment_skill_index.py:163](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/experiment_skill_index.py:163)), поэтому JSON содержит hashes только победивших pipeline-копий. Это не влияет на объявленный precedence-контракт, но для проверяемости утверждения стоит сохранить отдельный `duplicate_collisions` с обеими парами path/hash.

2. **suggestion: Исправить default output harness**

   [experiment_skill_index.py:304](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/docs/tasks/89/experiment_skill_index.py:304) по умолчанию всё ещё пишет в `experiment-results.json`, который отчёт объявляет superseded pilot, тогда как M1 — `experiment-worker-mode.json`. Запуск без `--output` перезапишет сохранённую историю и не обновит цитируемый результат. Лучше сделать worker-mode файл новым default.

## Verdict

**APPROVED — confidence 0.98.**

Блокирующих проблем нет. Оставшиеся предложения касаются воспроизводимости артефакта и не меняют выводы F2–F5 или предложенный дизайн.

Теперь исследование стоит ровно; осталось лишь подписать две коробки с hashes, чтобы при следующей проверке никто не гадал, что лежало в выброшенной.
