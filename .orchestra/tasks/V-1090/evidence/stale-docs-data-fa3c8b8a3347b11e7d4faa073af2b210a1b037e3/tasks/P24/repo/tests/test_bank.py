import tempfile
import unittest
from pathlib import Path

from quizgen.bank import Question, letterIndex, loadBank, loadBanks

GEO = """\
[geo-1]
question = What is the capital of France?
choices = Berlin; Paris; Rome
answer = b

[geo-2]
question = Which river is the longest?
choices = Nile; Amazon; Danube
answer = A
points = 2
"""


class BankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def writeBank(self, name, text):
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_load_bank_reads_every_section(self):
        questions = loadBank(self.writeBank("geo.ini", GEO))
        self.assertEqual([question.qid for question in questions], ["geo-1", "geo-2"])
        first = questions[0]
        self.assertEqual(first.bank, "geo")
        self.assertEqual(first.choices, ["Berlin", "Paris", "Rome"])
        self.assertEqual(first.answer, "B")
        self.assertEqual(first.points, 1)
        self.assertEqual(first.correctChoice(), "Paris")
        self.assertEqual(questions[1].points, 2)

    def test_load_bank_rejects_an_answer_outside_the_choices(self):
        path = self.writeBank("bad.ini", "[q1]\nquestion = Pick\nchoices = yes; no\nanswer = C\n")
        with self.assertRaises(ValueError):
            loadBank(path)

    def test_load_bank_rejects_a_single_choice(self):
        path = self.writeBank("bad.ini", "[q1]\nquestion = Pick\nchoices = yes\nanswer = A\n")
        with self.assertRaises(ValueError):
            loadBank(path)

    def test_load_banks_reads_only_ini_files(self):
        self.writeBank("geo.ini", GEO)
        self.writeBank("notes.txt", "not a bank")
        questions = loadBanks(self.folder)
        self.assertEqual(sorted(questions), ["geo-1", "geo-2"])
        self.assertIsInstance(questions["geo-1"], Question)

    def test_load_banks_rejects_a_repeated_id(self):
        self.writeBank("a.ini", GEO)
        self.writeBank("b.ini", GEO)
        with self.assertRaises(ValueError):
            loadBanks(self.folder)

    def test_load_banks_needs_the_folder(self):
        with self.assertRaises(FileNotFoundError):
            loadBanks(self.folder / "missing")

    def test_letter_index(self):
        self.assertEqual(letterIndex("a"), 0)
        self.assertEqual(letterIndex(" C "), 2)


if __name__ == "__main__":
    unittest.main()
