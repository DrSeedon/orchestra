import os

from stockroom.loader import load_levels_csv, load_rules_csv, parse_quantity


def write_csv(tmp_path, name, text):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def test_parse_quantity():
    assert parse_quantity(" 12 ") == 12


def test_load_levels_csv_skips_bad_rows(tmp_path, caplog):
    path = write_csv(
        tmp_path,
        "levels.csv",
        "sku,location,on_hand,reserved\nBOLT-10,main,50,5\nNUT-10,main,lots,\nPIN-2,shop,7,\n",
    )
    levels = load_levels_csv(path)
    assert [(lv.sku, lv.on_hand, lv.reserved) for lv in levels] == [
        ("BOLT-10", 50, 5),
        ("PIN-2", 7, 0),
    ]
    assert "levels.csv:3: skipped level row" in caplog.text


def test_load_rules_csv(tmp_path, caplog):
    path = write_csv(
        tmp_path,
        "rules.csv",
        "sku,reorder_point,reorder_qty,max_level\nBOLT-10,50,200,\nNUT-10,10,100,60\n"
        "NUT-10,12,100,\nPIN-2,-1,5,\n",
    )
    rules = load_rules_csv(path)
    assert set(rules) == {"BOLT-10", "NUT-10"}
    assert rules["BOLT-10"].max_level is None
    assert rules["NUT-10"].reorder_point == 12
    assert "duplicate rule for NUT-10" in caplog.text
    assert "rules.csv:5: skipped rule row" in caplog.text
