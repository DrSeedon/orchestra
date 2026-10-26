from roomsched.rooms import load_rooms


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_rooms_keys_rooms_by_name(tmp_path):
    path = write(tmp_path / "rooms.csv", "name,capacity,opens,closes\nAurora,8,08:00,18:00\nBorealis,4,09:00,17:00\n")
    rooms, error = load_rooms(path)
    assert error is None
    assert sorted(rooms) == ["Aurora", "Borealis"]
    assert rooms["Borealis"] == {"name": "Borealis", "capacity": 4, "opens": 540, "closes": 1020}


def test_load_rooms_reports_bad_rows_with_line_number(tmp_path):
    path = write(tmp_path / "rooms.csv", "name,capacity,opens,closes\nAurora,8,08:00,18:00\nBorealis,0,09:00,17:00\n")
    rooms, error = load_rooms(path)
    assert rooms is None
    assert ":3:" in error and "capacity" in error


def test_load_rooms_rejects_duplicate_names(tmp_path):
    path = write(tmp_path / "rooms.csv", "name,capacity,opens,closes\nAurora,8,08:00,18:00\nAurora,6,08:00,12:00\n")
    rooms, error = load_rooms(path)
    assert rooms is None
    assert "duplicate room Aurora" in error


def test_load_rooms_reports_missing_columns_and_files(tmp_path):
    path = write(tmp_path / "rooms.csv", "name,capacity\nAurora,8\n")
    rooms, error = load_rooms(path)
    assert rooms is None and "opens, closes" in error
    rooms, error = load_rooms(str(tmp_path / "missing.csv"))
    assert rooms is None and "cannot read" in error
