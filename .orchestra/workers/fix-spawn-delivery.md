# fix-spawn-delivery

- `merge_worker` runs its test gate on the source branch before target integration. If an
  intentional snapshot update exists only on the target branch, first merge that target commit
  into the clean worker source; otherwise the gate tests stale expectations and rejects the merge.
