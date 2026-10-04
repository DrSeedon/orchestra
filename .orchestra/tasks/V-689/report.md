# V-689 — README GIF

Rebuilt `docs/dashboard-live.gif` from the existing V-686 tour video. The 10 scenes show the task being described, planning, worker launch and status, DONE, review and tests, merge, the task board, quotas, and spend. The GIF has its own English captions; the numbered captions from the narrated video are covered. The last segment dissolves into the same opening frame for the loop.

| Source time | Caption |
|---|---|
| 9.5–12.3 s | You describe the job |
| 13.0–15.8 s | The orchestrator splits the work |
| 17.4–20.2 s | Workers start in parallel |
| 27.0–29.8 s | Follow work and status |
| 32.0–34.8 s | The worker reports DONE |
| 37.5–40.3 s | The orchestrator reviews and tests |
| 42.2–45.0 s | Approved work is merged |
| 47.2–49.8 s | Tasks stay visible |
| 49.7–52.5 s | Track model quotas |
| 59.0–61.8 s | See spend by day and agent |

`ffprobe`: 1100×618, 10/1 fps, 28.2 s, 282 frames, 6,538,535 bytes. Pillow reports an infinite loop (`loop=0`) and 232 colors in the first frame. The contact sheet samples every 3 seconds from 0 to 27 seconds: `dashboard-live-contact.png`. The first and last decoded frames are visually indistinguishable at the loop boundary.

README was not edited. The existing V-686 recording supplied the beginning and all later scenes, so the stand was not started or modified. The render ran over SSH outside the agent cgroup.
