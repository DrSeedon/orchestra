import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADER = "member,name,barcode,due,notice,fine"

MEMBERS = "\n".join([
    "member_id,name,kind",
    "M2,Bea Jones,adult",
    "M1,Ada Park,adult",
    "K1,Kim Lo,child",
    "M3,Cy Dunn,adult",
]) + "\n"

COPIES = "\n".join([
    "barcode,title_id",
    "B1,dune",
    "B2,dune",
    "B3,emma",
    "B4,emma",
    "B5,odyssey",
    "B6,odyssey",
    "B7,ulysses",
    "B8,ulysses",
]) + "\n"

LOANS = "\n".join([
    "barcode,member_id,due,status",
    "B5,M2,2026-02-25,active",
    "B1,M2,2026-03-15,active",
    "B3,M1,2026-03-10,active",
    "B2,K1,2026-03-20,active",
    "B4,M1,2026-03-23,active",
    "B6,M3,2026-03-24,active",
    "B7,M3,2026-02-01,returned",
    "B8,K1,2026-03-19,active",
]) + "\n"


def make_branch(folder, settings=None):
    data = os.path.join(str(folder), "branch")
    os.makedirs(data)
    files = {"members.csv": MEMBERS, "copies.csv": COPIES, "loans.csv": LOANS}
    if settings is not None:
        files["settings.txt"] = settings
    for name, text in files.items():
        with open(os.path.join(data, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    return data


def run(*args):
    return subprocess.run([sys.executable, "-m", "loandesk.notices", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_notices_with_branch_settings(tmp_path):
    data = make_branch(tmp_path, "# branch north\nfine_per_day = 0.5\nfinal_notice_days = 10\n")
    out = os.path.join(str(tmp_path), "notices.csv")
    r = run(data, "2026-03-20", out)
    assert r.returncode == 0, r.stderr
    assert read_lines(out) == [
        HEADER,
        "K1,Kim Lo,B2,2026-03-20,reminder,0.00",
        "K1,Kim Lo,B8,2026-03-19,overdue,0.50",
        "M1,Ada Park,B3,2026-03-10,final,5.00",
        "M1,Ada Park,B4,2026-03-23,reminder,0.00",
        "M2,Bea Jones,B1,2026-03-15,overdue,2.50",
        "M2,Bea Jones,B5,2026-02-25,final,10.00",
    ]


def test_notices_with_default_settings(tmp_path):
    data = make_branch(tmp_path)
    out = os.path.join(str(tmp_path), "notices.csv")
    r = run(data, "2026-04-02", out)
    assert r.returncode == 0, r.stderr
    assert read_lines(out) == [
        HEADER,
        "K1,Kim Lo,B2,2026-03-20,overdue,3.25",
        "K1,Kim Lo,B8,2026-03-19,final,3.50",
        "M1,Ada Park,B3,2026-03-10,final,5.75",
        "M1,Ada Park,B4,2026-03-23,overdue,2.50",
        "M2,Bea Jones,B1,2026-03-15,final,4.50",
        "M2,Bea Jones,B5,2026-02-25,final,9.00",
        "M3,Cy Dunn,B6,2026-03-24,overdue,2.25",
    ]


def test_no_notices(tmp_path):
    data = make_branch(tmp_path, "loan_days = 14\n")
    out = os.path.join(str(tmp_path), "notices.csv")
    r = run(data, "2026-01-05", out)
    assert r.returncode == 0, r.stderr
    assert read_lines(out) == [HEADER]


def test_final_notice_days_below_one(tmp_path):
    out = os.path.join(str(tmp_path), "notices.csv")
    for n, value in enumerate(["0", "-3"]):
        data = make_branch(tmp_path / str(n), "final_notice_days = " + value + "\n")
        r = run(data, "2026-03-20", out)
        assert r.returncode == 2, value
        assert not os.path.exists(out)


def test_bad_day_and_bad_data(tmp_path):
    data = make_branch(tmp_path)
    out = os.path.join(str(tmp_path), "notices.csv")
    for day in ("2026-02-30", "tomorrow"):
        assert run(data, day, out).returncode == 2, day
        assert not os.path.exists(out)
    assert run(os.path.join(str(tmp_path), "nowhere"), "2026-03-20", out).returncode == 2
    assert not os.path.exists(out)
    with open(os.path.join(data, "loans.csv"), "w", encoding="utf-8") as fh:
        fh.write("barcode,member_id,status\nB1,M1,active\n")
    assert run(data, "2026-03-20", out).returncode == 2
    assert not os.path.exists(out)
