# README insert draft (V-686) — NOT applied to README.md

Two variants for the block that currently shows `docs/dashboard.png` (a mock-up).
Both keep the mock-up file untouched; new files would go next to it.

## Variant A — no upload to GitHub, only committed files (works today)

Commit the files below into `docs/` and replace the current `<p align="center">…dashboard.png…</p>`:

```html
<p align="center">
  <img src="docs/dashboard-live.gif" alt="Orchestra dashboard: a worker reports done, the orchestrator reviews, tests and merges; the quota panel and the daily-spend chart for Claude and Codex unfold" width="100%">
</p>

<p align="center">
  <img src="docs/dashboard-real.png" alt="Orchestra dashboard: chat with the orchestrator, agents panel with models, status and cost, quota bar" width="100%">
</p>
```

Files: `media/dashboard-live.gif` → `docs/dashboard-live.gif` (4.5 MB, 880×417, 41 s loop with English captions),
`media/dashboard-real.png` → `docs/dashboard-real.png` (3200×1880).

Optional third image for the cost/quota features (same pattern):
`media/dashboard-spend.png` (📊 Usage Analytics, 30 days) or `media/dashboard-quota.png` (quota panel with history).
GIF has no sound — no animated image format does (GIF, APNG, animated WebP, SVG).

## Variant B — video with sound (needs one manual upload by the owner)

GitHub plays an MP4 inside a README only if the file was uploaded through the GitHub web UI
and is referenced by its `https://github.com/user-attachments/assets/<uuid>` URL. A `.mp4`
committed to the repo, or a `<video>` tag pointing at a repo path, is not played.

Owner's step (not done by the agent — this publishes the file):
1. On github.com open `README.md` → pencil (Edit), or a new issue draft (do not submit).
2. Drag `media/orchestra-tour-github.mp4` (5.1 MB) into the text area; wait until GitHub inserts a line like
   `https://github.com/user-attachments/assets/1a2b3c…`.
3. Keep that line as its own paragraph in README (a bare URL on its own line becomes a player):

```markdown
<!-- 85-second narrated tour, with sound -->
https://github.com/user-attachments/assets/REPLACE-WITH-UUID
```

Limits: 10 MB per video on a free plan, 100 MB on a paid one; `.mp4`, `.mov`, `.webm`.
`orchestra-tour-github.mp4` is the under-10 MB copy for this reason (the 9.3 MB master is for Telegram).

Recommended combination: Variant A GIF on top (autoplays, silent) + Variant B player below it
("Watch the 85-second tour with sound").
