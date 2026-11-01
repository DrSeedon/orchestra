# V-1172 read-only disk QA scope inventory

Snapshot scope is limited to the roots named by the V-1170 full receipt/script and one-level `/tmp/orchestra-v1171-parent-*` / `neighbors-*` globs. `du -x -s -B1` succeeded (rc 0, empty stderr) on every listed exact root. Raw paths, stat details, per-root command output and proc-scan counters are in the ignored private record `candidates.json`.

| Scope alias | Allocated bytes | Provenance and completion evidence | Owner / device / root symlink | CWD/open-FD scan | Remaining unknowns |
|---|---:|---|---|---|---|
| V-1170 `home` | 80,248,832 | `run_tests.py` env root; full run receipt captured 17:54 UTC, elapsed 509.117s, rc 1; final log summary present | kesha / same device / no | No match among readable entries | Descendant file identities/types/content and descendant symlink targets not inventoried |
| V-1170 `codex-home` | 5,115,904 | Same run | kesha / same / no | No match among readable entries | Same |
| V-1170 `xdg-config` | 12,288 | Same run | kesha / same / no | No match among readable entries | Same |
| V-1170 `xdg-cache` | 1,179,648 | Same run | kesha / same / no | No match among readable entries | Same |
| V-1170 `xdg-state` | 4,096 | Same run | kesha / same / no | No match among readable entries | Same |
| V-1170 `tmp` | 626,688 | Same run | kesha / same / no | No match among readable entries | Same |
| V-1170 `pytest-base` | 2,533,326,848 | Same run; pytest temporary tree configured by `run_tests.py` | kesha / same / no | No match among readable entries | Descendant worktree/source-like content and symlink targets not inventoried |
| V-1170 `pytest-cache` | 20,480 | Same run | kesha / same / no | No match among readable entries | Descendant file identities/types/content and descendant symlink targets not inventoried |
| V-1171 `parent-A` | 28,672 | One of three `mkdtemp` roots in `accept.py`; control receipt records baseline/original-seam/skip-durable rc 0/1/1, but no path-to-mode mapping | kesha / same / no | No match among readable entries | Exact control association and descendant contents/symlinks unknown |
| V-1171 `parent-B` | 4,096 | Same three-root set; exact mapping unknown | kesha / same / no | No match among readable entries | Same |
| V-1171 `parent-C` | 28,672 | Same three-root set; exact mapping unknown | kesha / same / no | No match among readable entries | Same |
| V-1171 `parent-D` | 28,672 | Found by the same one-level prefix glob; no creator evidence in supplied script/receipt | kesha / same / no | No match among readable entries | Provenance, files/source-like items and descendant symlink targets unknown |
| V-1171 `neighbors` | 10,186,752 | `accept.py` neighbors pytest `--basetemp`; receipt says rc 0 | kesha / same / no | No match among readable entries | Descendant worktree/source-like content and symlink targets not inventoried |

V-1170 listed roots total 2,620,534,784 allocated bytes. V-1171 discovered roots total 10,276,864 bytes, including the unproven fourth parent; all 13 roots total 2,630,811,648 bytes. V-1171 receipt also records the instruction-contract command rc 0 and three control subprocess results; the neighbors log ends with 80 passed and 4 subtests passed. The V-1170 full command completed with rc 1, not a green full suite. File modification times for the PNG check are not treated as completion proof.

The candidate discovery was bounded: 8 receipt-listed V-1170 roots, 4 matches for the single-level V-1171 parent glob and 1 for the neighbors glob; no recursive/global find or unrelated `/tmp`, cache, or home inventory was run. All exact roots and their path components were non-symlinks at inspection; this does not establish whether descendants contain symlinks or identify any original targets.

The `/proc` check inspected 260 numeric PIDs' cwd links, read 81 fd directories and 1,370 FD links, and found no candidate-path references among accessible entries. It recorded 392 permission-denied accesses and 2 process-disappearance races, so it is not a complete host-wide reference proof. `du` and proc results were taken during the same snapshot; no file contents or recursive names were read.

`df` on `/` before inspection reported 305,621,368,832 used / 5,273,268,224 available bytes; after inspection at 18:08 UTC it reported 305,680,551,936 used / 5,214,085,120 available. The task-provided prior snapshot reported 305,549,336,576 used / 5,345,300,480 available. These are filesystem snapshots only and do not attribute usage to processes or candidate roots.
