# #321 — weekly quota trajectory preview

## Durable result

`docs/artifacts/quota-runway-controller.html` now presents the quota as a 168-hour burn trajectory:

- `elapsed = W - h`, `B = 99 - reserve`, and `target(h) = B × elapsed / W` are calculated live.
- `u_eff` is named as reported utilization plus unsettled reservations; the exact dispatch gate is shown as `u_eff + q95(next turn) + guard ≤ 99 − reserve`.
- The 2D SVG uses X for week progress toward reset and Y for usage. It draws target, illustrative Sol/Luna lead corridors, hard-fit lines, colored normal / Sol HOLD–Luna ALLOW / both HOLD zones, and the current point.
- Current usage and hours-to-reset are the two large controls. Readouts, reasons, lane cards, lines, zones, and point update together.
- Spark is explicitly separate and is not connected to the Codex primary slider.
- The old main “Пороги сегодня” mode switch and central static 95/98 map logic are gone. A small comparison table retains static policy only as context.
- The `target + 10 pp` Sol and `target + 15 pp` Luna corridors, reserve `1 pp`, and q95/guard examples are marked as operator-configurable illustrative defaults before #318 calibration—not measured facts or a production contract. The page explicitly says it does not implement the full #285 p50/p90/p95 moving-block bootstrap.

## Acceptance probes

The defaults and edge probes use the illustrative values in `source.json`:

| case | inputs | expected lane result |
|---|---:|---|
| early 80 | `usage=80`, `h=160` | Sol HOLD, Luna HOLD |
| late 80 | `usage=80`, `h=8` | Luna ALLOW (Sol also fits) |
| Sol corridor crossing | `usage=85`, `h=40` | Sol HOLD, Luna ALLOW |
| Luna corridor crossing | `usage=90`, `h=40` | Sol HOLD, Luna HOLD |
| hard fit near 99 | `usage=98`, `h=0` | Luna HOLD from hard fit |

## Verification

Command:

```text
uv run python - <<'PY' ... Playwright Chromium ... PY
```

The headless run loaded the file offline in light and dark color schemes at 1440×1200 and 390×900. It exercised all five cases above, checked live target output, checked `body.scrollWidth <= window.innerWidth`, and collected `console`/`pageerror` events.

Result:

```text
PASS light (1440, 1200) overflow 1440
PASS light (390, 900) overflow 390
PASS dark (1440, 1200) overflow 1440
PASS dark (390, 900) overflow 390
```

`node --check` on the extracted inline script, `python3 -m json.tool` on `source.json`, and `git diff --check` also passed. Full-page light and dark screenshots were rendered from Chromium for visual inspection; the trajectory, zones, lane cards, formula, caveat, comparison, and source link were visible without overflow.

## Review route

One targeted `gpt-5.6-luna` review ran against the exact committed diff. It found one blocking evidence contradiction and two non-blocking evidence/visual issues; all three were addressed in the follow-up commit. Luna is the same Codex model family as the author/runtime and is therefore non-independent; no Sol or Opus escalation was requested or performed. The reviewer artifact and route record are `docs/tasks/321/codex-review-luna.md` and `docs/tasks/321/codex-review-impl.md`.
