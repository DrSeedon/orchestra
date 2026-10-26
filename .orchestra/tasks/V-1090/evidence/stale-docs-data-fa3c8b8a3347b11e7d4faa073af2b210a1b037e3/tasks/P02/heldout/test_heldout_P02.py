import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEADER = "sku,source,destination,quantity"
LEVELS = (
    "sku,location,on_hand,reserved\n"
    "BOLT-10,main,50,0\n"
    "BOLT-10,shop,2,0\n"
    "NUT-10,main,12,0\n"
    "NUT-10,shop,1,0\n"
    "PIN-2,main,0,0\n"
    "PIN-2,shop,40,5\n"
    "WASHER,main,3,0\n"
    "GLUE,main,5,0\n"
    "GLUE,depot,100,0\n"
    "TAPE,depot,0,0\n"
)
RULES = (
    "sku,reorder_point,reorder_qty,max_level\n"
    "BOLT-10,10,100,\n"
    "NUT-10,10,50,\n"
    "PIN-2,5,20,\n"
    "GLUE,4,10,\n"
    "TAPE,3,10,\n"
)


def run(*args):
    return subprocess.run([sys.executable, "-m", "stockroom.transfers", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(folder, name, text):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def read_lines(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [line.rstrip("\r\n") for line in fh if line.strip()]


def test_transfers_cover_short_locations(tmp_path):
    levels = write(str(tmp_path), "levels.csv", LEVELS)
    rules = write(str(tmp_path), "rules.csv", RULES)
    out = str(tmp_path / "transfers.csv")
    r = run(levels, rules, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out) == [
        HEADER,
        "BOLT-10,main,shop,9",
        "NUT-10,main,shop,1",
        "PIN-2,shop,main,6",
    ]


def test_no_transfer_when_both_locations_are_short(tmp_path):
    levels = write(str(tmp_path), "levels.csv",
                   "sku,location,on_hand,reserved\nNUT-10,main,4,0\nNUT-10,shop,20,15\n"
                   "BOLT-10,main,30,0\nBOLT-10,shop,30,0\n")
    rules = write(str(tmp_path), "rules.csv",
                  "sku,reorder_point,reorder_qty,max_level\nNUT-10,5,10,\nBOLT-10,10,10,\n")
    out = str(tmp_path / "transfers.csv")
    r = run(levels, rules, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out) == [HEADER]


def test_reserved_stock_is_not_given_away(tmp_path):
    levels = write(str(tmp_path), "levels.csv",
                   "sku,location,on_hand,reserved\nCAP-1,main,15,4\nCAP-1,shop,0,0\n")
    rules = write(str(tmp_path), "rules.csv", "sku,reorder_point,reorder_qty,max_level\nCAP-1,6,10,\n")
    out = str(tmp_path / "transfers.csv")
    r = run(levels, rules, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_lines(out) == [HEADER, "CAP-1,main,shop,4"]


def test_missing_levels_file(tmp_path):
    rules = write(str(tmp_path), "rules.csv", RULES)
    out = str(tmp_path / "transfers.csv")
    r = run(str(tmp_path / "nope.csv"), rules, out)
    assert r.returncode == 2
    assert not os.path.exists(out)


def test_missing_rules_file(tmp_path):
    levels = write(str(tmp_path), "levels.csv", LEVELS)
    out = str(tmp_path / "transfers.csv")
    r = run(levels, str(tmp_path / "nope.csv"), out)
    assert r.returncode == 2
    assert not os.path.exists(out)
