# synthesize-information-architecture

- For architecture research, preserve the exact OpenViking official URLs and fetch date: docs are
  active/version-sensitive, and current v0.4.16 release notes can diverge from older page summaries.
- When the user explicitly forbids review/model/eval calls, record the constraint in each phase artifact
  and use evidence/confidence/counter-evidence instead of implying a reviewer verdict.
- For Phase 2 with no production changes, label existence checks as smoke diagnostics only; freeze
  behavioral oracle design separately, and do not call a smoke failure a RED acceptance test.
