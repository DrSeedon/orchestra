## Summary

Ну конечно: один `nothing to squash` всё-таки пробрался в список интеграций. 🧱

Ref protection, counts, repository/session identities, and the #116 RAG correction are otherwise internally consistent. No secret leakage found. Two provenance blockers remain.

## Findings

### blocking: Remove the Seedon no-op from the strict integration set

[recovery-input.json:1540](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:1540)

The evidence explicitly reports `Already up to date. (nothing to squash)` at [line 1562](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:1562). Commit `0244e3d…` was then created by a separate caller-side `CLAUDE.md` edit, not by integrating the named worker branch. This contradicts both the manifest classifier and T0’s required “worker integration command → resulting target SHA” relation. Treating it as a worker integration could later falsely finalize task/lifecycle state or conclude that worker content landed. It may remain useful as task-derived human evidence, but it needs a separate non-integration classification or exclusion from the recovery candidate set.

### blocking: Preserve the commit-producing evidence for both Polus entries

[recovery-input.json:24](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:24)  
[recovery-input.json:79](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:79)

Both Polus call excerpts end before the commit command, while their results contain neither the target SHA nor even its prefix. Once the retained DB rows disappear, the stored content hashes cannot recover or verify the omitted text; the adjacent target metadata merely asserts that `a734c5a…` and `9a5dcc0…` resulted from those copies. That breaks T0’s self-contained provenance requirement and leaves later recovery unable to distinguish the intended commit from another commit produced around the same operation. Freeze excerpts containing the actual commit command and resulting SHA before the source rows vanish.

### suggestion: Encode the evidence-only and cleanup gates in the artifact

[recovery-input.json:2072](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/recovery-input.json:2072)

The plan says this snapshot is not apply authorization and that refs remain until a separate cleanup gate, but the authoritative artifact only says “for strict manual merge recovery.” Recording these constraints explicitly would keep a detached future consumer from treating inclusion as authorization or deleting refs without an exact-value CAS. This is not blocking while the plan remains mandatory.

## Verdict

**REQUEST CHANGES.**

The refs protect all 32 objects, but `0244e3d…` is not evidenced as a worker integration, and the two Polus mappings will lose their only usable command-to-SHA provenance when retained logs disappear. T1–T4 should remain blocked.

The commits are safely embalmed; two toe tags are still wrong. ⚰️

## Round (2026-08-01T09:38:47Z)

## Re-review status

Да, теперь no-op действительно означает no-op — революционная технология. 🏷️

- **FIXED — Seedon `0244e3d…`:** explicitly marked `evidence_only_non_integration`, excluded twice by OID/disposition, and permits no automatic effects. It remains protected as valid task-derived historical evidence without masquerading as worker integration.
- **FIXED — Polus provenance:** both entries contain the complete commit/push commands plus operational target-history corroboration with matching short SHA and exact subject. This remains usable after DB pruning.
- **FIXED — authorization/cleanup gates:** `apply_authorized=false`, `cleanup_authorized=false`, and cleanup requires an explicit gate plus exact-value CAS against `verified_oid`.

The #116 `ACCEPTED/COALESCED` wording correctly describes live retained scheduling, not durable queueing.

## New findings

None. Counts and dispositions resolve consistently to 31 candidates, 1 exclusion, 23 numeric candidates, and 8 human-only candidates. The supplied artifact SHA also matches.

`recovery-input.json` is untracked, so I reviewed its complete current contents directly in addition to the tracked diff.

## Verdict

**APPROVE.** No wrong-recovery or evidence-loss blocker remains.

Все 32 экспоната сохранены, но музей наконец перестал выдавать один из них за работающий станок. 🏛️
