import csv
import os

from photosort.catalog import main


def make_file(root, relpath, content=b"x"):
    path = os.path.join(root, *relpath.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def test_catalog_lists_photos_with_dates_and_copies(tmp_path):
    source = os.path.join(str(tmp_path), "photos")
    make_file(source, "IMG_20240315_101500.jpg", b"aaa")
    make_file(source, "backup/scan.jpg", b"aaa")
    make_file(source, "2024-01-05 08.00.00.png", b"bb")
    make_file(source, "notes.txt")
    output = os.path.join(str(tmp_path), "out", "catalog.csv")
    assert main([source, output]) == 0
    assert read_rows(output) == [
        ["path", "size", "taken", "duplicate_of"],
        ["2024-01-05 08.00.00.png", "2", "2024-01-05", ""],
        ["IMG_20240315_101500.jpg", "3", "2024-03-15", ""],
        ["backup/scan.jpg", "3", "", "IMG_20240315_101500.jpg"],
    ]


def test_catalog_rejects_a_missing_source(tmp_path):
    output = os.path.join(str(tmp_path), "catalog.csv")
    assert main([os.path.join(str(tmp_path), "missing"), output]) == 2
    assert not os.path.exists(output)


def test_catalog_needs_two_arguments(tmp_path):
    assert main([str(tmp_path)]) == 2
