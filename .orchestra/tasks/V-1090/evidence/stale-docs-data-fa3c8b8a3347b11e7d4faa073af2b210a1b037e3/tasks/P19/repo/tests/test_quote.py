import json

import pytest

from shiprate.parcels import Parcel
from shiprate.quote import Quote, load_data, main, quote_parcel
from shiprate.settings import Settings

RATES_CSV = "zone,max_grams,price\nZ1,1000,4.90\nZ1,5000,6.90\nZ3,5000,14.70\n"


@pytest.fixture
def data_dir(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "zones.csv").write_text("country,zone\nDE,Z1\nNO,Z3\n", encoding="utf-8")
    (folder / "rates.csv").write_text(RATES_CSV, encoding="utf-8")
    return folder


def test_quote_parcel(data_dir):
    zones, rates = load_data(str(data_dir))
    quote = quote_parcel(Parcel("P1", "NO", 1200), zones, rates, Settings())
    assert quote == Quote("P1", "Z3", 1470, 118)
    assert quote.total_cents == 1588


def test_quote_parcel_too_heavy(data_dir):
    zones, rates = load_data(str(data_dir))
    with pytest.raises(ValueError, match="more than 1000 g"):
        quote_parcel(Parcel("P1", "DE", 1200), zones, rates, Settings(max_weight_grams=1000))


def test_main_writes_csv(data_dir, tmp_path):
    parcels = tmp_path / "parcels.csv"
    parcels.write_text("id,country,grams\nP1,DE,800\nP2,NO,1200\n", encoding="utf-8")
    output = tmp_path / "quotes.csv"
    assert main([str(data_dir), str(parcels), str(output)]) == 0
    assert output.read_text(encoding="utf-8").splitlines() == [
        "id,zone,base,fuel,total,currency",
        "P1,Z1,4.90,0.39,5.29,EUR",
        "P2,Z3,14.70,1.18,15.88,EUR",
    ]


def test_main_uses_settings_file(data_dir, tmp_path):
    parcels = tmp_path / "parcels.csv"
    parcels.write_text("id,country,grams\nP1,DE,800\n", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"fuel_percent": 10, "currency": "CHF"}), encoding="utf-8")
    output = tmp_path / "quotes.csv"
    assert main([str(data_dir), str(parcels), str(output), "--settings", str(settings)]) == 0
    assert output.read_text(encoding="utf-8").splitlines()[1] == "P1,Z1,4.90,0.49,5.39,CHF"


def test_main_bad_input(data_dir, tmp_path):
    parcels = tmp_path / "parcels.csv"
    parcels.write_text("id,country,grams\nP1,XX,800\n", encoding="utf-8")
    output = tmp_path / "quotes.csv"
    assert main([str(data_dir), str(parcels), str(output)]) == 2
    assert main([str(tmp_path / "nowhere"), str(parcels), str(output)]) == 2
    assert not output.exists()
