import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*args):
    return subprocess.run([sys.executable, "-m", "notegrep.backlinks", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(folder, rel, text):
    path = os.path.join(str(folder), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def make_garden(folder):
    write(folder, "garden.md",
          "# Garden\nSee [[Compost]] and [[Kitchen|the kitchen]].\nMore in [[Compost#Bins]].\n")
    write(folder, "kitchen.md",
          "# Kitchen\nHerbs from [[garden#Beds]]. Tools in [[Shed]] and [[Attic]].\n")
    write(folder, "archive/compost.md", "Bins. Back to [[Garden]]. Needs [[Pantry]].\n")
    write(folder, "seeds.md", "# Seeds\nNo links here.\n")
    write(folder, "notes.txt", "[[garden]] is not a note\n")
    write(folder, ".trash/gone.md", "[[Seeds]] [[Nowhere]]\n")


def read_report(folder):
    with open(os.path.join(str(folder), "backlinks.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_backlinks_report(tmp_path):
    make_garden(tmp_path)
    r = run(str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert read_report(tmp_path) == {
        "notes": 4,
        "links": 7,
        "backlinks": {
            "compost": ["garden"],
            "garden": ["compost", "kitchen"],
            "kitchen": ["garden"],
            "seeds": [],
        },
        "broken": {"compost": ["Pantry"], "kitchen": ["Shed", "Attic"]},
    }


def test_notes_without_links(tmp_path):
    write(tmp_path, "alpha.md", "# Alpha\nplain text\n")
    write(tmp_path, "beta.md", "plain [link](alpha.md) only\n")
    r = run(str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert read_report(tmp_path) == {
        "notes": 2, "links": 0, "backlinks": {"alpha": [], "beta": []}, "broken": {},
    }


def test_empty_folder(tmp_path):
    r = run(str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert read_report(tmp_path) == {"notes": 0, "links": 0, "backlinks": {}, "broken": {}}


def test_missing_folder(tmp_path):
    r = run(str(tmp_path / "missing"))
    assert r.returncode == 2
    assert os.listdir(str(tmp_path)) == []


def test_file_instead_of_folder(tmp_path):
    write(tmp_path, "garden.md", "# Garden\n[[Compost]]\n")
    r = run(str(tmp_path / "garden.md"))
    assert r.returncode == 2
    assert os.listdir(str(tmp_path)) == ["garden.md"]
