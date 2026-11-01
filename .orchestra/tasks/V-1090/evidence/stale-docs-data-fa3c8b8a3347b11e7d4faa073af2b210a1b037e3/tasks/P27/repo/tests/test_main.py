import logging

from rentroll.__main__ import main


def test_main_writes_rent_roll(sample_files, tmp_path):
    out = tmp_path / "roll.csv"
    assert main([sample_files[0], sample_files[1], str(out), "--sort", "balance"]) == 0
    assert out.read_text(encoding="utf-8").splitlines()[1].startswith("1B,")


def test_main_reports_units_without_tenant(write_file, sample_files, tmp_path, caplog):
    ledger = write_file("extra.csv", "date,unit,kind,amount\n2026-09-01,9Z,charge,10\n")
    with caplog.at_level(logging.WARNING, logger="rentroll"):
        assert main([sample_files[0], ledger, str(tmp_path / "roll.csv")]) == 0
    assert "9Z" in caplog.text


def test_main_missing_file(sample_files, tmp_path):
    out = tmp_path / "roll.csv"
    assert main([sample_files[0], str(tmp_path / "none.csv"), str(out)]) == 2
    assert not out.exists()
