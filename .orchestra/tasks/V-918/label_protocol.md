# V-909 labeling protocol

You are labeling the findings of an automated code reviewer. You do not know, and must not try to find out, anything
about how the commit was classified beforehand. Judge each finding on its own claim.

Repository: you cannot access it; everything you need is inline.
Do not read anything under `.orchestra/tasks/V-909`, `.orchestra/tasks/V-905`, `.orchestra/tasks/V-906`.

IMPORTANT (tool limits): you have NO shell, so ignore any `git ...` command quoted in the item file. Instead use Read/Grep on:
- the item file (`<stem>.md`) and its context file (`<stem>.ctx.md`, same directory): the exact diff reviewed with 20 lines of context, the list of later
  commits on main that touched the same files, and the patches of the first 8 of them;
- the repository's CURRENT state at /home/kesha/orchestra (current main, read-only): use it to see how the touched code looks later.
For `retro-*` items about research/plan documents, the documents are under /home/kesha/orchestra/.orchestra/tasks/<task>/ (current main).
State in `notes` what you could not verify.

Steps for each item file:
1. Read the item file (reviewer output + commit sha). Extract every distinct finding (one defect claim = one finding),
   whatever its heading (blocking / suggestion / question / unlabelled). A "question" that only asks the author to confirm
   intent or scope, with no claimed defect, is a finding with label `question_only`. Ignore praise and the summary.
2. For each finding, check the claim against the code at that commit (`git show <sha>:<path>`, `git show <sha>`), and against
   what the repository did afterwards (`git log main --first-parent`, `git log -S'<symbol>' main`, `git log main -- <path>`,
   `git show <later-sha>`) — look for later commits that fixed, changed, reverted or relied on the spot. A later fix of that spot
   is strong evidence for `real`; its absence is NOT proof of `noise` (judge by reading the code). A revert for an unrelated policy
   reason is not evidence of a defect.
3. Label each finding exactly one of:
   - `real`: the claim is true AND is a defect introduced or exposed by this diff: wrong behavior, crash, data loss/corruption,
     security hole, broken contract or race that a competent maintainer of this project would want fixed. Minor but true bugs count.
   - `noise`: the claim is false, rests on a wrong assumption about the code/library/project, is purely speculative with no concrete
     failing input, is style/naming/preference, or matters nothing for this project (a single-owner, self-hosted platform).
   - `preexisting`: the claim is true but the defect lives in code the diff did not touch or introduce.
   - `question_only`: see step 1.
4. For `real`, add `importance`: `high` (a maintainer would stop a merge for it) or `low`.
5. `evidence`: one or two sentences with the concrete file:line or later commit sha you used. No evidence = you did not verify.
Be concrete and skeptical in both directions: do not accept a finding because it sounds plausible, and do not dismiss it
because the author's tests passed.
