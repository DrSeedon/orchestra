from datetime import date

from photosort.naming import date_from_name, is_photo


def test_is_photo_checks_the_extension_in_any_case():
    assert is_photo("IMG_0001.JPG")
    assert is_photo("scan.tiff")
    assert is_photo("2024-01-05 08.00.00.heic")
    assert not is_photo("notes.txt")
    assert not is_photo("movie.mp4")


def test_date_from_camera_names():
    assert date_from_name("IMG_20240315_101500.jpg") == date(2024, 3, 15)
    assert date_from_name("PXL_20231231_235959123.jpg") == date(2023, 12, 31)
    assert date_from_name("VID-20240101-120000.png") == date(2024, 1, 1)


def test_date_from_exported_names():
    assert date_from_name("2024-01-05 08.00.00.png") == date(2024, 1, 5)
    assert date_from_name("Screenshot 2024-02-29 at 10.11.12.png") == date(2024, 2, 29)


def test_names_without_a_valid_date():
    assert date_from_name("scan.jpg") is None
    assert date_from_name("IMG_20231399_101500.jpg") is None
    assert date_from_name("2023-02-29.jpg") is None
    assert date_from_name("12024-01-05.jpg") is None
