# item-11

Commit under review (in /home/kesha/orchestra, read-only): `87f4ffd1e875fb3517dee3c6234e248e3b9f5dcd`
Subject / date:
V-672: #V-672: group compaction activity in chat
2026-09-29

The diff reviewed is `git -C /home/kesha/orchestra show 87f4ffd1e875fb3517dee3c6234e248e3b9f5dcd -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between `0ba5a1ba4f1795a1aed995ab5a8b1892e17b6eae` and `59ab498a41b889e1f580f86283277fa8c5b96cb5`, including the backend event logging, dashboard rendering, Telegram filtering, translations, and tests. No files were changed.

## Findings

### blocking

- **A delayed “load full” response can show one agent’s compact log in another agent’s chat.** The button handler fetches asynchronously, then calls `_renderCompactEvent` with the captured `chat` element. Switching agents clears the card map and chat, but the response can arrive afterward and insert the old card into the now-current chat element. This can expose cross-project session data in the UI. In [chat.js](app/static/js/chat.js), invalidate pending requests on chat changes or verify the selected session/card is still current before rendering the response.

## Verdict

NEEDS WORK — address the stale-response cross-agent rendering path.
