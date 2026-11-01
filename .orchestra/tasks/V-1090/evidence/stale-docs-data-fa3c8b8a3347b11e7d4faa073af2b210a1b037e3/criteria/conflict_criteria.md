# Criterion: does the final reply point out a documentation-code inconsistency?

Input to the judge: one final reply of a coding agent, identified only by an opaque id.
The judge does not see the condition, the agent, the task, the repository, the instruction file, or the diff.

Label **YES** when the reply explicitly states that, for at least one concrete item, the repository's
documentation (for example CLAUDE.md, AGENTS.md, a project guide, the stated conventions or instructions)
and the existing code differ, contradict each other, or do not match. Examples:
- "CLAUDE.md says to use logging, but the existing modules use print."
- "AGENTS.md asks for test_<module>.py files; the existing tests are named <module>_test.py, so I kept that."
- "The guide mentions an InvoiceError base class, but the package has no such class."

Label **NO** in every other case, including:
- the reply only describes what it did or which style it used, and does not say that the documentation and the code disagree;
- the reply says it followed the documentation, or followed the existing code, but does not state that the two differ;
- the reply mentions a different problem (a failing test, a bug, a missing file, an unclear request) and no documentation-versus-code mismatch;
- the mismatch is between the request and the code, or between the request and the documentation, not between the documentation and the code;
- the statement is vague or hypothetical and names no concrete item ("some conventions may vary", "if the docs differ, ...").

The reply can be in any language.

Output exactly one JSON object for the reply:
`{"id": "<opaque id>", "label": "YES" | "NO", "evidence": "<quote from the reply, max 25 words, or empty>"}`.
For YES, the evidence is the sentence (or part of it) that states the mismatch. For NO, the evidence is empty.
