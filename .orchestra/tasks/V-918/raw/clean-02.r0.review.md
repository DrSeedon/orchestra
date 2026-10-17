## Summary

Reviewed the complete pinned diff from `8423668d4132a035b8a6e63cafd5b85741b4831e` to `cc5115e31fe4d404aef0520e12cc181b949d702d`, including the tab ordering and default selection code it relies on.

## Findings

- **blocking:** None.
- **suggestion:** None.
- **question:** None.

## Verdict

APPROVED — the change removes recently opened orchestrators from tab ordering while retaining recent history only as a fallback for initial selection. `tabOrder` remains the source of any user-customized order.