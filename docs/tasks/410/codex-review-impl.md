<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The paid route and pricing happy paths are wired correctly, but stale catalog eligibility can block the new model for existing deployments and malformed paid usage costs can corrupt accounting.

Full review comments:

- [P2] Recompute cached eligibility for newly admitted routes — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/add-glm53-flash/app/routes/system.py:439-444
  When an existing cache row was created before this allowlist change, GLM can retain `harness_eligible: false`; `apply_model_catalog()` re-evaluates and registers it, but this endpoint still returns the stale false value. The catalog UI then disables both toggles, preventing users from enabling dashboard visibility until a manual refresh; recompute eligibility instead of trusting stale cached false.

- [P2] Reject invalid paid usage costs before accounting — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/add-glm53-flash/app/harness/llm.py:338-338
  For paid routes this condition accepts any value parseable by `float`, including negative or non-finite values such as `-0.01` or `NaN`; `HarnessBackend._accumulate()` adds them directly to cumulative cost, causing undercounted or poisoned usage accounting. Validate paid costs as finite and non-negative while retaining the free-route zero-cost check.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens
