from linkcheck.extract import Link
from linkcheck.report import format_problem, format_summary, render_report
from linkcheck.scanner import Problem


def make_problem(tmp_path, name, line, target="x.md"):
    return Problem(Link(tmp_path / name, line, target), f"missing file: {target}")


def test_format_problem_relative(tmp_path):
    problem = make_problem(tmp_path, "docs/a.md", 3)
    assert format_problem(problem, tmp_path) == "docs/a.md:3: x.md: missing file: x.md"


def test_format_summary():
    assert format_summary([], 4) == "4 documents checked, no broken links"


def test_render_report_sorts_problems(tmp_path):
    problems = [make_problem(tmp_path, "b.md", 1), make_problem(tmp_path, "a.md", 9, "y.md")]
    assert render_report(problems, 5, tmp_path).splitlines() == [
        "a.md:9: y.md: missing file: y.md",
        "b.md:1: x.md: missing file: x.md",
        "2 broken links in 2 of 5 documents",
    ]
