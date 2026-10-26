from budgetbook.report import isMonth, main

LEDGER = (
    "date,category,kind,amount,note\n"
    "2024-03-02,groceries,expense,120.50,\n"
    "2024-03-08,groceries,refund,10.00,\n"
    "2024-03-09,fun,expense,60.10,cinema\n"
    "2024-03-25,salary,income,2500.00,\n"
    "2024-02-28,groceries,expense,300.00,\n"
)


def writeFile(folder, name, text):
    target = folder / name
    target.write_text(text, encoding="utf-8")
    return str(target)


def readLines(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [line.rstrip("\r\n") for line in fh]


def test_is_month():
    assert isMonth("2024-03")
    assert not isMonth("2024-3")
    assert not isMonth("2024-13")
    assert not isMonth("March")


def test_report_without_budgets(tmp_path):
    ledger = writeFile(tmp_path, "ledger.csv", LEDGER)
    output = str(tmp_path / "report.csv")
    assert main([ledger, "2024-03", output]) == 0
    assert readLines(output) == [
        "category,spent,budget,remaining",
        "fun,60.10,,",
        "groceries,110.50,,",
    ]


def test_report_with_budgets(tmp_path):
    ledger = writeFile(tmp_path, "ledger.csv", LEDGER)
    budgets = writeFile(tmp_path, "budgets.csv", "category,limit\ngroceries,100\nbooks,30\n")
    output = str(tmp_path / "report.csv")
    assert main([ledger, "2024-03", output, "--budgets", budgets]) == 0
    assert readLines(output) == [
        "category,spent,budget,remaining",
        "books,0.00,30.00,30.00",
        "fun,60.10,,",
        "groceries,110.50,100.00,-10.50",
    ]


def test_bad_month_or_missing_file_exit_2(tmp_path):
    ledger = writeFile(tmp_path, "ledger.csv", LEDGER)
    output = tmp_path / "report.csv"
    assert main([ledger, "03/2024", str(output)]) == 2
    assert main([str(tmp_path / "missing.csv"), "2024-03", str(output)]) == 2
    assert not output.exists()
