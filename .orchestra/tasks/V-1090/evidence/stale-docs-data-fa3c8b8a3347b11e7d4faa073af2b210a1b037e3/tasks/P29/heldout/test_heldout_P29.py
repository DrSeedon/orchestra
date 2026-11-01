import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLUB = {
    "books.csv": (
        "book_id,title,author,pages\n"
        "dune,Dune,Frank Herbert,300\n"
        "emma,Emma,Jane Austen,480\n"
    ),
    "members.csv": (
        "name,email,joined\n"
        "Dev,dev@example.com,2026-02-01\n"
        "Ben,ben@example.com,2025-03-02\n"
        "Ana,ana@example.com,2025-01-10\n"
        "Cleo,cleo@example.com,2025-06-15\n"
    ),
    "journal.csv": (
        "day,member,book_id,page\n"
        "2026-09-01,Ana,dune,50\n"
        "2026-09-10,Ana,dune,100\n"
        "2026-09-03,Ben,dune,77\n"
        "2026-09-05,Ana,dune,120\n"
        "2026-09-04,Cleo,emma,200\n"
        "2026-09-08,Cleo,dune,310\n"
    ),
    "meetings.csv": (
        "day,book_id,host,place\n"
        "2026-10-01,dune,Ana,Library room 2\n"
    ),
}


def run(*args):
    return subprocess.run([sys.executable, "-m", "bookclub.progress", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_club(tmp_path, **changes):
    folder = tmp_path / "club"
    folder.mkdir()
    files = dict(CLUB, **changes)
    for name, text in files.items():
        with open(str(folder / name), "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return str(folder)


def lines(path):
    with open(path, encoding="utf-8") as fh:
        return [line for line in fh.read().splitlines() if line]


def test_progress_of_a_book(tmp_path):
    club = make_club(tmp_path)
    out = str(tmp_path / "progress.csv")
    r = run(club, "dune", out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines(out) == [
        "member,progress,percent,last",
        "Cleo,300/300,100.0,2026-09-08",
        "Ana,120/300,40.0,2026-09-10",
        "Ben,77/300,25.7,2026-09-03",
        "Dev,0/300,0.0,",
    ]


def test_same_page_sorted_by_name(tmp_path):
    club = make_club(tmp_path)
    out = str(tmp_path / "progress.csv")
    r = run(club, "emma", out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines(out) == [
        "member,progress,percent,last",
        "Cleo,200/480,41.7,2026-09-04",
        "Ana,0/480,0.0,",
        "Ben,0/480,0.0,",
        "Dev,0/480,0.0,",
    ]


def test_unknown_book(tmp_path):
    club = make_club(tmp_path)
    out = str(tmp_path / "progress.csv")
    r = run(club, "ulysses", out)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_invalid_club_folder(tmp_path):
    club = make_club(tmp_path, **{"journal.csv": "day,member,book_id,page\n2026-09-01,Zoe,dune,5\n"})
    out = str(tmp_path / "progress.csv")
    r = run(club, "dune", out)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_missing_club_folder(tmp_path):
    out = str(tmp_path / "progress.csv")
    r = run(str(tmp_path / "nowhere"), "dune", out)
    assert r.returncode == 2
    assert not os.path.exists(out)
