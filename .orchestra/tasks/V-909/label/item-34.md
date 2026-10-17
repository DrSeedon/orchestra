# item-34

Commit under review (in /home/kesha/orchestra, read-only): `a8d2e20ad49d3f107717055567afe824970f457d`
Subject / date:
V-582: #V-582: харнес-маршруты из живого каталога, допуск по данным провайдера
2026-09-17

The diff reviewed is `git -C /home/kesha/orchestra show a8d2e20ad49d3f107717055567afe824970f457d -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `3d862500219a90eaf2c26519ced95e6db3e1db64` to `e01fdc8b3351152ae2a60ec4a3136e1e1c13cf61`, including the harness admission changes and new route probe. No blocking defects found.

## Findings

### Suggestion

- [scripts/probe_free_models.py](scripts/probe_free_models.py:190): `--budget-seconds` is checked only before each route. An in-progress route can exceed the deadline by up to its request timeouts and retry sleeps, and the catalog fetch itself is outside that deadline. The report can therefore take substantially longer than the configured budget. Consider bounding each request and retry by the remaining time, or describing this as a between-routes budget.

- [scripts/probe_free_models.py](scripts/probe_free_models.py:182): `--model` converts the requested IDs to a set, so repeatable model arguments are probed in nondeterministic order. Keeping the supplied order would make bounded runs and reports reproducible.

## Verdict

APPROVED — the admission check uses the provider catalog record and rejects missing, ineligible, and unavailable routes.
