# synthesize-information-architecture

- For architecture research, preserve the exact OpenViking official URLs and fetch date: docs are
  active/version-sensitive, and current v0.4.16 release notes can diverge from older page summaries.
- When the user explicitly forbids review/model/eval calls, record the constraint in each phase artifact
  and use evidence/confidence/counter-evidence instead of implying a reviewer verdict.
- For Phase 2 with no production changes, label existence checks as smoke diagnostics only; freeze
  behavioral oracle design separately, and do not call a smoke failure a RED acceptance test.
- When a new canonical store sits behind existing adapters, direct store tests are insufficient: add a
  real adapter-to-owner-to-store test and a hook-removal mutant, or a dead parallel store can pass.
- Final acceptance controls must be invariant across both pre-change and intended states; keep old
  implementation hashes/counts as excluded evidence, never as executable post-change requirements.
