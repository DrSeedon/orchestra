"""Offline reproduction of the available optional helper, without error-watch stubs."""

from io import StringIO
import logging
import os
from pathlib import Path
import tempfile

from app import private_folder


def main():
    evidence_dir = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(dir=evidence_dir) as temporary:
        cwd = Path(temporary) / "standalone"
        cwd.mkdir()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
            os.environ.pop(name, None)
        os.environ["GIT_CEILING_DIRECTORIES"] = temporary
        os.environ["LC_ALL"] = "C"
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        private_folder.logger.addHandler(handler)
        try:
            result = private_folder.ensure_main_private(cwd)
        finally:
            private_folder.logger.removeHandler(handler)
        assert result is None
        assert list(cwd.iterdir()) == []
        normalized_path_warning = stream.getvalue().strip().replace(str(cwd), "<PATH>")
        assert normalized_path_warning == (
            "WARNING:app.private_folder:Could not prepare shared private folder for <PATH>: "
            "git-common-dir failed in <PATH>: "
            "fatal: not a git repository (or any of the parent directories): .git"
        ), normalized_path_warning
        print("PASS: real optional helper returned None; standalone cwd stayed empty")
        print(normalized_path_warning)


if __name__ == "__main__":
    main()
