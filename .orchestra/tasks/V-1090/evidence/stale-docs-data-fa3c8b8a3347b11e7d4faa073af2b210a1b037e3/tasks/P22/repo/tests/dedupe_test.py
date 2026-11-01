import hashlib
import os

from photosort.dedupe import file_digest, find_duplicates
from photosort.scan import scan_photos


def make_file(root, relpath, content):
    path = os.path.join(root, *relpath.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def test_file_digest_is_sha1_of_the_content(tmp_path):
    path = make_file(str(tmp_path), "a.jpg", b"photo bytes")
    assert file_digest(path) == hashlib.sha1(b"photo bytes").hexdigest()


def test_find_duplicates_groups_identical_files(tmp_path):
    root = str(tmp_path)
    make_file(root, "b/copy.jpg", b"same")
    make_file(root, "a.jpg", b"same")
    make_file(root, "c.jpg", b"diff")
    make_file(root, "d.jpg", b"other content")
    groups = find_duplicates(scan_photos(root))
    assert len(groups) == 1
    assert groups[0].relpaths == ["a.jpg", "b/copy.jpg"]
    assert groups[0].digest == hashlib.sha1(b"same").hexdigest()


def test_find_duplicates_without_copies(tmp_path):
    root = str(tmp_path)
    make_file(root, "a.jpg", b"one")
    make_file(root, "b.jpg", b"two")
    assert find_duplicates(scan_photos(root)) == []
