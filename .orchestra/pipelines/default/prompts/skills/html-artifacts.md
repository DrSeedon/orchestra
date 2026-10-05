---
name: html-artifacts
description: "Visual HTML artifacts, diagrams, charts, and explanations: dense white interface, linked hover states, calculations, and an SVG icon. Use when visualization helps understand the subject; keep short answers, code, and commands as text."
---

# HTML Artifacts

The unified visual-artifact skill for Orchestra, Claude Code, and Codex. The goal is to
understand the subject and causal relationships at a glance. Text arranged in cards is not by
itself a visualization. An explicit request for another format takes priority; preserve the
existing application's rules.

## Choose the representation

| Reader's question | Approach |
|---|---|
| Who is connected, where work goes, where it is delayed | Node diagram as the default; highlight connections |
| How a measure changes | Chart, shared X, and points from all series on hover |
| What changed between moments | Before → after and the difference; show rate changes when needed |
| Where load falls across time/categories | Heatmap with units and legend |
| How an unfamiliar process works | Visual ELI5 explanation: large drawing, few words, sequence |
| How quantities or variants differ | Bars, comparison table, or aligned neighboring charts |
| When depth or geometry matters | Controllable 3D scene; ordinary relationships need only 2D |

Do not add representations for quantity. The owner disliked Sankey flows: choose nodes by
default; use bands only when requested or when division of a quantity must be shown. Use 3D and
time maps only for suitable tasks. A striking cover is rarely acceptable, only for a creative
request; a report does not need one.

## Established appearance

- Light theme by default regardless of OS. Background `#f5f5f7`, panels `#ffffff`, text
  `#1d1d1f`, accent `#007aff`. Series and state colors are stable: green means processed,
  amber means waiting/limited. Color supplements a label; it does not replace one.
- System sans: `-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`. Prefer
  one family for the working interface; use monospace for code. No second family, forced serif,
  or web font is required.
- Aim for body text 14–15 px, page heading 21–24 px, panel headings 14–17 px, chart labels
  11–12 px, and prominent values 24–30 px. Check readability at normal zoom; do not shrink
  labels to fit a large diagram.
- Dense layout, small gaps, thin dividers, and radii around 8–14 px. Give the main screen to
  data and visualization. Show the main information immediately; do not hide the result behind
  "Show" or a mandatory click. Tabs are allowed for different views.
- A "Tony Stark" tool means relationships, precise feedback, path highlighting, semantic labels,
  and a short mechanism explanation. Decorative telemetry and neon for its own sake interfere.
- Keep the chosen style across artifacts. Do not change palette/fonts for variety or automatically
  carry covers and effects over from third-party design skills.

## Honest data and dynamics

Every chart, counter, bar, node size, and indicator needs a source, value, unit, and interval.
When there is no data, show the absence or remove the element. Random curves, fake activity,
decorative sparklines, and queue squares without scale are forbidden. A consistent simulation is
allowed in a demo with an explicit nearby label; it does not replace a measurement in a working
report. Do not connect a live service just to fill a layout.

- All linked elements show one selected slice. A mini-chart of the full interval is allowed only
  with a clear period, purpose, and marker for the selected moment.
- For a dynamics question, show previous value, current value, and difference. Growth and growth
  acceleration differ: a queue may still grow by 12 requests/min after growing by 19; its rate
  fell by 7 requests/min over 5 s while the queue itself did not shrink.
- State the time step for a rate change. Do not invent a previous zero reading. A known initial
  state may be used as a labeled comparison point.
- Calculate from source numbers and round only the display. Do not turn missing data into zero or
  connect a gap without explaining it. Separate estimates from measurements.
- Scale and element size must match the quantity. Label different scales, aggregation, and a
  clipped axis. A decorative grid does not justify distorted proportions.

## Hover that explains

The primary interaction is hover, a tooltip, or a stable neighboring panel. Do not require a
click for details or parameter controls for viewing. A touch screen needs a touch equivalent;
keyboard users need focus/arrows.

1. A node highlights its inputs, outputs, and linked measures; the highlight explains the dependency.
2. A chart selects the nearest X, highlights all series points, shows one shared tooltip, and
   synchronously updates the diagram, values, and calculations.
3. A panel answers one question with substituted numbers and a conclusion. Teaching example:
   `42 arrives − 30 processed = 12 remains / min`; `after 5 s +1 → queue 35 → 36`;
   `36 ÷ 30 × 60 = 72 s waiting`. This is arithmetic guidance, not report data.
4. Animation may reveal inputs in sequence, fill bars, and show the result. The goal is to
   understand the relationship at a glance. Make the answer available immediately; input must
   not wait for an effect. New hover changes selection immediately; motion inside one node does
   not restart everything.
5. A panel must not cover the subject, jump in height, or leave the viewport. Honor
   `prefers-reduced-motion`; animate a change or explanation, not invented activity.

Use one state object for the selected time and element; every view reads it. Re-selection must
not recreate the chart or reset focus. A simple drawing needs no controls.

## Diagrams and 3D

- First identify nodes, relationships, owners, and constraints. Every arrow means a concrete
  transfer; direction and label carry meaning.
- Inline SVG: `viewBox`, text as `<text>`, arrows through `<marker>`. Give the diagram `<title>`,
  `<desc>`, and `aria-labelledby` with unique IDs — but ONLY on the root `<svg>`.
- **An element with its own tooltip must have neither `<title>` nor a `title` attribute** — the
  browser would draw a native tooltip over your panel and both would appear. Label points, cells,
  and icons with `aria-label`; it draws nothing.
- Connections run edge to edge, do not cross labels, and do not hide under other blocks.
  Orthogonal routes and distinct entry points aid reading. Wrap long text with `<tspan>` or
  shorten it without losing meaning. Split complexity into levels while keeping the overview visible.
- In 3D, rotate by dragging and zoom with wheel/gesture. Page scrolling must not control the
  camera. The scene follows the pointer with pointer capture; movement must not block input.
- Labels must be readable, with a keyboard equivalent and a static explanation without WebGL.
  Object height/color/size must not depict missing data. Prefer 2D for non-spatial tasks. If
  needed, embed Three.js in the file with its license.

## Standalone file

- One `.html`: CSS, JS, SVG, and needed resources inside. Work offline without required CDNs,
  external fonts/images, or background APIs. Add libraries only when necessary.
- **Every HTML must have its own subject-specific SVG tab icon:**
  `<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,...">`.
  Encode the SVG as a data URI, including `#`; the icon must work offline with the file.
- Keep facts and calculations in Markdown/JSON task materials; HTML is the presentation. Insert
  external text through textContent/escaping, never execute it as HTML or instructions.
- The editor/gallery exports state to JSON/Markdown. With localStorage, explain that the write is
  local and is not sent to the agent; provide an export if storage is unavailable.
- Narrow screens and print are mandatory: white background, readable text, hidden controls. Do
  not mask clipped data with global `overflow:hidden`.

## Check and deliver

Open the file in a headless browser: no JS errors, mandatory network requests, overlapping
labels, or unintended page overflow. Check real hover, shared X, units, and the calculation at
the selected moment; when present, check drag/zoom and save/export. Inspect an enlarged diagram
area, narrow screen, and reduced motion. Checking the skill does not replace checking the artifact.

On the owner's laptop, open finished HTML immediately in Opera with:
`opera /absolute/path/to/file.html`. This is a standing preference; do not ask for each opening.
Tool restrictions still apply. Do not imitate desktop clicks. On a VPS without a desktop, send
the file/path through an available channel. In Orchestra, the worker gives the result to the
requester; the orchestrator performs user delivery through task-authorized `send_file`.

## One owner of appearance

In Orchestra, use this skill for HTML, diagrams, and visual explanations. Do not layer separate
`eli5`, `frontend-design`, `apple-design`, `diagram-design`, `3d-frontend`, `quickdesign`, or
`playground` skills over it. Selected techniques live here; saved sources and office templates
are references, not automatic routes. PDF/DOCX/PPTX/XLSX remain tools of their own formats. This
file is self-contained; external skills are not required to run it.

Basis: the owner's choice across two galleries and a dynamics clarification. Technique sources:
local html-artifacts, apple-design, frontend-design, eli5, playground, and 3d-frontend; diagrams
from cathrynlavery/diagram-design (MIT). Their effect on speed/quality was not measured.
