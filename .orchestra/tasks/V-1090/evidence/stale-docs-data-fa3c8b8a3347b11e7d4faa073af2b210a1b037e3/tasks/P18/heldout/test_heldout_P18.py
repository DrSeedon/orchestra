import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {
    "a.csv": "sku,name,price\nA1,Apple,1.20\nB2,Banana,0.50\n",
    "b.csv": "SKU;Name;Stock\nB2;Banana split;7\nC3;Cherry;12\n;Mystery;3\n",
    "c.csv": "",
    "d.csv": "sku,name\nD4,Date\nE5\n",
    "notes.txt": "sku,name\nN1,Not a table\n",
}


def run(*args):
    return subprocess.run([sys.executable, "-m", "csvmerge.merge", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_folder(tmp_path, names):
    folder = tmp_path / "exports"
    folder.mkdir()
    for name in names:
        (folder / name).write_text(FILES[name], encoding="utf-8")
    return folder


def read_lines(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_merge_by_sku(tmp_path):
    folder = make_folder(tmp_path, FILES)
    out = tmp_path / "merged" / "stock.csv"
    r = run(str(folder), "sku", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out) == [
        "sku,name,price,stock",
        "A1,Apple,1.20,",
        "B2,Banana,0.50,",
        "C3,Cherry,,12",
    ]


def test_merge_by_other_key(tmp_path):
    folder = make_folder(tmp_path, FILES)
    out = tmp_path / "by_name.csv"
    r = run(str(folder), "Name", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out) == [
        "sku,name,price,stock",
        "A1,Apple,1.20,",
        "B2,Banana,0.50,",
        "B2,Banana split,,7",
        "C3,Cherry,,12",
        ",Mystery,,3",
    ]


def test_missing_key_column_exits_3(tmp_path):
    folder = make_folder(tmp_path, FILES)
    out = tmp_path / "by_price.csv"
    r = run(str(folder), "price", str(out))
    assert r.returncode == 3
    assert not out.exists()


def test_missing_folder_exits_2(tmp_path):
    out = tmp_path / "out.csv"
    r = run(str(tmp_path / "nowhere"), "sku", str(out))
    assert r.returncode == 2
    assert not out.exists()


def test_no_readable_file_exits_2(tmp_path):
    folder = make_folder(tmp_path, ["c.csv", "d.csv", "notes.txt"])
    out = tmp_path / "out.csv"
    r = run(str(folder), "sku", str(out))
    assert r.returncode == 2
    assert not out.exists()
