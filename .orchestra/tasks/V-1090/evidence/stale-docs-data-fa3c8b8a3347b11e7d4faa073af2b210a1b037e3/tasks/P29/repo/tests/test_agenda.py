from bookclub.agenda import main


def test_agenda(club_dir, tmp_path, capsys):
    out = tmp_path / "agenda.txt"
    assert main([club_dir, "2026-09-10", str(out)]) == 0
    assert out.read_text(encoding="utf-8").splitlines() == [
        "Book club meeting on 2026-09-17",
        "Place: Library room 2",
        "Host: Rosa",
        "Book: Solaris by Stanislaw Lem (204 pages)",
        "",
        "Invited:",
        "- Karl <karl@example.com>",
        "- Rosa <rosa@example.com>",
    ]
    assert "wrote the agenda for 2026-09-17" in capsys.readouterr().out


def test_agenda_no_meeting(club_dir, tmp_path):
    out = tmp_path / "agenda.txt"
    assert main([club_dir, "2026-12-01", str(out)]) == 2
    assert not out.exists()


def test_agenda_bad_date(club_dir, tmp_path):
    out = tmp_path / "agenda.txt"
    assert main([club_dir, "next week", str(out)]) == 2
    assert not out.exists()
