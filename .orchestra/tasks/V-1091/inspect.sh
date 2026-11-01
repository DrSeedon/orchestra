#!/usr/bin/env bash
# Local research instrumentation; no upstream script is executed.
set -eu
base=.orchestra/tasks/V-1091
date -u '+%Y-%m-%dT%H:%M:%SZ'
node --version
wc -c AGENTS.md "$base/sources/github/landing-page-design.SKILL.md"
sha256sum -c "$base/evidence/project-baseline.sha256"
nl -ba "$base/sources/github/README.md"
nl -ba "$base/sources/github/LICENSE"
nl -ba "$base/sources/github/landing-page-design.SKILL.md"
rg -n '^(#|---)|https?://|ffmpeg|API|Playwright|playwright|install|bookmarks|bookmark' "$base/sources/github/design-to-motion.SKILL.md"
sed -n '1,139p;172,193p;298,439p;441,465p;505,535p' "$base/sources/github/design-to-motion.SKILL.md"
nl -ba "$base/sources/openai/build-skills.md"
nl -ba "$base/sources/openai/agents-md.md"
