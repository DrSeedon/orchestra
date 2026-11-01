import pytest

from invoice_tool.normalize import normalize_row, normalize_rows, parse_amount, parse_date

GOOD_ROW = {"invoice_no": " a-17 ", "date": "05/04/2024", "amount": "99.90", "currency": "eur"}


def test_parse_date_formats():
    assert parse_date("2024-03-01") == "2024-03-01"
    assert parse_date("01/03/2024") == "2024-03-01"
    assert parse_date("01.03.2024") == "2024-03-01"
    assert parse_date("20240301") == "2024-03-01"


def test_parse_date_rejects_unknown_format():
    with pytest.raises(ValueError, match="unrecognised date"):
        parse_date("March 1st")


@pytest.mark.parametrize(
    "text, cents",
    [("10.00", 1000), ("1,234.50", 123450), ("12,5", 1250), ("-3.10", -310), (" 7 ", 700)],
)
def test_parse_amount(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "ten", "1.2.3"])
def test_parse_amount_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_normalize_row():
    assert normalize_row(GOOD_ROW, "acme") == {
        "supplier": "acme",
        "invoice_no": "A-17",
        "date": "2024-04-05",
        "amount_cents": 9990,
        "currency": "EUR",
    }


def test_normalize_row_rejects_unknown_currency():
    with pytest.raises(ValueError, match="unknown currency"):
        normalize_row(dict(GOOD_ROW, currency="XYZ"), "acme")


def test_normalize_rows_skips_bad_rows(capsys):
    rows = [GOOD_ROW, dict(GOOD_ROW, date="yesterday"), {"invoice_no": "A-3"}]
    records = normalize_rows(rows, "acme")
    assert [record["invoice_no"] for record in records] == ["A-17"]
    out = capsys.readouterr().out
    assert "acme: row 2 skipped" in out
    assert "acme: row 3 skipped" in out
