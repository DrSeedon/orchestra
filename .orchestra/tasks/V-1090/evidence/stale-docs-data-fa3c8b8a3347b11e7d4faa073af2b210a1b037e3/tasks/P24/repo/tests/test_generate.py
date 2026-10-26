import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from quizgen.generate import main

BANK = """\
[q1]
question = One?
choices = yes; no
answer = A

[q2]
question = Two?
choices = yes; no
answer = B
points = 2
"""


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.banks = self.folder / "banks"
        self.banks.mkdir()
        (self.banks / "demo.ini").write_text(BANK, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def runMain(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main([str(arg) for arg in args])
        return status, err.getvalue()

    def test_generate_writes_quiz_sheet_and_key(self):
        output = self.folder / "out" / "week1"
        status, _ = self.runMain(self.banks, 2, output, "--seed", 1, "--title", "Week 1")
        self.assertEqual(status, 0)
        self.assertTrue((output / "quiz.txt").read_text(encoding="utf-8").startswith("Week 1\n"))
        sheet = (output / "sheet.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(sheet[2:]), ["q1:", "q2:"])
        key = (output / "key.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(key[0], "question,answer,points")
        self.assertEqual(sorted(key[1:]), ["q1,A,1", "q2,B,2"])

    def test_generate_rejects_too_many_questions(self):
        output = self.folder / "out"
        status, err = self.runMain(self.banks, 3, output)
        self.assertEqual(status, 2)
        self.assertIn("error", err)
        self.assertFalse(output.exists())

    def test_generate_rejects_a_missing_banks_folder(self):
        status, _ = self.runMain(self.folder / "nothing", 1, self.folder / "out")
        self.assertEqual(status, 2)


if __name__ == "__main__":
    unittest.main()
