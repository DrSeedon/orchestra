# Проверки доставки V-1158

Первоначальный результат **10 passed in 0.04s** и полная проверка 176 файлов **до transport** сохранены дословно в `private-evidence/original/`; исходные REPORT/CHECKS/verification и inventory176 не переписывались. Нормализованный импорт: `worker-copy/app/usage_contract.py`; полного app import не было.

Использован provisioned uv 0.11.28, default `.venv`, исходный lock. Повторная проверка касается миграции/расчётов и архивных данных, **не свежих списаний Wello**:

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 uv run --frozen python .orchestra/tasks/V-1158/verify_evidence.py --evidence-root .orchestra/tasks/V-1158/private-evidence/original
PYTHONDONTWRITEBYTECODE=1 uv run --frozen python -m pytest .orchestra/tasks/V-1158/test_research.py -q -o cache_dir=.orchestra/tasks/V-1158/private-evidence/pytest-cache
```

Тестам можно передать альтернативный архив через `TASK_V1158_EVIDENCE_ROOT`; без него используется указанный task-local путь. Сеть/CLI провайдеров тесты не вызывают. Полный продуктовый suite не требуется: нет изменений продукта, урезанной копии недостаёт backend dependencies и штатных test scripts.

**Post-transport контракт:** проверяются все **172 обязательных non-cache оригинала / 17 034 919 байт и 38 body SHA**. Четыре rebuildable-файла `.pytest_cache/{.gitignore,CACHEDIR.TAG,README.md,v/cache/nodeids}` (37/191/302/1016 байт) broker исключает на всех уровнях; их точные пути/размеры/SHA сверяются только как provenance исходного inventory176. Их bodies не читаются, не создаются и не архивируются; это не заявление о доставке 176 копий. На remote исходные cache-файлы оставлены как есть. Parent сообщил о сохранении 172 non-cache оригиналов в canonical private.

`verification.json` содержит отдельные счётчики inventory176, required172, cache metadata4, source bodies38, относительные public links, локальный scan и фактические pytest rc. Сырые stdout/rc остаются private. Тесты дополнительно запрещают чтение cache bodies, проверяют отказ при отсутствии обязательного source и при изменении/расширении исключений.

Локальный скан проверяет формы ключей/токенов и локальные идентификаторы; **не является** `app/secret_mask.py` или canonical literal/forbidden guard. Штатного модуля в worker-copy нет; окончательную границу публикации проверяет parent.

**PUBLIC_FILES, ровно 10 путей относительно task:** `.gitignore`, `REPORT.md`, `CHECKS.md`, `calculate.py`, `calculations.json`, `source_index.json`, `preservation_manifest.json`, `test_research.py`, `verify_evidence.py`, `verification.json`.

Verifier сканирует только этот allowlist: старые физические raw/logs могут оставаться после transport-защиты WIP. Это **не** проверка Git index. Parent после подтверждённого private-сохранения уберёт из index только остальные researchartifactpaths (`git rm --cached`, без удаления файлов) и задаст task `.gitignore` allowlist. Worker не выполняет mass deletion/force-add/private archive; `.git` здесь отсутствует, HEAD назначает платформа. Полный private уже сохранён parent; cache-пропуски не надо обходить. Новых lookup/инсталлов/model calls/продуктовых изменений нет.
