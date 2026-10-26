import pytest

from cronlint.crontab import CrontabEntry, parse_crontab, read_crontab, split_entry
from cronlint.errors import CronSyntaxError

CRONTAB = """\
# nightly jobs
SHELL=/bin/sh
MAILTO = ops@example.com

30 2 * * * /opt/backup.sh --full
@hourly   /usr/bin/sync -q
"""


def test_split_entry():
    assert split_entry("*/5 * * * * run.sh  a b") == ("*/5 * * * *", "run.sh  a b")
    assert split_entry("@daily run.sh") == ("@daily", "run.sh")


def test_split_entry_needs_command():
    with pytest.raises(CronSyntaxError, match="no command"):
        split_entry("0 0 * * *")


def test_parse_crontab_skips_comments_variables_and_blanks():
    assert parse_crontab(CRONTAB) == [
        CrontabEntry(5, "30 2 * * *", "/opt/backup.sh --full"),
        CrontabEntry(6, "@hourly", "/usr/bin/sync -q"),
    ]


def test_parse_crontab_reports_line_number():
    with pytest.raises(CronSyntaxError, match="line 2"):
        parse_crontab("# jobs\n@daily\n")


def test_read_crontab(tmp_path):
    path = tmp_path / "crontab"
    path.write_text(CRONTAB, encoding="utf-8")
    assert [entry.line for entry in read_crontab(str(path))] == [5, 6]
