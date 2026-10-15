# V-867 — калибровка чисел в ответе оркестратора

Добавлено короткое правило в `<user-answer-format>` [роли orchestrator](../../pipelines/default/prompts/roles/orchestrator.md): перед сравнительным, причинным, трендовым или обобщающим числом оркестратор проверяет N и единицу анализа, знаменатель, сопоставимый baseline/control и возможность объяснить вариацию шумом. Если утверждение неразличимо, его нужно убрать либо обозначить как неубедительное/шумное и назвать свидетельство, которое решило бы вопрос. Для точного подсчёта по полностью проверенному конечному множеству статистический тест не требуется, но сообщается охват (`x из N проверено`). Decision line записана по публичному формату промптов: owner decision, 2026-10-15; без цитаты.

Правило находится внутри существующего `<user-answer-format>`, который собирается только для `orchestrator`; новые модули или pipeline subscriptions не добавлялись. Это дополняет `research-method`: та инструкция задаёт измерительную работу, а новое правило не даёт представить владельцу числовой вывод сильнее его доказательств.

Проверки: `uv run --frozen python -m pytest tests/test_default_pipeline.py::TestUserAnswerFormatOwnership -q` — **2 passed**; `python scripts/check_instruction_contract.py` — passed; `uv run --frozen python scripts/check_pipeline_manifest.py --check` — passed; `git diff --check` — passed. Существующий mechanical ownership test подтвердил, что блок собран для orchestrator и не попал в sub-orchestrator, worker или full-cycle.

Изменённый код находится в prompt/config, `app/` не трогался. Рестарт не нужен: собранные prompt modules читаются при сборке новой сессии; уже живые сессии не получают изменённый prompt задним числом. Порядок ответа и delivery кода не менялись.
