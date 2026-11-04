# sanitized-publication-copy

This status applies to **every artifact in this task directory**, including old
reports, logs, refresh artifacts, snapshots, diffs, numeric `.exit` files and
checksum inventories. Only identifying Hub account/host/workspace paths were
replaced; publication notices and audit metadata were added. Numeric `.exit`
files and machine-readable source hash inventories keep their original format.

Root preserved the raw originals plus SHA/byte metadata at
`private/tasks/V-1277/originals/manifest` (root-private). This worker did not read
that directory or manifest. Original artifact hashes/bytes in
`publication-manifest.json` describe the worker's pre-sanitization copies and
can be compared by root with its private archive.

Neutral replacements:

- Absolute copied checkout root → `<WORKSPACE>`.
- Hub account home prefix → `<ACCOUNT_HOME>`.
- Account identifiers, including pytest directory names → `<ACCOUNT>`.
- Hub host identifier → `<HOST>`.
- Workspace identifier outside a full path → `<WORKSPACE_ID>`.

Portable system paths and variable references such as `/usr/bin`, `$HOME` and
`$PWD` remain intact. Paths inside sanitized diagnostics are display placeholders,
not reproduction locations. **All original failures, exits, outputs and limitations
remain recorded**. In particular, the warning length **665** and limit **600**
refer to the raw original run; the shorter displayed path does not change them.
Historical imported paths now display as `<WORKSPACE>/app/...`; root verifies the
actual imported host path, HEAD, CLAUDE symlink and host tests separately.

The two product prompts, compiled CSS and functional tests were not edited for
this publication correction. Product before/after hashes are equal and are
recorded in `publication-manifest.json`. No functional tests, model/provider
calls, live infrastructure checks or root-private reads were performed.
