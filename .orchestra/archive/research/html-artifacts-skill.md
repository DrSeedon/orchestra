# Research: HTML Artifacts Skill for Claude Code

## 1. How Claude.ai Artifacts Work

**Architecture**: Artifacts run inside an `<iframe>` on `claudeusercontent.com` (separate origin from claude.ai). Communication via `window.postMessage()`.

**Triggers**: Content is substantial (>15 lines), self-contained, reusable/iteratable → artifact. Short/conversational → inline.

**MIME types**: `application/vnd.ant.react`, `text/html`, `image/svg+xml`, `application/vnd.ant.mermaid`, `application/vnd.ant.code`, `text/markdown`, `text/plain`, CSV, JSON, LaTeX, Graphviz.

**Sandbox (CSP)**:
- `connect-src` only allows `cdn.jsdelivr.net` (Pyodide) → no arbitrary fetch
- `object-src 'none'` — no plugins
- No `localStorage`/`sessionStorage`
- iframe: `allow-scripts allow-same-origin allow-forms`

**Pre-bundled libraries**: React 18, Tailwind CSS, shadcn/ui (Radix), Lucide React, Recharts, Three.js, DOMPurify.

**Source**: [Reid Barber reverse engineering](https://www.reidbarber.com/blog/reverse-engineering-claude-artifacts), [ShareDuo guide](https://www.shareduo.com/blog/claude-artifacts)

## 2. Thariq Shihipar's "Unreasonable Effectiveness of HTML"

**Core argument**: Markdown limits agents that have outgrown the format. HTML enables spatial layout, interactivity, color-as-meaning, non-linear navigation, and shareability.

**When HTML**: comparisons, spatial info (diffs, flowcharts, timelines), interaction, reference material with non-linear nav, color/hierarchy, one-off editors, shareable docs, >100 lines.

**When Markdown**: short replies, code-only, terminal commands, quick summaries, files needing clean git diffs.

**Cost**: HTML = 2-4x tokens of markdown equivalent. Worth it for deliverables, not for disposable.

**9 categories**: Exploration & planning, Code review, Design & prototypes, Diagrams, Reports & research, Decks, Custom editors, Matching style, (general).

**Source**: [thariqs.github.io/html-effectiveness](https://thariqs.github.io/html-effectiveness/), [Simon Willison writeup](https://simonwillison.net/2026/May/8/unreasonable-effectiveness-of-html/)

## 3. Existing Skill: dogum/html-artifacts

**Structure**: `SKILL.md` (entry point) + `references/` folder (8 category-specific files loaded conditionally).

**Key design decisions**:
- Description is the trigger — extremely aggressive ("even if they don't explicitly say HTML")
- Category index with per-category reference files
- Universal rules enforced on ALL artifacts (self-contained, offline, responsive, real layout, readable, tasteful, editors export back)
- Two environments: Claude Code (save .html, offer to open) vs Claude.ai (artifact system)
- Anti-pattern list: "AI default look" (cards everywhere, gradient heroes, emoji headers, glass morphism)

**Default CSS palette** (light+dark, `prefers-color-scheme`):
```css
--bg: #fafaf7; --surface: #fff; --ink: #1a1a1f; --ink-soft: #555560;
--rule: #e7e5df; --accent: #8b5cf6;
/* dark: */
--bg: #0e0e12; --surface: #16161c; --ink: #f1f1f4; --ink-soft: #a8a8b3; --rule: #2a2a32;
```

**Typography**: Charter/Iowan/Source Serif (serif for docs), Inter/system-ui (sans for tools), JetBrains Mono (mono). 17px body, 1.55 line-height, 60-75ch max-width.

## 4. HTML Best Practices for Self-Contained Files

**CSS**: Embedded `<style>` with CSS custom properties. NOT Tailwind CDN (100KB+, "not for production"), NOT inline styles (no :hover, @media).

**Charts**: Chart.js (~200KB, best general), uPlot (~50KB, best for time series), frappe-charts (~60KB, SVG-based). Avoid D3 (~300KB) unless custom viz needed. Avoid Mermaid (~1.2MB) for simple diagrams.

**Dark theme palettes**:
- Vercel Geist: `#000/#111/#1f1f1f/#ededed/#888/#fff`
- Linear-inspired: `#0f0f13/#16161d/#2a2a3a/#e2e2e8/#6b6b80/#7c3aed`
- GitHub Dark: `#0d1117/#161b22/#30363d/#e6edf3/#8b949e/#58a6ff`

**Interactive patterns (zero-JS or minimal JS)**:
- Tabs: `<input type="radio">` + CSS `:checked`
- Accordion: `<details><summary>` (native HTML)
- Sortable tables: 20 lines vanilla JS
- Search/filter: `input.oninput` + display toggle

**Print-friendly**:
```css
@media print {
  :root { --bg: #fff; --surface: #f5f5f5; --text: #000; }
  button, .no-print { display: none !important; }
}
```

**SVG diagrams**: Inline SVG > Mermaid CDN. Use `viewBox`, `currentColor`, round numbers, `<g>` grouping.

**Responsive**: `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))` — adaptive without @media.

**Size targets**: <50KB bare, ~250KB with Chart.js, ~100KB with uPlot, 500KB reasonable ceiling.

## 5. Key Design Decisions for Our Skill

### What makes ours different from dogum/html-artifacts:

1. **Dark-first** — our user preference is dark theme, not light. Default to dark with light via `prefers-color-scheme`.
2. **Orchestra integration** — `send_file` to Telegram when in Orchestra context.
3. **Aggressive self-containment** — zero CDN deps by default (system fonts, inline everything). CDN only for charts.
4. **Project-aware** — detects project type, reads existing design tokens if available.
5. **Russian + English triggers** — билингвальные триггеры.
6. **Quality guardrails** — explicit anti-patterns list baked into skill.
7. **Reference architecture** — full reference docs per category, not just SKILL.md.

### Categories we support:
1. Exploration & comparison (side-by-side options)
2. Code review & PR writeups (annotated diffs)
3. Reports & status updates (weekly, post-mortem, incident)
4. Diagrams & architecture (inline SVG)
5. Explainers & docs (concept/feature deep dives)
6. Dashboards & data viz (KPIs, charts, metrics)
7. Decks & presentations (arrow-key slides)
8. Custom editors (triage, flags, prompt tuner)
9. Plans & specs (implementation plans, design specs)
