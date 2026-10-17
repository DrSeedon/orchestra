## Summary

Reviewed the complete diff from `277b85e…` to `aa61b31…` and checked the Read, Grep, and Bash image-rendering call sites. No files were changed.

## Findings

### Suggestion

- **Read truncation can be silent.** In [app/diff_image.py](/home/kesha/v918-work/v918-bad-cand-08.r0-hfkikd1m/app/diff_image.py:230), a single long input line can wrap to more than 25 display rows, then be clipped to `MAX_LINES_READ`. But `truncated` only checks whether the number of source lines exceeds 25, so this case gets no truncation marker. Check whether wrapped display rows were omitted as well.

- **Grep lines are clipped, not wrapped, and clipping can hide the match.** At [app/diff_image.py](/home/kesha/v918-work/v918-bad-cand-08.r0-hfkikd1m/app/diff_image.py:284), long result lines are shortened to fit the nominal character limit. If the match falls beyond that limit, the image omits it; a long path prefix can also exceed the limit by itself. This misses the requested word wrapping and makes some grep results unreadable.

- **Bash’s “more lines” count is inaccurate for wrapped output.** At [app/diff_image.py](/home/kesha/v918-work/v918-bad-cand-08.r0-hfkikd1m/app/diff_image.py:350), the marker counts omitted source lines, but the renderer limits wrapped display rows. A single long source line can be cut into 30 rows while the marker reports `+0 more lines`. Track omitted display content or report truncation without an inaccurate count.

## Verdict

NEEDS WORK