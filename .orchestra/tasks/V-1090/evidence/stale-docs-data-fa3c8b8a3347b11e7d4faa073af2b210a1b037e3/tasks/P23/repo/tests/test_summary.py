from tipjar.summary import main


def write_bill(tmp_path):
    path = tmp_path / "bill.csv"
    path.write_text("item,amount\npizza,12.50\npasta,14.00\nwine,28.00\n", encoding="utf-8")
    return str(path)


def test_summary_with_tip(tmp_path):
    output = tmp_path / "summary.txt"
    assert main([write_bill(tmp_path), "3", str(output), "--tip", "15"]) == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[3].split() == ["subtotal", "54.50"]
    assert lines[4].split() == ["tip", "(15%)", "8.18"]
    assert lines[5].split() == ["total", "62.68"]
    assert [line.split()[-1] for line in lines[7:]] == ["20.90", "20.89", "20.89"]


def test_summary_without_tip(tmp_path):
    output = tmp_path / "summary.txt"
    assert main([write_bill(tmp_path), "2", str(output)]) == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[4].split() == ["tip", "-"]
    assert [line.split()[-1] for line in lines[7:]] == ["27.25", "27.25"]


def test_summary_rejects_a_bad_tip(tmp_path, capsys):
    output = tmp_path / "summary.txt"
    assert main([write_bill(tmp_path), "2", str(output), "--tip", "lots"]) == 2
    assert "error" in capsys.readouterr().err
    assert not output.exists()


def test_summary_rejects_a_missing_bill(tmp_path):
    output = tmp_path / "summary.txt"
    assert main([str(tmp_path / "missing.csv"), "2", str(output)]) == 2
    assert not output.exists()
