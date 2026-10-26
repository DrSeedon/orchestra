import pytest

from shiprate.csvfiles import read_rows
from shiprate.parcels import Parcel, load_parcels
from shiprate.rates import Band, load_rates, price_for
from shiprate.zones import load_zones, zone_for


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_read_rows_trims_and_skips_blank_rows(tmp_path):
    path = write(tmp_path / "t.csv", "a,b,c\n 1 ,2,x\n,,\n3,4,y\n")
    assert read_rows(path, ("a", "b")) == [(2, {"a": "1", "b": "2"}), (4, {"a": "3", "b": "4"})]


def test_read_rows_missing_column(tmp_path):
    with pytest.raises(ValueError, match="missing columns b"):
        read_rows(write(tmp_path / "t.csv", "a\n1\n"), ("a", "b"))


def test_zones(tmp_path):
    zones = load_zones(write(tmp_path / "zones.csv", "country,zone\nde,z1\nNO,Z3\n"))
    assert zones == {"DE": "Z1", "NO": "Z3"}
    assert zone_for("no", zones) == "Z3"
    with pytest.raises(ValueError, match="'XX'"):
        zone_for("XX", zones)


def test_zones_repeated_country(tmp_path):
    with pytest.raises(ValueError, match="DE appears twice"):
        load_zones(write(tmp_path / "zones.csv", "country,zone\nDE,Z1\nde,Z2\n"))


def test_rates(tmp_path):
    rates = load_rates(write(tmp_path / "rates.csv",
                             "zone,max_grams,price\nZ1,5000,6.90\nZ1,1000,4.90\nZ2,5000,8.10\n"))
    assert rates["Z1"] == [Band("Z1", 1000, 490), Band("Z1", 5000, 690)]
    assert price_for("Z1", 1000, rates) == 490
    assert price_for("Z1", 1001, rates) == 690
    assert price_for("Z2", 10, rates) == 810
    with pytest.raises(ValueError, match="no rate for 5001 g"):
        price_for("Z1", 5001, rates)
    with pytest.raises(ValueError, match="zone Z9"):
        price_for("Z9", 10, rates)


def test_rates_bad_price(tmp_path):
    with pytest.raises(ValueError, match="rates.csv:3"):
        load_rates(write(tmp_path / "rates.csv", "zone,max_grams,price\nZ1,1000,4.90\nZ1,2000,4.9.0\n"))


def test_parcels(tmp_path):
    parcels = load_parcels(write(tmp_path / "parcels.csv", "id,country,grams\nP1,de,800\nP2,NO,1200\n"))
    assert parcels == [Parcel("P1", "DE", 800), Parcel("P2", "NO", 1200)]


@pytest.mark.parametrize("rows", ["P1,DE,0\n", "P1,DE,1.5\n", ",DE,10\n", "P1,DE,10\nP1,NO,20\n"])
def test_parcels_invalid(tmp_path, rows):
    with pytest.raises(ValueError):
        load_parcels(write(tmp_path / "parcels.csv", "id,country,grams\n" + rows))
