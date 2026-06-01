---
name: html-artifacts
description: Generate interactive HTML artifacts instead of markdown
---

# HTML Artifacts

Generate `.html` files when content benefits from layout, color, diagrams, interactivity.

## When to use HTML
- Comparing 2+ options — side-by-side
- Diagrams, flowcharts, architecture schemas
- Dashboards, metrics, status reports
- Reports >100 lines
- Anything the user will share or re-read

## When NOT to use
- Short replies, code, terminal commands
- Disposable summaries

## Rules
1. **Language** — write ALL text content (titles, labels, TL;DR, descriptions) in the SAME language the user is communicating in. User speaks Russian → artifact in Russian. English → English
2. **Single .html file** — CSS in `<style>`, JS in `<script>`, SVG inline
2. **Works offline** — CDN only for Chart.js if charts needed
3. **System fonts** — `system-ui, sans-serif`
4. **Dark-first** — `prefers-color-scheme` for light mode
5. **Responsive** — `<meta name="viewport">`
6. **Readable in 5 sec** — title, TL;DR, then substance

## CSS base
```css
:root {
  --bg: #0e0e12; --surface: #16161c; --surface-2: #1c1c24;
  --border: #2a2a32; --ink: #f1f1f4; --ink-soft: #a8a8b3;
  --accent: #7c3aed; --ok: #22c55e; --warn: #f59e0b; --danger: #ef4444;
  --sans: system-ui, -apple-system, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: light) {
  :root { --bg: #fafaf7; --surface: #fff; --border: #e7e5df; --ink: #1a1a1f; --ink-soft: #555; }
}
```

## Where to save
1. `artifacts/` in project root
2. `docs/artifacts/` if `docs/` exists

## After saving
1. Tell the path
2. `xdg-open <file>` (Linux)
3. In Orchestra: `send_file(path, caption)` to Telegram

## Anti-patterns (NEVER)
- Cards with shadows on gray background
- Gradient hero section
- Emoji as section headers
- Glass morphism, frosted blur
- Generic Tailwind aesthetic

## SVG rules
- `viewBox`, not fixed width/height
- `currentColor` for theme adaptation
- `<text>` not paths — copyable text
- Arrow markers via `<defs><marker>`
