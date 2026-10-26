"""Class reports: one row per student plus the class average."""
import argparse
import sys
from typing import NamedTuple, Optional

from gradebook.course import Course
from gradebook.letters import Scale, letterFor
from gradebook.loader import loadCourse


class ReportRow(NamedTuple):
    student_id: str
    name: str
    percent: Optional[float]
    letter: Optional[str]


def buildReport(course: Course, scale: Optional[Scale] = None) -> list[ReportRow]:
    """One row per student, sorted by student id."""
    rows = []
    for student in course.students:
        percent = course.finalPercent(student.student_id)
        letter = letterFor(percent, scale) if percent is not None else None
        rows.append(ReportRow(student.student_id, student.name, percent, letter))
    return rows


def classAverage(rows: list[ReportRow]) -> Optional[float]:
    """Mean percentage of the students that have one."""
    values = [row.percent for row in rows if row.percent is not None]
    if not values:
        return None
    return sum(values) / len(values)


def formatPercent(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.1f}"


def formatReport(rows: list[ReportRow]) -> str:
    """Plain-text table with a closing class average line."""
    lines = [f"{'ID':<8} {'Name':<20} {'Pct':>6} Grade"]
    for row in rows:
        percent = formatPercent(row.percent)
        lines.append(f"{row.student_id:<8} {row.name:<20} {percent:>6} {row.letter or '-'}")
    lines.append(f"Class average: {formatPercent(classAverage(rows))}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    """Write the text report of a course export to a file."""
    parser = argparse.ArgumentParser(prog="python -m gradebook.report",
                                     description="Write the class report of a course.")
    parser.add_argument("course", help="course export (JSON)")
    parser.add_argument("output", help="text file to write")
    args = parser.parse_args(argv)
    try:
        course = loadCourse(args.course)
    except (OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f"error: cannot read {args.course}: {exc}\n")
        return 2
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(formatReport(buildReport(course)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
