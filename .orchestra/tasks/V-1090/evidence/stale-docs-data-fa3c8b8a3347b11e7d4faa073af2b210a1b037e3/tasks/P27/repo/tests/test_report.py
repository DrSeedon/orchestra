from rentroll.ledger import load_ledger
from rentroll.report import SortOrder, rent_roll, write_rent_roll
from rentroll.tenants import load_tenants


def test_rent_roll_by_unit(sample_files):
    lines = rent_roll(load_tenants(sample_files[0]), load_ledger(sample_files[1]))
    assert [line.unit for line in lines] == ["1A", "1B", "2A"]
    assert (lines[1].charged, lines[1].paid, lines[1].balance) == (98000, 50000, 48000)
    assert lines[2].paid == 114000


def test_rent_roll_by_balance(sample_files):
    lines = rent_roll(load_tenants(sample_files[0]), load_ledger(sample_files[1]), SortOrder.BALANCE)
    assert [line.unit for line in lines] == ["1B", "1A", "2A"]


def test_write_rent_roll(sample_files, tmp_path):
    lines = rent_roll(load_tenants(sample_files[0]), load_ledger(sample_files[1]))
    out = tmp_path / "roll.csv"
    write_rent_roll(lines, str(out))
    assert out.read_text(encoding="utf-8").splitlines() == [
        "unit,tenant,rent,charged,paid,balance",
        "1A,Ana Ruiz,1250.50,1250.50,1250.50,0.00",
        "1B,Ben Cole,980.00,980.00,500.00,480.00",
        "2A,Cora Diaz,1100.00,1100.00,1140.00,-40.00",
        "total,,,,,440.00",
    ]
