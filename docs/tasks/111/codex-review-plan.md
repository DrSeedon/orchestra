## Summary

Naturally, `/proc` promises a family tree right until the children run away 😏

Three blocking gaps remain: process enumeration is incomplete, PID signaling is racy, and the lifecycle lock does not cover every send admission. Exact thread resume and the detached DB-only route are otherwise specified adequately.

## Findings

1. **blocking — The `/proc` walk cannot guarantee complete tree ownership.**  
   [plan.md:24](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/plan.md:24)

   `/proc/<pid>/task/<pid>/children` covers only children created by the leader task, not every TID. More importantly, Linux documents this interface as reliable only when all children are already stopped; the proposed root-first traversal discovers them while they are still running. An intermediate process can exit and reparent descendants before discovery, so a fixed-point walk can still leak MCP processes. Require ownership that survives reparenting, or explicitly solve per-TID freezing and the exiting-intermediate race. Add fixtures for a non-leader thread spawning a child and for an intermediate parent exiting during traversal. [Linux `proc_tid_children(5)`](https://www.man7.org/linux/man-pages/man5/proc_tid_children.5.html)

2. **blocking — `(pid, starttime)` does not make signaling race-free.**  
   [plan.md:24](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/plan.md:24)

   Reading `starttime` and then calling `kill(pid, ...)` are separate operations. The target can exit and its PID can be reused between them, causing an unrelated process to receive `SIGSTOP`, `SIGTERM`, or `SIGKILL`. The current AC tests only a mismatch visible before signaling. Use a stable process reference such as pidfd, and test replacement after validation but before signal delivery. Linux provides pidfd signaling specifically to eliminate this race. [Linux `pidfd_send_signal(2)`](https://www.man7.org/linux/man-pages/man2/pidfd_send_signal.2.html)

3. **blocking — Mid-turn send bypasses the claimed lifecycle linearization.**  
   [plan.md:59](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/plan.md:59)

   T2 moves `_flush_pending()` under the lock, but the current `RUNNING`/mid-turn path enters before `_lifecycle_lock` in [session.py:605](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/session.py:605). If the turn becomes `IDLE` while that send awaits backend I/O, manual hibernate can acquire the lock, observe no pending work, and disconnect. The send can then fail and enqueue after the hibernate predicate and after the turn-finalizer’s flush decision, leaving a pending message stuck with `_hibernated=True`. T2 must explicitly serialize this admission or add an in-flight guard, with a deterministic test that pauses send after its initial `RUNNING` read while the turn transitions to `IDLE`.

4. **suggestion — The capability flip is not actually the final ticket step.**  
   [plan.md:157](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/plan.md:157)

   T2 enables Codex hibernation, while T3 is blocked by T2 and therefore follows the flip. That contradicts “final code change” and permits automatic hibernation in an intermediate ticket state. Put the registry change and capability assertion in a final activation ticket blocked by T1–T3, or move them to the end of T3.

## Verdict

**NO-GO until the three blocking findings are resolved.**

The plan correctly preserves the exact thread ID, backend ownership on failure, and DB-only no-load behavior, but it does not yet prove zero leaked processes or lock-linearized delivery. Right now MCP can still win hide-and-seek by changing PID or parent at the right moment.

## Round (2026-08-01T08:03:01Z)

## Summary

The PID hydra is dead; now the user manager gets to be the dramatic one 😏

Prior findings 1–3 are resolved for supported hosts. Finding 4 is improved but incomplete. Two new blocking deployment/fallback gaps remain.

## Findings

1. **blocking — Preflight must prove scope attachment from Orchestra’s real cgroup.**  
   [plan.md:23](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/plan.md:23)

   Orchestra’s shipped deployment is a system service under `system.slice` ([service template](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/deploy/orchestra.service.template:5)). A responsive user bus does not prove that its manager can migrate a `systemd-run --scope` child from that separate cgroup delegation; cgroup v2 can reject such cross-delegation moves. Because post-preflight scope failure is deliberately fatal, this would break all Codex launches instead of selecting direct fallback. Preflight must launch and verify a disposable scope from the actual Orchestra process/cgroup, with a service-context smoke test. [Kernel cgroup-v2 delegation rules](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)

2. **blocking — User-manager availability does not guarantee its lifetime.**  
   [plan.md:35](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/plan.md:35)

   A bus socket may exist during a login even though lingering is disabled. After the last logout, systemd terminates the user manager and its units while the system-wide Orchestra service continues, abruptly killing scoped Codex during an active turn. Scope mode must require either that Orchestra itself shares that user-manager lifetime or that lingering is guaranteed; otherwise choose direct fallback. Add an AC for this host state. [systemd user-manager lifetime](https://man7.org/linux/man-pages/man1/systemd-run.1.html)

3. **suggestion — Move timer wiring into T2 before the final capability flip.**  
   [plan.md:196](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/111/plan.md:196)

   T3 still both enables `hibernate=True` and reroutes the timer through the safe helper—in that order. Therefore activation is not structurally the final prerequisite: an intermediate T3 state lets the legacy timer bypass `hibernate_safe`. Put timer wiring and its tests in T2; leave T3 as the registry flip and capability-matrix assertion only.

## Verdict

**NO-GO until the two host-compatibility blockers are addressed.**

The cgroup teardown, exact resume, ownership retention, and send linearization are now well specified. The remaining risk is choosing a perfectly safe scope that the deployed service cannot enter—or that disappears when someone logs out.

## Round (2026-08-01T08:10:18Z)

## Summary

Apparently measuring the actual service beats arguing with hypothetical cgroups—who knew 😏

All prior findings are resolved:

- PID-tree and reuse risks: removed by unit-scoped ownership.
- Send/hibernate race: covered by lock-linearized admission and targeted AC.
- Deployment fallback: guarded by `Linger=yes` plus a real service-context scope probe.
- Activation ordering: timer wiring is in T2; T3 is now capability-only.

## Findings

No blocking, suggestion, or question findings.

## Verdict

**GO for implementation planning.**

The plan now fails closed without breaking unsupported hosts, preserves exact resume and backend ownership, and makes the capability flip genuinely last. The process hydra finally has one cage and one eviction notice.
