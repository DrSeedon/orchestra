# Reusable workflow notes

- Post-commit stages can fail after an earlier durable side effect. Preserve completed sub-results on the shared finalization payload before entering later transactions, then make response normalization fall back to that payload when the aggregate result is partial.
- When acceptance names a mutation, keep the regression oracle in the repository and run that named test against the mutation; one-off probes only diagnose the defect.
