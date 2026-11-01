import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ZONES = "country,zone\nDE,Z1\nFR,Z2\nIS,Z4\nNO,Z3\n"
RATES = (
    "zone,max_grams,price\n"
    "Z1,1000,4.90\nZ1,5000,6.90\nZ2,5000,8.10\nZ3,5000,14.70\nZ4,5000,18.40\nZ4,20000,32.15\n"
)
PARCELS = "id,country,grams\nP1,DE,800\nP2,IS,4200\nP3,NO,1200\nP4,IS,12000\n"


def run(*args):
    return subprocess.run([sys.executable, "-m", "shiprate.remote", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def make_inputs(tmp_path, parcels=PARCELS):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "zones.csv").write_text(ZONES, encoding="utf-8")
    (data / "rates.csv").write_text(RATES, encoding="utf-8")
    parcel_file = tmp_path / "parcels.csv"
    parcel_file.write_text(parcels, encoding="utf-8")
    return str(data), str(parcel_file)


def write_settings(tmp_path, values):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return str(path)


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_default_percent(tmp_path):
    data, parcels = make_inputs(tmp_path)
    out = tmp_path / "remote.json"
    r = run(data, parcels, "Z4,Z3", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "currency": "EUR",
        "percent": 15,
        "parcels": [
            {"id": "P1", "zone": "Z1", "base": "4.90", "surcharge": "0.00"},
            {"id": "P2", "zone": "Z4", "base": "18.40", "surcharge": "2.76"},
            {"id": "P3", "zone": "Z3", "base": "14.70", "surcharge": "2.21"},
            {"id": "P4", "zone": "Z4", "base": "32.15", "surcharge": "4.82"},
        ],
        "surcharge": "9.79",
    }


def test_percent_and_currency_from_settings(tmp_path):
    data, parcels = make_inputs(tmp_path)
    settings = write_settings(tmp_path, {"remote_percent": 20, "currency": "CHF"})
    out = tmp_path / "remote.json"
    r = run(data, parcels, "Z3,Z4", str(out), "--settings", settings)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(out) == {
        "currency": "CHF",
        "percent": 20,
        "parcels": [
            {"id": "P1", "zone": "Z1", "base": "4.90", "surcharge": "0.00"},
            {"id": "P2", "zone": "Z4", "base": "18.40", "surcharge": "3.68"},
            {"id": "P3", "zone": "Z3", "base": "14.70", "surcharge": "2.94"},
            {"id": "P4", "zone": "Z4", "base": "32.15", "surcharge": "6.43"},
        ],
        "surcharge": "13.05",
    }


def test_remote_zone_without_parcels(tmp_path):
    data, parcels = make_inputs(tmp_path)
    out = tmp_path / "remote.json"
    r = run(data, parcels, "Z2", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    result = read_json(out)
    assert [p["surcharge"] for p in result["parcels"]] == ["0.00", "0.00", "0.00", "0.00"]
    assert result["surcharge"] == "0.00"


def test_unknown_zone_exits_2(tmp_path):
    data, parcels = make_inputs(tmp_path)
    out = tmp_path / "remote.json"
    r = run(data, parcels, "Z4,Z9", str(out))
    assert r.returncode == 2
    assert not out.exists()


def test_invalid_input_exits_2(tmp_path):
    data, parcels = make_inputs(tmp_path)
    out = tmp_path / "remote.json"
    for values in ({"remote_percent": "20"}, {"remote_percent": -5}, {"max_weight_grams": 10000}):
        r = run(data, parcels, "Z4", str(out), "--settings", write_settings(tmp_path, values))
        assert r.returncode == 2, values
    data, parcels = make_inputs(tmp_path / "unknown", PARCELS + "P5,XX,100\n")
    r = run(data, parcels, "Z4", str(out))
    assert r.returncode == 2
    assert not out.exists()
