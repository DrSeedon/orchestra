# quota-panel-merge

Memory: updated — in this project `usage_snapshots.ts` can arrive from SQLite as ISO strings OR numeric strings (e.g. `1999999200.0`), so timestamp parsing must accept both string ISO and stringified epoch before filtering by window.
Memory: updated — API helper can already return parsed objects; frontend helpers should accept object and avoid unconditional JSON.parse; mixed `ts` in DB needs explicit dual-branch filtering for ISO/numeric values.
