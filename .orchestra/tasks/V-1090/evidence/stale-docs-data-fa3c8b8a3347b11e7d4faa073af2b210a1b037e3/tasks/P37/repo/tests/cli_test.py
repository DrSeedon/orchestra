from pricewatch.cli import main


def write(tmp_path, text):
    path = tmp_path / "prices.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_summary(tmp_path, capsys):
    path = write(tmp_path, "sku,name,price\nA-1,Desk lamp,20\nB-2,Stapler,8.25\n")
    assert main(["summary", path]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "items: 2",
        "lowest: 8.25",
        "highest: 20.00",
        "average: 14.13",
    ]


def test_cheapest(tmp_path, capsys):
    path = write(tmp_path, "sku,name,price\nA-1,Desk lamp,20\nB-2,Stapler,8.25\n")
    assert main(["cheapest", path, "--count", "1"]) == 0
    assert capsys.readouterr().out.splitlines() == ["B-2             8.25  Stapler"]


def test_bad_file_gives_status_2(tmp_path, capsys):
    path = write(tmp_path, "sku,name\nA-1,Desk lamp\n")
    assert main(["summary", path]) == 2
    assert "missing column price" in capsys.readouterr().err


def test_missing_file_gives_status_2(tmp_path, capsys):
    assert main(["summary", str(tmp_path / "none.csv")]) == 2
    assert "error:" in capsys.readouterr().err
