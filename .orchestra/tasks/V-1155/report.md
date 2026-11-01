
## V-1155 — один bounded metadata pass

Свежий df 07:43:03Z сравнен с V-1154 final 07:40:26Z: used 292040536064→292578680832 B (+538144768), Use 94→95%. После pass (07:47:27Z) used 292736286720 B, Use 95%; scan-window delta +157605888 B не приписан процессу/категории. Снимки: `.orchestra/private/V-1155/df-start.txt`, `df-after-scan.txt`.

Metadata-only по 67 выбранным V-1154 roots, cutoff 07:40:00Z: 2690 recent file-path records, 443 directory records; тела не читались, symlink targets не обходились. Root scan/changed-root `du -x -s -B1`: 0 errors; 9 changed categories remeasured. Baseline du at 07:13:52Z предшествует cutoff и V-1154 final df, поэтому category delta охватывает более длинный интервал; recent mtime и current allocated не дают per-file size delta. Du deduplicates hardlinks per root; totals across roots and path/FD records не складывались в unique allocated bytes.

| scope | baseline allocated @07:13:52Z | current allocated @07:47:27Z | delta | recent path records / max allocated | current writer PID/task evidence | evidence | coverage |
|---|---:|---:|---:|---:|---|---|---|
| W01 worktree | 3067838464 | 3067949056 | +110592 | 1910 / 23937024 | none | D,M,P,S | no per-file baseline |
| W02 worktree | 1791885312 | 1791909888 | +24576 | 1 / 20480 | PIDs 3426817, 3858200; files not recent; no CLI-task ancestor match | D,M,P,S | no per-file baseline |
| W04 worktree | 1144459264 | 1144655872 | +196608 | 1 / 8192 | none | D,M,P,S | no per-file baseline |
| W06 worktree | 484560896 | 507891712 | +23330816 | 43 / 86016 | none | D,M,P,S | no per-file baseline |
| C07 main checkout | 14441312256 | 14481379328 | +40067072 | 76 / 2105344 | none | D,M,P,S | no per-file baseline |
| C08 main checkout | 63797882880 | 64315703296 | +517820416 | 634 / 3010560 | PID 3971056, 2 refs/81920 B; files not recent; no CLI-task ancestor match | D,M,P,S | baseline predates cutoff |
| K02 cache | 137474048 | 137535488 | +61440 | 5 / 4096 | none | D,M,P,S | no per-file baseline |
| D01 service-data category | 631078912 | 631013376 | −65536 | 2 / 45056 | PID 764; recent refs 65536 B; category decreased | D,M,P,S | no per-file baseline |
| E01 own V-1154 evidence | no baseline | 33460224 | n/a | 18 / 135168 | none | D,M,S | baseline unavailable |

`D`=`metadata-scan-summary.json` (same-level du); `M`=`recent-file-metadata.jsonl`; `P`=`writer-file-join.json` / `writer-process-correlations.json`; `S`=`scope-id-map.json`. Nine writable FD refs belong to four PIDs; 245760 B is the sum of FD stat extents before inode de-duplication, not disk growth. PID 764 writes recent D01 entries while the category net delta is negative. W01 has 1910 recent paths but only +110592 B category delta and no current writer. C08's large delta is only relative to the earlier 07:13 baseline; recent-file paths have no per-file baseline, while the two currently open writable files are older than cutoff. No specific current writer/file proves the +538144768 B rise after 07:40.

Coverage: 67 selected baseline roots (worktree/project roots, baseline-large cache/data/tmp roots and own V-1154 evidence); live DB showed 5 active session scopes inside these roots, but none linked to the four writer PIDs through `cli_pid` ancestry, so session scope was not treated as writer attribution.  smaller baseline categories, protected cache roots, Trash, and the V-1151 symlink-target temp scope were excluded. Process snapshot: 275 PID entries, 9 writable refs/4 PIDs; EACCES counts cwd=193, fd-dir=192, fd-links=35; five UV processes skipped without interaction. Exact root and recent paths remain local under `.orchestra/private/V-1155/`. No recommendations or cleanup were performed.

## Supplemental aggregate du and no-baseline file metadata

One whole-root read-only `du -x -s -B1` snapshot captured at 08:57:15 CET; matching current physical filesystem was `/dev/sda1` ext4. No files were opened for content, and no symlink target was traversed.

| scope | V1154 baseline B | supplemental current B | delta / coverage | current writer evidence |
|---|---:|---:|---|---|
| repo `.orchestra` incl private | no baseline | 3971616768, RC=0 | current only | top current large-file metadata in private; no matched writable FD |
| `orchestra/data` | 35182477312 lower bound | 35190960128 lower bound, RC=1 | +8482816, not comparable: one Permission denied, current denied path differs | MainPID 3102453 writes DB/WAL/SHM; DB allocated 6688456704 @08:57→6689820672 @09:13 (+1363968 B); WAL/SHM allocated unchanged |
| `~/.cache` aggregate | 43261157376 | 42397347840, RC=0 | −863809536; prior pip+Electron cache allocated reclamation was 863875072 B; difference 65536 B unassigned | UV baseline 34397569024, current 34397573120 (+4096); UV commands/process-control untouched |
| `~/.local/share` | no baseline | 13484736512 lower bound, RC=1 | three Permission denied; includes Trash aggregate, untouched | PID 3145900 wrote recent file-ID `1df1909c3b8d` (1086902272 B) at 08:04Z; absent by 09:09. PID 3149524 (`python3`) had a writable FD to recent local-share path-ID `e17ea392746c` (274432 B) at 09:09; CWD matched seedon session scope, no CLI ancestry |
| `/tmp` aggregate | 7687278592 lower bound | 7580995584 lower bound, RC=1 | −106283008, not comparable: prior V1151 cleanup and 13 Permission denied | no global writer attribution |
| 7 observed `CODEX_HOME` roots | no baseline | 1863266304 B total | individual current sizes in private | active Codex processes hold writable FDs on recent runtime-home files; see IDs below |

Current DB/WAL/SHM `du` sizes at 08:57:15 CET were respectively 6688456704, 14794752 and 32768 B. The current service MainPID 3102453 had write-capable FDs for all three at the targeted metadata check; no per-file baseline was available.

| runtime-home ID | active PID | recent open-file path ID / allocated B | session context |
|---|---:|---|---|
| H1 | 3109026 | `b471ab46075d` / 227516416 | CWD matches an active session scope; no CLI-PID ancestor match |
| H3 | 3103143 | `732f834ea37e` / 4206592 | same |
| H5 | 3103494 | `658f8cb45986` / 227762176 | same |
| H7 | 3107028 | `e6664dd4bd2d` / 8671232 | CWD scope matched; no CLI-PID ancestor match |

At 09:09:36 CET, PIDs 3109026/3103143/3103494/3107028 (`codex`) had write-capable FDs on recent-mtime CODEX_HOME files, largest per home: 227516416/4206592/227762176/8671232 B. Their CWDs matched active session scopes but no `cli_pid` ancestor matched. PID 3145900’s 1.0869-GB local-share file had no prior file baseline and its writer was gone by 09:09. These file/PID matches do not establish the global df delta. File IDs map to exact paths only in private evidence.

The first no-baseline metadata script completed the tree walk and wrote recent-file records, then failed with `TypeError` during session-join serialization. A corrected bounded recovery scan covered only the 9 no-baseline roots and produced top-file/session metadata; no project-wide second inventory or content read occurred. Recovery coverage: 180 recent files, 33 directories, three metadata errors (in local share); process snapshot plus targeted PID/session correlation are preserved locally. Initial failure and recovery evidence are in `.orchestra/private/V-1155/`.

Final df at 09:10:51 CET: used 292859138048 B, available 18035499008 B, Use 95%; versus the V1154 08:40:26 CET baseline, used is higher by 818601984 B. This aggregate change is not attributed to any actor; the V1155 read-only pass found current writers but no per-file baseline to establish their net growth. No services, files, caches, processes, quotas, configs or models were modified.

## Aggregate du и текущие писатели

| scope | V1154 baseline B | supplemental allocated B | coverage |
|---|---:|---:|---|
| main `.orchestra` (private included) | n/a | 3971616768 | RC=0 |
| `orchestra/data` | 35182477312 lower bound | 35190960128 lower bound | RC=1, current 1 Permission denied path differs |
| `~/.cache` | 43261157376 | 42397347840 | RC=0; pip/Electron own cache removals already recorded |
| `~/.cache/uv` | 34397569024 | 34397573120 | RC=0, +4096 B, no UV command or process control |
| `~/.local/share` | n/a | 13484736512 lower bound | RC=1, 3 Permission denied; aggregate includes Trash, unchanged |
| `/tmp` | 7687278592 lower bound | 7580995584 lower bound | RC=1, 13 Permission denied; V1151 temp cleanup intervened |
| 7 observed CODEX_HOME roots | n/a | 1863266304 total | each root’s du RC=0; home IDs and exact paths in private evidence |

DB/WAL/SHM whole-file `du` values at 08:57:15 CET: 6688456704, 14794752, 32768 B. At the targeted FD snapshot, MainPID 3102453 held write-capable handles on all three; current FD stat was approximately 6.689 GB for the database and 14.8 MB for WAL. No per-file V1154 baseline exists.

| current/recent scope | path ID (private mapping) | current allocated B / mtime UTC | PID / task evidence |
|---|---|---:|---|
| local-share | `1df1909c3b8d` | 1086902272 / 08:04:30 | PID 3145900 (`python3`) held writable FD at 08:05; absent by 09:09; no session/CLI match |
| CODEX_HOME H1 | `b471ab46075d` | 227516416 / 08:00:31 | PID 3109026 (`codex`), still present at 09:09; CWD matched session scope, no CLI-PID ancestor |
| CODEX_HOME H3 | `732f834ea37e` | 4206592 / 08:05:09 | PID 3103143 (`codex`), same scope-only linkage limit |
| CODEX_HOME H5 | `658f8cb45986` | 227762176 / 07:52:39 | PID 3103494 (`codex`), same scope-only linkage limit |
| CODEX_HOME H7 | `e6664dd4bd2d` | 8671232 / 08:01:14 | PID 3107028 (`codex`), CWD scope included Orchestra/local-ops, no CLI-PID ancestor |

File IDs are SHA-256 prefixes of paths; full mappings and lstat metadata remain in private evidence. These are matched current/recent writers, but their roots lack per-file pre-cutoff sizes. No PID is assigned the global df increase. The `.local/share` writer was no longer present at the 09:09 targeted check.

The first no-baseline metadata script completed traversal and wrote recent-file records, then failed at session-join serialization (`TypeError`); one bounded recovery pass over only the 9 no-baseline roots produced top-file metadata. It found 180 recent file records, 33 recent directories, 3 local-share metadata errors. Process/session joins, open FD inode matches, and raw top-file metadata remain under `.orchestra/private/V-1155/`.

Final df snapshot: 09:14:09 CET, used 292854231040 B, available 18040406016 B, Use 95%; +813694976 B used versus V1154 final at 08:40:26 CET. Used fell 4907008 B from the 09:10:51 snapshot; the fluctuation is unassigned. Aggregate deltas and active writable FDs are recorded; file-level baselines are absent for `.orchestra`, local-share and CODEX homes, so causality for the global increase remains unestablished. No cleanup/services/models/providers were touched in V-1155.
