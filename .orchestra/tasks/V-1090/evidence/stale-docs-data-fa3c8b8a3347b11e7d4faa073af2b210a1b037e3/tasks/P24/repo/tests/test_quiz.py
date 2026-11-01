import unittest

from quizgen.bank import Question
from quizgen.quiz import Quiz, answerKey, answerSheet, pickQuestions, renderQuiz


def makeQuestions():
    return {
        "q1": Question("q1", "demo", "One?", ["yes", "no"], "A"),
        "q2": Question("q2", "demo", "Two?", ["yes", "no"], "B", 2),
        "q3": Question("q3", "demo", "Three?", ["red", "green", "blue"], "C", 3),
    }


class QuizTests(unittest.TestCase):
    def test_pick_questions_is_repeatable_with_a_seed(self):
        questions = makeQuestions()
        first = pickQuestions(questions, 2, seed=7)
        second = pickQuestions(questions, 2, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(len({question.qid for question in first}), 2)

    def test_pick_questions_rejects_a_bad_count(self):
        with self.assertRaises(ValueError):
            pickQuestions(makeQuestions(), 4)
        with self.assertRaises(ValueError):
            pickQuestions(makeQuestions(), 0)

    def test_max_score(self):
        quiz = Quiz("Demo", list(makeQuestions().values()))
        self.assertEqual(quiz.maxScore(), 6)

    def test_render_quiz(self):
        quiz = Quiz("Demo", [makeQuestions()["q3"]])
        text = renderQuiz(quiz)
        self.assertIn("1. [q3] Three? (3 points)", text)
        self.assertIn("   C) blue", text)
        self.assertTrue(text.endswith("Maximum score: 3\n"))

    def test_answer_sheet_and_key(self):
        questions = makeQuestions()
        quiz = Quiz("Demo", [questions["q2"], questions["q1"]])
        self.assertEqual(answerSheet(quiz).splitlines()[2:], ["q2:", "q1:"])
        self.assertEqual(answerKey(quiz), [("q2", "B", 2), ("q1", "A", 1)])


if __name__ == "__main__":
    unittest.main()
