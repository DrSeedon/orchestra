"""V-896 frozen task set: prompts (arm A), blind checklists (research), judge criteria (creative)."""

WRAP = ("You are working in the current directory (a snapshot of a software project without git history, or an "
        "empty scratch directory). Work only inside this directory; do not read or list anything outside it.\n\n")

C_SUFFIX = ("\n\nAdditionally: before finishing, name the external, independent criterion by which this result "
            "can be checked (a test, a command, or an observable fact outside your own reasoning), and apply "
            "it if you can.")

R_FORMAT = ("\n\nDo not change any files. Final answer: at most 600 words, plain text, starting with 'FINDINGS:'. "
            "State the conclusions, the evidence (file/function names) and the recommendation.")

# Research / thinking tasks. snapshot = commit whose tree is the starting state; the real report is NOT in the tree.
RESEARCH = {
 "R1": dict(past="#52", snapshot="84d58f6a^", paths="app scripts pyproject.toml CLAUDE.md CHANGELOG.md docs/tasks", prompt=(
   "CHANGELOG.md in this project is edited by five worker agents in parallel. Each works on its own git branch cut "
   "from the same point, and the orchestrator merges the branches one by one. Merges keep failing on CHANGELOG.md, "
   "and the project rule says every task must add an entry. Work out why this happens and what the cheapest durable "
   "fix is. What matters to the owner: merge conflicts per N parallel branches, and the number of tool calls an "
   "agent needs per task." + R_FORMAT),
   checklist=[
    "Conflicts are structural: all parallel branches insert at the same anchor (top of the shared file), so after the first merge each later merge conflicts (about N-1 of N), however careful the agents are.",
    "The fix is to stop sharing one file: one entry file per task/author (a directory such as changelog.d/<id>.md) assembled by a script, so entries coexist without conflict by construction.",
    "The existing rule is not actually followed: most or all recently merged tasks have no CHANGELOG entry (a step the agent must remember extra is skipped), so the fix must not rely on one more remembered step.",
    "The material already exists: every task already writes its own report in a per-task directory (docs/tasks/<id>/report.md); its title or a summary section can be the changelog entry, so the agent needs zero extra steps.",
    "The version number should be assigned at assembly time by one actor, not by each worker on its own stale branch.",
    "Names at least two genuinely open decisions: when to assemble (at merge vs before release), what counts as an entry (report title vs explicit section), what to do with the old large file.",
   ]),
 "R2": dict(past="#78", snapshot="c4843b0c^", paths="app scripts pyproject.toml CLAUDE.md", prompt=(
   "In the SQLite journal (table logs) about 43% of all bytes are 52 rows holding base64-encoded images (tool results "
   "of image reads). The frontend team proposes: when the row is written (app/session.py, where the tool_result is "
   "logged), copy the referenced image file into our own blob storage and keep the blob only while the log "
   "retention keeps the row, i.e. clean blobs in step with log retention. Evaluate this proposal against the code "
   "and recommend what to do." + R_FORMAT),
   checklist=[
    "At the write point the file path is not available (it sits in the previous journal row of the tool call), so 'copy the file' is the wrong source; the image bytes are already in hand in event.content, so decode and store those bytes instead.",
    "Referenced files are fragile: worker working copies are removed after merge, so a link to the file would rot; storing the bytes makes the blob independent of the working copy.",
    "Log retention does not exist: cleanup_old_logs is a disabled tombstone by owner decision (history is never deleted), so 'clean blobs in step with retention' means never; the blob lifecycle must be decided explicitly (e.g. blob lives exactly as long as its row, plus an inventory that deletes nothing).",
    "The logs table is append-only by invariant (no UPDATE), so migrating the existing 52 rows conflicts with it; options are a new row plus a marker, an explicit revision of the invariant, or leaving old rows; readers must handle both formats.",
    "base64 inflates data by a third, so storing decoded bytes also shrinks the volume (about 25%).",
    "Non-image heavy rows exist too (large Read/Write results), so truncation of heavy rows stays needed; blobs do not solve them.",
   ]),
 "R3": dict(past="V-624", snapshot="6d7b5793^", paths="app scripts tests pyproject.toml", prompt=(
   "Running the full test suite of this project (`pytest tests/`) is killed with exit code 137 and no summary, at a "
   "varying position around 35-40% of the way; the machine has plenty of free memory. A different run configuration "
   "of the same suite hangs forever near 85-88%, during the teardown of a fixture that wraps TestClient(app). "
   "Find the root causes of both without running the full suite (small targeted commands are allowed)." + R_FORMAT),
   checklist=[
    "Cause 1 (the 137): tests of the restart path call app.routes.system._do_restart_service, which arms a real helper process (app.restart_guard) targeting the pytest process itself; so the kill is not an out-of-memory kill.",
    "The restart guard sends SIGKILL to its target a few seconds (about 5 s) after the application-teardown-complete marker, which any later test that enters and leaves TestClient(app) writes; that is why the death position floats and the run ends without a summary.",
    "The tests stub os.kill but not the guard helper; the fix is a conftest/fixture-level guard that forbids arming the real guard on the test runner's own pid (autouse fixture or shared fixture), turning a silent death into a visible failure.",
    "Cause 2 (the hang): a test renders the limits card with real Chromium (app.limits_card) and leaves the browser in a module-level singleton bound to that test's event loop.",
    "On lifespan shutdown (TestClient exit) limits_card.shutdown_renderer runs browser.close() on a different event loop; the Playwright reply goes to the dead loop, the future never resolves and teardown waits forever; the render path already handles the previous-loop case but the shutdown path does not.",
    "States explicitly that memory is not the cause (exit 137 is misleading), with a reason from the code or a check.",
   ]),
}

# Creative tasks without a reference: blind pairwise judging. The judge sees only the brief and two texts.
CREATIVE = {
 "K1": dict(prompt=(
   "Write the narration script for a 75-second explainer video for non-technical viewers, titled 'Why an AI agent "
   "forgets after a long session, and what a summary does about it'. Facts you may use: an agent works in a long "
   "conversation; when the conversation grows too big for the model's window it is compressed into a summary and "
   "work continues from that; details that were not carried into the summary are gone; a good summary is checked "
   "by asking the agent questions about the old work. Deliver: the narration with a one-line scene direction before "
   "each part, at most 260 words in total. Final answer is only the script."),
   brief="a 75-second explainer-video script for non-technical viewers, at most 260 words, narration plus one-line scene directions"),
 "K2": dict(prompt=(
   "The owner of a multi-agent coding platform cannot tell at a glance what each of ten running agents is doing and "
   "whether it is stuck, waiting, or making progress; reading the chat logs of each is too slow. Propose one feature "
   "concept for the dashboard that fixes this. Deliver at most 300 words: the core idea in one sentence, what the "
   "owner sees and does (concretely), why it works better than the obvious alternative of a log list, and the main "
   "risk. Final answer is only the concept."),
   brief="one dashboard feature concept (core idea, what the owner sees and does, why better than a log list, main risk), at most 300 words"),
 "K3": dict(prompt=(
   "Agents on a platform sometimes go quietly idle for hours while waiting for something that will never come, and "
   "nobody notices. The platform now blocks this with a mechanism: when an agent has been silent past a limit and "
   "has no live background job, it is woken with a message naming the rule it broke. Give: (1) five candidate names "
   "for this mechanism, each with a six-word-or-shorter rationale, (2) your pick, (3) a one-sentence rule for the "
   "owner's rules file that states the behaviour and its reason. At most 150 words in total. Final answer is only "
   "these three parts."),
   brief="five names with short rationales, a pick, and a one-sentence rule stating behaviour and reason, at most 150 words"),
 "K4": dict(prompt=(
   "Write a Telegram message to the product owner (a smart non-programmer who reads on a phone) reporting an "
   "experiment result honestly. Facts: we tested a prompt trick that rewrites each task before the agent executes "
   "it; across 48 runs it did not raise the share of accepted answers, it more than doubled the paid tokens, and the "
   "task set was too easy to show any gain anyway. Do not hide the weakness of the measurement. The message must let "
   "the owner decide what to do next without opening anything else. At most 120 words. Final answer is only the "
   "message."),
   brief="a phone-readable message to a non-programmer owner reporting a negative experiment honestly, ending in a decision-ready state, at most 120 words"),
 "K5": dict(prompt=(
   "Explain to someone who has never programmed why a test that turns green can still prove nothing, and what "
   "'checking that the test can fail' means. Use one fresh everyday analogy (not a smoke alarm and not a bathroom "
   "scale, which are overused). At most 220 words. Final answer is only the explanation."),
   brief="an explanation for a non-programmer of why a green test can prove nothing and why one checks that it can fail, one fresh everyday analogy, at most 220 words"),
 "K6": dict(prompt=(
   "A personal assistant bot receives the owner's voice notes in Telegram, turns them into text, files them into a "
   "notes vault and answers questions about them later. Write: a product name (one word, pronounceable in Russian "
   "and English), a tagline of at most eight words, and a three-sentence pitch that makes a sceptical friend want to "
   "try it. At most 90 words in total. Final answer is only these three parts."),
   brief="a one-word name, a tagline of at most eight words and a three-sentence pitch for a voice-notes assistant bot, at most 90 words"),
}

JUDGE_CRITERIA = (
 "Judge which of the two texts is the better answer to the brief. Criteria, in this order: (1) insight and "
 "originality: a non-obvious, well-chosen idea rather than generic filler; (2) concreteness: specific images, "
 "numbers or actions instead of abstractions; (3) fit to the stated audience and tone; (4) strict compliance with "
 "the brief's format and length limits (a text that breaks a hard limit loses unless the other breaks it worse). "
 "Do not prefer a text for being longer. Reply with a JSON object only: {\"winner\": \"X\" or \"Y\", "
 "\"reason\": \"<=25 words\"}.")

GRADER_PROMPT = (
 "You grade an answer against a checklist of key findings. Mark a finding 1 if the answer states it clearly "
 "(different wording is fine, same substance), 0.5 if it is only hinted at or half right, 0 if absent or wrong. "
 "Do not reward length or extra material. Reply with a JSON object only: {\"scores\": [<one number per finding, in "
 "order>]}.")
