# retro-01

Commit range reviewed: `git -C /home/kesha/orchestra diff 4b4ac8626651171b987a33194fd246dc42d6a5e8...cbb593bea9e5514e3d7d75c0f2ccc5cb0fa37526 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`
Review date: 2026-09-07.

## Reviewer output (verbatim)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Обнаружен blocking-риск ложного снятия тестов с merge-гейта. Выражение `-m` и CI-шарды настроены корректно; проверка пустого исходного набора также реализована через `ValueError`.

## Findings

- blocking: `tests/conftest.py:326-333` — фикстура `page` слишком общее имя. Любой небраузерный тест, объявивший локальную фикстуру `page` с другим смыслом, попадёт в `browser` через `fixturenames` и будет исключён из блокирующего набора. Та же проблема применима к `browser_context` и `dashboard_browser` при совпадении имён. Автоматическая классификация должна опираться на однозначные имена/маркер владельца, иначе это может снять реальные проверки.

## Verdict

NEEDS CHANGES.

