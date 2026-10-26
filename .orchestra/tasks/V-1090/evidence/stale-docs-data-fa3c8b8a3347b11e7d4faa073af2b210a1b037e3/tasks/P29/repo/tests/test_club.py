import os

import pytest

from bookclub.club import load_club


def test_load_club(club_dir):
    club = load_club(club_dir)
    assert sorted(club.books) == ["middlemarch", "solaris"]
    assert len(club.members) == 3
    assert len(club.journal) == 3
    assert [m.place for m in club.meetings] == ["Library room 2", "Cafe Lindo"]


def test_load_club_unknown_member(club_dir):
    with open(os.path.join(club_dir, "journal.csv"), "a", encoding="utf-8") as handle:
        handle.write("2026-09-13,Zoe,solaris,10\n")
    with pytest.raises(ValueError, match="unknown member Zoe"):
        load_club(club_dir)


def test_load_club_unknown_book(club_dir):
    with open(os.path.join(club_dir, "meetings.csv"), "a", encoding="utf-8") as handle:
        handle.write("2026-11-20,dune,Rosa,Cafe Lindo\n")
    with pytest.raises(ValueError, match="unknown book dune"):
        load_club(club_dir)


def test_load_club_missing_file(tmp_path):
    with pytest.raises(OSError):
        load_club(str(tmp_path))
