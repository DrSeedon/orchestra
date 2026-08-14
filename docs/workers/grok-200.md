# grok-200

- Unifying a duplicated helper: re-export the function object (`from app.x import fn`), do not copy the corrected body. A test that builds fixture paths from the same helper it asserts against stays green when that helper is mutated — pin expected directory names as literals.
- A question to the orchestrator currently trips the fan barrier (platform bug, 14.08). Ask only when actually blocked, not “just in case”.
