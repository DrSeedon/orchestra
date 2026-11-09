# Пять free-моделей через Orchestra Harness — результат

Выполнено 15 сочетаний (5 моделей × 3 задачи), N=1 на сочетание. Всего **38 model POST**; во всех полученных usage стоимость **$0**. Только перечисленные exact :free, без платных подмен, без retries.

| Модель | Разработчик | Инструмент | Баг: оракул | Документ | Оракул / 3 | Корректно завершено / 3 |
|---|---|---|---|---|---:|---:|
| Flint | [Recursive](https://recursive.com/updates/introducing-recursive-flint) | FAIL | PASS | PASS | 2/3 | 1/3 |
| Dots3-Note | [Dots Studio](https://huggingface.co/dots-studio/dots3-note-prev) | PASS | FAIL | PASS | 2/3 | 2/3 |
| Nemotron 3 Ultra | [NVIDIA](https://research.nvidia.com/labs/nemotron/Nemotron-3-Ultra/) | PASS | PASS | PASS | 3/3 | 2/3 |
| North Mini Code | [Cohere](https://cohere.com/blog/north-mini-code) | PASS | FAIL | FAIL | 1/3 | 1/3 |
| Nemotron 3.5 Super VL | [NVIDIA](https://research.nvidia.com/labs/nemotron/Nemotron-3.5-Super-and-Lightning/) | PASS | PASS | PASS | 3/3 | 2/3 |

## Что именно измерено

Штатные app.harness.loop.AgentLoop и app.harness.llm.OpenRouterClient. Одноразовая evaluation-ветка без platform worker spawn; canonical validate_harness_model_spec и quota admission вызваны в каждом изолированном плече. Политики обычного worker dispatch не менялись.
Использованы существующие namespace/network/snapshot/oracle функции scripts.local_bench. На хабе doctor PASS, без изменения AppArmor/sysctl. Все вопросы имели красный baseline и зелёный reference до model calls; input и oracle SHA-256 одинаковы для всех пяти моделей каждого вопроса.
Задачи: прочитать неизвестное модели значение инструментом; исправить публичный calc.total (неизменённый оракул из существующего repair-примера, пять проверок); извлечь актуальные данные из синтетического журнала с архивами/черновиками и точными номерами строк.
Лимит на вопрос: три HTTP/agent rounds, 1536 output tokens, reasoning medium, 115 секунд; вопросы выполнялись последовательно. Provider retries отключены. Vision не проверялся.

## Ограничения и причины отказов

- Flint/protocol: ответ оборван на лимите длины. Это не доказательство отсутствия tool support: реальные tool calls были.
- Все пять repair-плеч достигли max_turns=3. Flint, Ultra и Super VL успели исправить код до прохождения тестов, но не завершили агентный ход. Dots потратила лимит на поиск файла, включая запрещённый recursive find; North сначала пыталась read директории и затем искала файл. Ни одна repair-попытка не является успешным завершённым агентным ходом.
- North/document: факты извлечены верно, но модель указала строки 42–44 вместо настоящих 62–64. Frozen oracle это отклонил; проверка не ослаблялась.
- В коротком прогоне Ultra и Super VL дали 3/3 проходящих артефакта, но только 2/3 корректно завершённых ходов. Это три простых текстовых задания с N=1, а не рейтинг общего интеллекта. Жёсткий лимит сильно цензурирует исправление кода.
- Provider usage показал cost=0 на всех 38 попытках. Результат относится к текущей доступности free endpoints, не к будущей квоте или размеру пула.

## Обнаруженный дефект приватности

В исходном адаптере реальные /etc/passwd и /etc/group, унаследованные от стандартного local_bench, позволили ls в двух repair-плечах вывести имя пользователя хаба. Этот tool output попал в последующие запросы Flint и North. В NVIDIA-плечах такой вывод не найден. Следовательно, весь исходный переданный контекст нельзя назвать строго синтетическим.
Артефакты не подменялись. После прогона в отдельном адаптере введены synthetic passwd/group и hostname; локальная проверка получила bench/bench/benchmark. Красный baseline и зелёный reference вновь прошли без model calls. Полный прогон с новым слоем не повторялся.
Поиск шаблонов OpenRouter API key в артефактах дал 0 совпадений. Ключ передавался в RAM по stdin, в model prompt/argv/файлы не попадал. Оригинальные adapter sources и hashes сохранены в runtime-src исходного прогона.

## Проверки и расположение

- Все 15 test-процессов завершены; relay закрывались в finally.
- Негативные проверки: платный маршрут и другой free-маршрут вне списка отклонены до model requests.
- Production DB, catalog, provider flags, службы и настройки T3 не менялись; новые worker routes не разрешались.
Абсолютный импорт app: /mnt/claude-data/astrahancev-maxim-911aird/orchestra/app; исходный Git HEAD b57f361995c2ff6722d6238e3c5aa802a96f5b39.
Исходный прогон: /mnt/claude-data/astrahancev-maxim-911aird/orchestra/.orchestra/tasks/openrouter-free-bench-2026-11-05/runs/20261105T11342396429; raw stdout/stderr закрыты .gitignore.
Агрегат: summary.json. Полный app pytest не запускался: production app не менялся; проверялись скрипты оценки, frozen controls, негативные route guards и реальные ответы.
