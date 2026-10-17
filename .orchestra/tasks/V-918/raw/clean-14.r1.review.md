## Summary

Reviewed the complete diff between the specified commits and traced quota snapshot handling and `turn ended` consumers. The change removes quota percentages and reset times from the turn-ended status line while keeping quota data available for usage records. `limit_wake` still identifies turn endings by the line prefix and stop reason.

## Findings

### Blocking

None.

### Suggestion

None.

### Question

None.

## Verdict

APPROVED