"""Census real review artifacts with the current finding extractor."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.review_coverage import review_findings
ARTIFACTS = sorted({
    *ROOT.glob(".orchestra/tasks/*/codex-review*.md"),
    *ROOT.glob(".orchestra/tasks/*/review-*.md"),
})
MENTION_RE = re.compile(
    r"(?<!\w)(?:/[A-Za-z0-9_.-]+)+/[A-Za-z0-9_.-]+:\d+"
    r"|[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+:\d+"
)


def last_round(text: str) -> str:
    return re.split(r"(?im)^##\s+Round\b", text)[-1]


zero = []
nonzero = 0
for path in ARTIFACTS:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = review_findings(text)
    if findings:
        nonzero += 1
    else:
        mentions = sorted(set(MENTION_RE.findall(last_round(text))))
        zero.append((len(mentions), str(path.relative_to(ROOT)), mentions))

print(f"artifacts={len(ARTIFACTS)}")
print(f"zero_findings={len(zero)}")
print(f"at_least_one_finding={nonzero}")
for count, path, mentions in sorted(zero, reverse=True)[:20]:
    print(f"zero_mentions={count} {path} {mentions}")
