import pytest

from cronlint.cli import main


@pytest.fixture
def crontab(tmp_path):
    path = tmp_path / "crontab"
    path.write_text("# jobs\n0 */12 * * * /opt/a.sh\n0 0 30 2 * /opt/b.sh\n", encoding="utf-8")
    return str(path)


def test_check_clean_file(tmp_path, capsys):
    path = tmp_path / "crontab"
    path.write_text("@daily /opt/a.sh\n", encoding="utf-8")
    assert main(["check", str(path)]) == 0
    assert capsys.readouterr().out == "0 bad entries\n"


def test_check_reports_bad_entries(tmp_path, capsys):
    path = tmp_path / "crontab"
    path.write_text("61 * * * * /opt/a.sh\n@daily /opt/b.sh\n", encoding="utf-8")
    assert main(["check", str(path)]) == 1
    out = capsys.readouterr().out
    assert "line 1: minute: 61 is outside 0-59" in out
    assert out.endswith("1 bad entry\n")


def test_next_lists_runs(crontab, capsys):
    assert main(["next", crontab, "--start", "2026-01-01 06:00", "--count", "2"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "line 2: 2026-01-01 12:00, 2026-01-02 00:00  /opt/a.sh",
        "line 3: never  /opt/b.sh",
    ]


def test_missing_file_exits_2(tmp_path, capsys):
    assert main(["check", str(tmp_path / "nope")]) == 2
    assert "error:" in capsys.readouterr().err


def test_bad_start_time_is_rejected(crontab):
    with pytest.raises(SystemExit):
        main(["next", crontab, "--start", "tomorrow"])
