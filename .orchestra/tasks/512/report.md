# #512 — public showcase: Russian version, header badges, head-to-head with Orca

Artifacts: `README.md`, `README.ru.md`, `.orchestra/tasks/511/check_table.py`.
Exact numbers are frozen here, as measured on 2026-09-05. The public text carries thresholds and
words instead, because a byte count in a README goes stale on the first foreign edit (#511).

## 1. Russian version and the language switch

`README.ru.md` is a full parity version, not a subtitle track: 29 status rows and 17 `file:line`
anchors on both sides, verified by counting the parsed block in each file. The switch sits in the
first screen of both files (`<sub><b>English</b> · <a href="README.ru.md">Русский</a></sub>` and its
mirror), directly under the tagline and above the nav, so a reader lands in their own version before
scrolling. The Russian nav targets are explicit `<a id="quick-start">`-style anchors rather than
generated Cyrillic slugs.

## 2. Badges — what was measured, not what was expected

| badge | request result |
|---|---|
| `github/last-commit` | `http=200`, renders `last commit: today` |
| `github/commit-activity/m` | `http=200`, renders `commit activity: 1.1k/month` |
| `actions/workflows/ci.yml/badge.svg` | `http=200`, renders **`CI - failing`** |
| existing `github/license` | `http=200`, renders **`license: not identifiable by github`** |
| link `/actions/workflows/ci.yml` | `http=200` |
| link `/graphs/commit-activity` | `http=200` |
| link `/commits/main` | `http=429` — and `stablyai/orca` returns 429 on the same path from this
  host, so it is GitHub rate-limiting anonymous HTML, not a dead page. Underlying resource verified
  via `gh api repos/DrSeedon/orchestra/commits/main` → `sha=b30fe9d0` |
| link `/stargazers` | `http=404`, and the positive control `stablyai/orca/stargazers` is also 404
  from here — same class of anonymous-HTML block, not a broken link |

**CI badge deliberately not published** (orchestrator's call, my measurement). Workflow
`ci.yml` (id 291940562) has **258 completed runs: 1 success, 159 failure, 98 cancelled**. The last
failure, run `33893200040`, printed **60 `F`** and was then killed with **exit code 137** — out of
memory — at 81 %. So the badge would be formally true and substantively misleading: it says "broken
project", the truth is "the suite does not survive one process, and there are also real failures".
The README carries this as a 🚧 row saying both causes, with no badge.

**License badge is static, and this is not a workaround pending laziness.** After the orchestrator
replaced `LICENSE` with the verbatim AGPL-3.0 text locally (`886aaa89`, 34 523 B, plus a new
`NOTICE`), GitHub still answers `gh api repos/DrSeedon/orchestra -q .license.key` → **`other`** /
`NOASSERTION`, and the live badge still renders "not identifiable by github". Reason established,
not guessed: **the fix has not reached GitHub.** `gh api repos/.../contents/LICENSE -q .size` → **826**
(the old stub), `contents/NOTICE` → **404**, and `git branch -r --contains 886aaa89` is **empty**.
Detection cannot update on a file the server has never seen. Swap the static badge for the live one
after the push, once `.license.key` reads `agpl-3.0`.

## 3. Head to head with Orca

Every Orca cell is a quote from their own README, pulled raw 2026-09-05
(`gh api repos/stablyai/orca/readme -q .content | base64 -d`). Metadata the same day: **61 836★**,
4 136 forks, MIT, pushed that day. Ours: **12★**.

Six axes, **three of them ours to lose** and marked in-table, not in a footnote: number of pluggable
agents (4 hand-written backends vs "any CLI agent", 29 named), install and interfaces (`git clone`
vs brew/AUR/exe/AppImage + App Store + APK), audience. The sharp row is the first one and it quotes
them against themselves: their header says "The AI Orchestrator for 100x builders", their feature
text says "Fan one prompt across five agents … compare the results and merge the winner" — the fan
and the choice of winner are the user's.

Two cells say **"not checked"** rather than "they don't have it": model review, and agent lifetime.
Their README describes review by a human ("Drop comments on any diff line and ship them back to the
agent", `docs/review/annotate-ai-diff`) and says nothing about agent lifetime or merge gates. Their
docs site was not audited — `https://www.onorca.dev/llms.txt` returns 404, and one pass over a docs
site is too little for an honest cell (#503).

## 4. Findings — README claims that were false, and a watchdog that could not see it

**8 of 17 `file:line` anchors in the status table had drifted**, and `check_table.py` passed on all
of them, because it only asserted the line was non-blank. Corrected, each now naming the symbol it
points at:

| claim | was | is |
|---|---|---|
| spawn refuses on `owned_dirs` overlap | `manager.py:554` (a comment about pytest) | `dirs_overlap`, `manager.py:596` |
| mapped test subset gates the merge | `merge_operations.py:1890` (`finish_operation` args) | `gate_blocks`, `:2063` |
| no-oracle merge into a non-main target is refused | `merge_operations.py:870` (an operation marker string) | `nested_behavioral`, `:1051` |
| review refusal | `merge_operations.py:2211` (exception handling) | `:609` |
| review policy switch | `review_coverage.py:89` (a diff comment) | `policy_active`, `:382` |
| reviewer runs unsandboxed | `mcp_stdio.py:4080` (`code="invalid_argument"`) | `:4201` |
| `codex_review` | `mcp_stdio.py:3866` (`_receipt_author_session`) | `:3987` |
| client `no-store` | `app.js:1225` (agent-selection guard) | `:1274` |

The watchdog now requires each anchor row to name a backticked symbol and that token to appear
within ±2 lines of the anchor. **Order was the proof**: the new check was run before the six
remaining anchors were corrected and printed 15 failures naming them; after correction, RC=0. Both
guards were then mutation-tested — dropping a status mark from a capability row reddens it, and
sending `review_coverage.py:382` back to `:89` reddens it with the wrong line quoted.

Known limit, written into the script: one row token satisfying one of the row's anchors is enough,
so a row whose tokens are substrings of one another is checked more weakly.

**The sandbox row stated a false reason.** It said the reviewer runs unsandboxed "because
unprivileged user namespaces are off on this host". Probe: `cat
/proc/sys/kernel/unprivileged_userns_clone` → **`1`**, and `bwrap` is not installed at all
(`/usr/bin/bwrap` does not exist, `bwrap` not on PATH). Namespaces are available; the sandbox is
absent by acceptance, not by kernel limitation. Row rewritten to say that.

Side note for the guide: `CLAUDE.md` currently records a 2026-09-05 probe of "system bwrap" returning
RC=0. In this worktree shell there is no bwrap binary to run, so that line does not reproduce here.

**`CLAUDE.md` is 212 299 B, not the "about 190 KB" the README claimed.** The floor in the script was
never the defect — `parents[3]` resolves to the repository root and 212 299 ≥ 150 000 held all along.
The defect was the pinned literal `"about **190 KB**"`, which froze a number that had already
drifted. Both sides now carry the claim in words ("hundreds of kilobytes"), and the script keeps the
floor plus a check that the wording is still there.

**The watchdog itself went red on the new Orca table** and I caught it only after committing: it
selected status rows by column count, and the head-to-head table also has three columns, so all six
of its rows were demanded to carry ✅/🚧/🚫. Fixed by selecting the status table by section
(everything before the first `###`) in `08383b00`.
