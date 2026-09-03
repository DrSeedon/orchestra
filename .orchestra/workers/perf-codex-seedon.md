# perf-codex-seedon

- При hot-version skew строй rollout matrix не только для `old/new`, но и для
  уже развёрнутой промежуточной версии клиента. Dual envelope обязан быть
  безопасно читаем legacy parser и текущим strict parser; недоказанную
  совместимость оформляй как явный fail-closed upgrade state.
- Canonical поля versioned envelope привязывай к exact wire version: наличие
  нового поля без версии не доказывает новый контракт и должно fail-closed.
