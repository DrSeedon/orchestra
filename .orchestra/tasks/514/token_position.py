"""Read-only: where does the old docs/ literal sit — comment, docstring, or live code?

Uses tokenize (no import, no execution of the audited file). A STRING token that is the
first statement of a module/class/function is reported as `docstring`; any other STRING
token as `string`; `#` text as `comment`. `string` and `docstring` are inert only when the
value is not consumed — that is decided by the run, not here. This probe exists to say
which lines cannot possibly be executed (comments) and which are literals.
"""
import io
import sys
import tokenize
from pathlib import Path

TARGETS = [
    ("kesha-tg-bot", "/home/kesha/projects/kesha-tg-bot", [
        "runtime_protocol.py", "codex_session.py", "compact.py", "claude_session.py",
        "rag.py", "tests/test_runtime_limits.py", "tests/test_compact_prompt.py",
        "tests/test_codex_session.py",
    ]),
    ("katya-work", "/home/kesha/katya-work", [
        "artifacts/task-6/lesson-01/validate.py",
        "artifacts/task-9-avito/avito_ads.py",
        "artifacts/task-4/tests/validate_t1_contract.py",
        "artifacts/task-4/tests/validate_t3_catalog.py",
        "artifacts/task-4/tests/validate_t4_lesson9.py",
        "pipeline/scripts/generate-master-registry.py",
    ]),
    ("orchestra", "/home/kesha/orchestra", [
        "app/orchestra_layout.py", "app/ia/cutover.py", "scripts/secret_scan.py",
        "scripts/wf_pilot.py", "scripts/verify_orchestra_move.py",
        "scripts/check_orchestra_paths.py",
    ]),
]
NEEDLES = ("docs/tasks", "docs/kb", "docs/workers", "docs/pipelines")

print("repo\tfile\tline\tposition")
for repo, root, files in TARGETS:
    for rel in files:
        path = Path(root) / rel
        source = path.read_text(encoding="utf-8")
        prev_meaningful = tokenize.INDENT  # a docstring follows NEWLINE/INDENT/nothing
        seen: set[tuple[int, str]] = set()
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                kind = "comment"
            elif token.type == tokenize.STRING:
                kind = "docstring" if prev_meaningful in (
                    tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT,
                ) else "string"
            else:
                if token.type not in (tokenize.NL, tokenize.COMMENT):
                    prev_meaningful = token.type
                continue
            if any(n in token.string for n in NEEDLES):
                for offset, text in enumerate(token.string.splitlines()):
                    if any(n in text for n in NEEDLES):
                        key = (token.start[0] + offset, kind)
                        if key not in seen:
                            seen.add(key)
                            print(f"{repo}\t{rel}\t{key[0]}\t{kind}")
            if token.type not in (tokenize.NL, tokenize.COMMENT):
                prev_meaningful = token.type
