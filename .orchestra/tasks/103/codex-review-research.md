# Codex review — research

## Round 1 — infrastructure timeout with substantive partial finding

Codex timed out after ten minutes and produced no formal findings or verdict artifact. The background trace nevertheless contained a load-bearing counterexample:

```text
custom_driver_rc=0
custom_driver_out=<base tree OID>
base_tree=<same OID>
false_allow_predicate_rc=0
```

The trace used a custom merge driver that kept the current side unchanged and exited successfully.

### Independent verification

The counterexample was rebuilt in `/tmp/orchestra-103-driver-tysYi9`:

```text
normal_rc=1
custom_rc=0
custom_eq_base=yes
effective config: merge.default keep; merge.keep.driver true
```

This falsified the original unsanitized `merge-tree` predicate.

The revised experiment in `/tmp/orchestra-103-sanitized-dTcu7V` overrode the default driver, disabled renormalization, and replaced the configured custom driver command with `false`:

```text
unsafe_rc=0 unsafe_eq_base=yes
safe_rc=1 safe_eq_base=no
```

The live audit found custom merge drivers in 2 of 22 represented repositories. With the sanitized command, all 69 extant live worktree configurations were classified with zero command errors; four clean hash-diverged branches remained content no-ops.

## Verdict

No Codex verdict: round 1 timed out. The blocking partial finding was accepted and resolved experimentally.

## Round 2 — transport failure

The resumed session opened the revised research, then lost both transports before producing findings:

```text
WebSocket: Connection refused
HTTPS fallback: network error / error decoding response body
turn.failed
```

No substantive Round 2 output was produced.

## Verdict

No final Codex verdict after two research-review infrastructure failures. The only substantive cross-model finding was the Round 1 custom-driver counterexample; it was accepted, reproduced independently, and incorporated into the sanitized detector. The separate narrowly scoped plan review also failed at the transport layer; see `codex-review-plan.md`.
