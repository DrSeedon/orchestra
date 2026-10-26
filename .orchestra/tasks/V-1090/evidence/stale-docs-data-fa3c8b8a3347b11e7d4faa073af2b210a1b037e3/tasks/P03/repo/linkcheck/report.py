"""Turn link problems into text for the terminal."""
from pathlib import Path

from linkcheck.scanner import Problem


def format_problem(problem: Problem, root: Path | None = None) -> str:
    """Format one problem as ``file:line: target: message``.

    :param problem: the problem to format.
    :param root: if given, the file is shown relative to it.
    :returns: one line of text.
    """
    source = problem.link.source
    if root is not None:
        source = source.relative_to(root)
    return f"{source.as_posix()}:{problem.link.line}: {problem.link.target}: {problem.message}"


def format_summary(problems: list[Problem], document_count: int) -> str:
    """Return the closing summary line of a report.

    :param problems: all problems found.
    :param document_count: number of documents checked.
    :returns: one line of text.
    """
    if not problems:
        return f"{document_count} documents checked, no broken links"
    files = len({problem.link.source for problem in problems})
    return f"{len(problems)} broken links in {files} of {document_count} documents"


def render_report(problems: list[Problem], document_count: int, root: Path | None = None) -> str:
    """Return the full report: one line per problem, sorted, then the summary.

    :param problems: all problems found.
    :param document_count: number of documents checked.
    :param root: if given, files are shown relative to it.
    :returns: the report text.
    """
    ordered = sorted(problems, key=lambda problem: (str(problem.link.source), problem.link.line))
    lines = [format_problem(problem, root) for problem in ordered]
    lines.append(format_summary(problems, document_count))
    return "\n".join(lines)
