## Summary

Reviewed the complete diff from `3fb1221f493dfe89e2542d642402e26bc3d44605` to `ca7e561d79853eeac2142e5835c78e9f2b07ba36`.

## Findings

### Suggestion

- In `render_read`, truncation is detected with `len(raw_lines) > MAX_LINES_READ`, but the limit applies to wrapped display rows. A single long input line can fill all 25 rows and be cut off with no truncation indicator. Track whether wrapped rows were omitted and show the indicator in that case.

- `WRAP_COLS = 90` can exceed the available image width at the new 16px font size. The text area is about 748px wide, while 90 DejaVu Sans Mono characters are wider than that, so wrapped lines can still be clipped. Choose the wrap limit from the font metrics and available width.

## Verdict

NEEDS WORK