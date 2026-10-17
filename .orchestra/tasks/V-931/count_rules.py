"""V-931: count rule units, dated units and units with a stated reason in rule sources.

Unit = one Markdown list item (with its continuation lines) or one prose paragraph
(blank-line separated) or one table data row. Headings, fenced code, YAML front matter,
table header/separator rows, lone XML tags and blank lines are not units.
Read-only: prints a TSV to stdout. Usage: python -I count_rules.py <label>=<path> ...
"""
import re
import sys
from pathlib import Path

DATE = re.compile(
    r"(?<![\d.$])(0?[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])(\.(20)?\d\d)?(?![\d%])"
    r"|20\d\d-\d\d-\d\d"
    r"|\b\d{1,2} (янв|фев|мар|апр|ма[яй]|июн|июл|авг|сен|окт|ноя|дек)\w*"
    r"|\b\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\b 20\d\d"
    r"|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* \d{1,2},? 20\d\d",
    re.IGNORECASE,
)
# Evidence-grade occasion: a task/issue reference, a measurement, a verbatim quote, a trigger.
EVIDENCE = re.compile(
    r"(?<![\w/])#\d{2,4}\b|\bV-\d{2,4}\b|\.orchestra/tasks/|measured|Measured|triggering|trigger was"
    r"|замер|измерен|дословно|verbatim|после того как|после того, как|инцидент|incident"
    r"|source:|источник:|Basis:|основание",
    re.IGNORECASE,
)
# Any stated justification, including purpose clauses.
ANY_REASON = re.compile(
    EVIDENCE.pattern + r"|because|since |reason|\bwhy\b|otherwise|so that|so the |→|cost of"
    r"|потому|причин|из-за|иначе|чтобы|ради|поскольку|так как|после ",
    re.IGNORECASE,
)


def units(text: str) -> list[str]:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), 0)
        lines = lines[end + 1:]
    out, cur, fence = [], [], False

    def flush():
        if cur:
            out.append(" ".join(cur))
            cur.clear()

    for raw in lines:
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            flush()
            fence = not fence
            continue
        if fence:
            continue
        if not s or s.startswith("#") or re.fullmatch(r"</?[\w-]+( [^>]*)?>", s):
            flush()
            continue
        if s.startswith("|"):
            flush()
            if not re.fullmatch(r"\|[\s:|-]+\|?", s):
                out.append(s)
            continue
        if re.match(r"([-*+]|\d+[.)])\s", s):
            flush()
        cur.append(s)
    flush()
    # The first row of each table is its header; drop rows immediately followed by a separator.
    return out


def table_headers(text: str) -> int:
    lines = [l.strip() for l in text.splitlines()]
    return sum(
        1 for a, b in zip(lines, lines[1:])
        if a.startswith("|") and re.fullmatch(r"\|[\s:|-]+\|?", b)
    )


def main() -> None:
    print("label\tfile\tbytes\tunits\tdated\treason_evidence\treason_any")
    for arg in sys.argv[1:]:
        label, _, path = arg.partition("=")
        p = Path(path)
        files = sorted(p.rglob("*.md")) if p.is_dir() else [p]
        for f in files:
            text = f.read_text(encoding="utf-8")
            us = units(text)
            n = len(us) - table_headers(text)
            dated = sum(bool(DATE.search(u)) for u in us)
            ev = sum(bool(EVIDENCE.search(u)) for u in us)
            anyr = sum(bool(ANY_REASON.search(u)) for u in us)
            print(f"{label}\t{f}\t{len(text.encode())}\t{n}\t{dated}\t{ev}\t{anyr}")


if __name__ == "__main__":
    main()
