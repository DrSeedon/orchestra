# V-1168: bounded disk delta and writer metadata

## Exact filesystem readings

All readings resolved to the same ext4 root filesystem mounted at `/`, total `310911414272` bytes. The supplied 23:36 KRS baseline is 16:36 UTC: used `301651070976`, available `9243566080`. The initial reading was used `301674397696`, available `9220239360` (98%). The targeted du pass began and ended at 16:44:38 UTC with used `301188251648`, available `9706385408` (97%). The final reading at 16:46:59 UTC was used `300802269184`, available `10092367872` (97%), or `848801792` bytes less used than the supplied baseline. During the pass, readings varied by up to `872128512` bytes; no cause is assigned.

## Root measurements

GNU `du` reports allocated bytes, with `-x -B1`; V-1155 recorded one `-s` invocation per root and this pass recorded `-d1` totals plus direct children. Roots are nested and some contain hard links; do not sum rows. The current snapshot time is 16:44:38 UTC. V-1155 root baseline time is 08:57:15 CET (07:57:15 UTC).

| Scope | V-1155 allocated B | Current allocated B | Delta B | Coverage / comparability |
|---|---:|---:|---:|---|
| Git common directory | no root baseline | 473894912 | — | current only, RC=0 |
| Project `.orchestra` | 3971616768 | 4016844800 | +45228032 | same root device/inode; RC=0 both |
| Project `data` | 35190960128 | 35088584704 | −102375424 | known-readable lower bound; RC=1 both with the same unreadable child |
| Runtime-home family | 7 observed homes sum 1863266304 | 38 homes sum 5254459392 | — | family coverage differs: 5 old paths remain, 2 are absent, 33 current paths had no V-1155 baseline |
| Local-share aggregate | 13484736512 | 14477213696 | +992477184 | lower bound; RC=1 both with the same 3 unreadable children |
| `~/.cache` aggregate | 42397347840 | 42459308032 | +61960192 | complete, RC=0 both |
| `~/.cache/uv` | 34397573120 | 34458419200 | +60846080 | complete; no UV command was run |
| `/tmp` aggregate | 7580995584 | 7696388096 | +115392512 | incomplete and not comparable: 13 unreadable children at baseline, 14 currently |

Current `.orchestra` includes 3439120384 B under its private subtree and 576913408 B under tasks. Current large project data subdirectories include backups 8551944192 B, uploads 3363581952 B, and models 1718460416 B. These are measurements, not deletion candidates.

Among exact-path child comparisons with saved V-1155 snapshots, the `tg-file-outbox` subtree is 708308992 B versus 942903296 B in the V-1155 metadata snapshot at 07:47:27 UTC (−234594304 B), and `.cache/v44` is 100667392 B versus 560992256 B (−460324864 B); it is back at its earlier V-1155 baseline. These category changes do not explain the aggregate `df` fluctuation.

## File and writer evidence

The configured service MainPID and DB path were read without opening database contents. The service process held write-capable FDs to `data/orchestra.db`, its WAL and SHM. At 16:46:07 UTC the DB was allocated 6800150528 B and the WAL 15192064 B. V-1155 had the same DB path at 6689820672 B allocated; path-level delta is +110329856 B. Baseline device/inode was not recorded, so this is a matched-path comparison, not inode proof of file continuity. The live FD proves a current writer on that path; it does not assign the global `df` movement to that writer.

Two local-share SQLite files were each held open read-write by one current Python process: allocated sizes 1086902272 B and 768491520 B. V-1155 path records measured the first at 1086902272 B and the second at 767762432 B; the second changed by +729088 B. No task/session identity was matched to that process. These measurements account for only a small part of the local-share aggregate delta; the rest is unresolved by this pass.

Two `uv` processes had the UV cache lock path open in the earlier process snapshot; no lock was manipulated. The process snapshot covered 269 user-owned proc entries, with 2 cwd, 1 FD-directory and 36 FD-link permission/race errors. No active matching `tar`/`pytest` writer was found in the readable process metadata.

## Temporary archives, test fixtures, and coverage limits

The source uses Python’s default temporary directory for `hub-sync-*` scratch (`app/hub_workspace.py:1495`) and has a `finally` cleanup path (`app/backend_hub.py:615`). `TMPDIR` was unset in the service process; the default resolves to `/tmp`. Metadata scanning found no `in.tar` or `out.tar` at least 100 MiB. The largest matching hub scratch tar was 60958720 B, last modified at 16:12 UTC before the supplied 16:36 UTC baseline, and had no current matched FD/CWD. Its contents were not read, so rebuildability is unproven and it was preserved. No path containing `V-1166` or `FakeDB` was found under the selected readable project metadata roots.

The metadata-only traversal covered selected roots under project data, `.orchestra`, runtime homes, local-share, cache and `/tmp`: 1085156 files and 249287 directories. There were no per-file stat errors. The walker did not record `os.walk` traversal errors; `du` explicitly reported 1 unreadable data child, 3 local-share children and 14 `/tmp` children, so negative results are limited to accessible paths. Recent-file metadata used cutoff 16:36 UTC. Bodies, DB contents, credentials, process command lines and unfiltered environment were not read. No existing files, caches, lock holders, processes, services, config or state were changed; only V-1168 evidence artifacts were written.

Raw exact paths, root stats, all current du output/RC/stderr, file metadata, process FD metadata and the derivation are local-only in `.orchestra/private/V-1168/` (`snapshot.json`, `root-comparison.json`, `writer-focus.json`, `df-start.txt`, `df-final.txt`, `du-*.stdout.txt`, `du-*.stderr.txt`, `du-*.rc`, `snapshot.py`). V-1155 comparison inputs are listed in `artifact-manifest.txt`. No actor is assigned the unaccounted aggregate changes.
