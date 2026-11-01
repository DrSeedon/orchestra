import os
from datetime import date

from photosort.scan import scan_photos, undated


def make_file(root, relpath, content=b"x"):
    path = os.path.join(root, *relpath.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def test_scan_finds_photos_in_subfolders(tmp_path):
    root = str(tmp_path)
    make_file(root, "trip/IMG_20240315_101500.jpg", b"abc")
    make_file(root, "2024-01-05 08.00.00.png")
    make_file(root, "notes.txt")
    photos = scan_photos(root)
    assert [photo.relpath for photo in photos] == ["2024-01-05 08.00.00.png", "trip/IMG_20240315_101500.jpg"]
    assert photos[1].size == 3
    assert photos[1].taken == date(2024, 3, 15)
    assert os.path.isfile(photos[1].path)


def test_scan_skips_hidden_folders_and_files(tmp_path):
    root = str(tmp_path)
    make_file(root, ".thumbnails/IMG_20240315_101500.jpg")
    make_file(root, ".IMG_20240315_101500.jpg")
    make_file(root, "kept.jpg")
    assert [photo.relpath for photo in scan_photos(root)] == ["kept.jpg"]


def test_undated_keeps_photos_without_a_date(tmp_path):
    root = str(tmp_path)
    make_file(root, "b.jpg")
    make_file(root, "IMG_20240315_101500.jpg")
    make_file(root, "a.png")
    assert [photo.relpath for photo in undated(scan_photos(root))] == ["a.png", "b.jpg"]
