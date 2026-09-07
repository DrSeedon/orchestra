<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, SHA проверили, а режим файла забыли — классика 🧩

## Summary

В diff есть 3 blocking-находки. Проверка тестов не выполнена: окружение не содержит `dotenv`, все 8 тестов упали на setup.

## Findings

blocking: app/review_coverage.py:108 — карта фиксирует только blob SHA и игнорирует file mode, поэтому обычный файл можно заменить на symlink с теми же байтами, и subset-ветка пропустит непроверенное изменение → сохранять и сравнивать mode вместе с dst-sha

blocking: app/db.py:3324 — `review_receipt_reserve()` использует `setdefault`, поэтому явно переданный `None` для любой новой `NOT NULL` колонки попадёт в INSERT и вызовет `sqlite3.IntegrityError` → нормализовать значения через `values[key] = values.get(key) or ""`

blocking: app/mcp_stdio.py:4479 — для cross-worker ревью квитанция получает `task_id` владельца, но `_write_delta_attestation()` читает `task_id` и worktree вызывающего подписанта; у оркестратора обычно нет task, поэтому `record_review_outcome(outcome='attested')` всегда откажет → передавать в attestation owner worktree/task из квитанции

## Verdict

Изменение некорректно: subset-проверка допускает смену семантики файла через mode, а разделённый signer ломает attestation-сценарий. Иара SQLite ещё и ждёт NULL там, где его запретили — очень последовательная проверка, почти как охрана с ключом от собственной двери.
