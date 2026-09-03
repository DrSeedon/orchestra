# Local evidence manifest — task #84 implementation status

**Checkout:** `5d72eb287dd78d48b152be0b4d3401de56d4677b`
**Branch:** `feat/mnt-data-projects-python-orchestra/research-self-improve`
**Captured:** 2026-07-18

Question: is the implementation described in the #84 plan present in this checkout? The planned
signatures were `app/self_learning.py`, a `learnings` table and `SELF_LEARNING_ENABLED`.

Commands were run from the repository root. Exit code `1` from `rg` means no matching lines.

```text
$ git ls-files app pipelines tests .env.example | rg "(^|/)(self_learning\\.py|.*learning.*\\.py)$"
exit=1

$ rg -n --glob "*.py" --glob "*.yaml" --glob "*.md" --glob ".env.example" "SELF_LEARNING_ENABLED|CREATE TABLE( IF NOT EXISTS)? learnings|class SelfLearning|def (extract|propose)_learning" app pipelines tests .env.example
exit=1

$ test -e app/self_learning.py
exit=1
```

This proves only that the planned #84 implementation is absent from the named checkout. It does not
make a claim about unmerged branches or external repositories. The prompt-only mechanism in
`pipelines/default/prompts/modules/self-improvement.md` is a different, shipped implementation.
