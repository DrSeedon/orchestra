import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRIPS = (
    "date,car,km,driver,riders\n"
    "2026-10-01,golf,100,Ana,Cleo;Ben\n"
    "2026-10-02,van,50,Ben,\n"
    "2026-10-03,golf,35,Cleo,Ana\n"
    "2026-10-04,van,120,Dev,Ana;Ben;Cleo\n"
)

VEHICLES = "car,consumption\ngolf,6.2\nvan,9.5\n"


def run(*args):
    return subprocess.run([sys.executable, "-m", "fuelcost.split", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def make_input(tmp_path, trips=TRIPS, settings=None):
    paths = [write(str(tmp_path / "trips.csv"), trips), write(str(tmp_path / "vehicles.csv"), VEHICLES),
             str(tmp_path / "split.csv")]
    if settings is not None:
        paths += ["--settings", write(str(tmp_path / "settings.json"), settings)]
    return paths


def lines(path):
    with open(path, encoding="utf-8") as fh:
        return [line for line in fh.read().splitlines() if line]


def test_driver_pays_by_default(tmp_path):
    args = make_input(tmp_path)
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines(args[2]) == [
        "name,trips,share",
        "Ana,3,11.10",
        "Ben,3,17.88",
        "Cleo,3,11.10",
        "Dev,1,5.28",
    ]


def test_driver_free(tmp_path):
    args = make_input(tmp_path, settings='{"driver": "free"}')
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines(args[2]) == [
        "name,trips,share",
        "Ana,3,11.04",
        "Ben,3,21.55",
        "Cleo,3,12.77",
        "Dev,1,0.00",
    ]


def test_trip_cost_follows_settings(tmp_path):
    args = make_input(tmp_path, settings='{"driver": "pays", "wear": "0.01"}')
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines(args[2]) == [
        "name,trips,share",
        "Ana,3,11.92",
        "Ben,3,19.01",
        "Cleo,3,11.90",
        "Dev,1,5.58",
    ]


def test_bad_driver_setting(tmp_path):
    args = make_input(tmp_path, settings='{"driver": "sometimes"}')
    r = run(*args)
    assert r.returncode == 2
    assert not os.path.exists(args[2])


def test_invalid_inputs(tmp_path):
    args = make_input(tmp_path, trips=TRIPS + "2026-10-05,bus,10,Ana,Ben\n")
    r = run(*args)
    assert r.returncode == 2
    assert not os.path.exists(args[2])
    out = str(tmp_path / "split.csv")
    r = run(str(tmp_path / "nope.csv"), args[1], out)
    assert r.returncode == 2
    assert not os.path.exists(out)
