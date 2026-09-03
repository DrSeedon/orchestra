# #456 pre-registered evaluation protocol

## Question and hypotheses

- Context: Orchestra implementation and review history for durable identity, keys, and state ownership.
- Change under test: add one bounded STOP rule to the existing code-review prompt.
- Baseline: existing review calibration and historical review artifacts, without the new rule.
- Outcome: detection on the three card-named defects; false STOP count on six frozen controls; incremental prompt tokens and review turns.
- H1: a narrow boundary/ownership signal catches the three defects because each change either makes a mutable value identify a durable entity or creates a second state writer. Falsifier: fewer than 3/3 STOPs, or more than 1/6 false STOPs.
- H2: prompt calibration is insufficient because the missing information is outside the reviewed diff or the implementation never reaches review. Falsifier: the augmented rule catches 3/3 from the supplied diff plus ordinary consumer context and history shows every defective hunk reached review.
- H3: the rule is more expensive than omission. Falsifier: one bounded first pass catches 3/3 with at most 1/6 false STOPs and adds no mandatory round on PASS cases.

## Frozen STOP rule

Apply this check only when a changed hunk does at least one of the following:

1. creates or changes a value used to identify, deduplicate, join, or address one logical entity across time, accounts, processes, components, or persistent stores; or
2. creates or leaves more than one write path for the same logical state.

For (1), name the entity, the key, its uniqueness scope, its source of authority, and what happens when the entity is renamed or the key is rotated, reset, or retried. For (2), name the state, every writer visible in the supplied material, and the single owner or coordination invariant. Output `STOP` only when the supplied hunk/context proves a missing or contradictory invariant: the same entity can receive another key, one key can address two entities, or independent writers can diverge. Absence of wider context alone is not a finding.

Do not stop for ephemeral local IDs, loop indices, presentation labels, regex/content classification, test names, immutable constants, documentation-only changes, or a second path that only reads/validates authoritative state. If neither trigger applies, output `PASS`.

## Frozen corpus and counting

- Positives: B (`e3f95f98`, content-derived fact identity), D (`01a666ed`, addressing historical transcripts by a current SDK session identifier that an existing lifecycle path replaces), G (`baf501c7`, canonical task-number writer beside an existing legacy allocator).
- Negative controls: A (`0f415e84`, presentation formatting), C (`a10f1451`, one-owner task-number fix), E (`18fdb7b8`, secret content patterns), F (`71240bd4`, audience classification), H (`38caf30b`, historical SDK-ID fix with test), I (`90e5a526`, ignore rule).
- A false positive is `STOP` on A/C/E/F/H/I for the identity/ownership class, regardless of unrelated suggestions.
- A false negative is `PASS` on B/D/G.
- The fixed order A-I is neither grouped by label nor disclosed to the evaluator through the target packet. The evaluator is forbidden to inspect the repository, history, sibling files, or this protocol.
- Pass threshold was fixed before the run: 3/3 positives detected and no more than 1/6 false STOPs. Observed rates are descriptive for this nine-case corpus; no population claim follows from them.
- One evaluator turn only. No retry or second round is permitted for this corpus; ambiguity remains a measured miss rather than being coached away.
