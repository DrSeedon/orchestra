## Summary

Reviewed the complete diff from `26c56db2904ab32c5ce439d9bda12b63cb4ba347` to `1490601ca69213d39973db5bec2478dd824dcb13`.

## Findings

### Suggestion

- In compact mode, a tool or tool result can end an active stream by setting `streamBubble` and `streamContent` to `null` and `''`, but it leaves `streamPending` and the scheduled animation frame intact ([app.js](/home/kesha/v918-work/v918-bad-cand-09.r1-zv_h5hg8/app/static/js/app.js:2169), [app.js](/home/kesha/v918-work/v918-bad-cand-09.r1-zv_h5hg8/app/static/js/app.js:2194)). If another stream event arrives before the frame runs, buffered text from the prior response can be rendered into the new bubble. Clear the pending buffer and cancel the frame when this compact-mode path ends a stream.

## Verdict

NEEDS WORK