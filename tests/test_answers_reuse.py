import unittest

from annalist.answers import reusable

CHAPTERS = list(range(10, 20))


def decision(verdict="unanswered", basis="same", candidates=CHAPTERS):
    entry = {"verdict": verdict, "candidates": candidates}
    return {**entry, "basis": basis} if basis else entry


class ReusableVerdictTest(unittest.TestCase):
    def test_keeps_a_verdict_when_nothing_changed(self):
        self.assertTrue(reusable(decision(), "same", CHAPTERS))

    def test_keeps_a_verdict_when_up_to_two_chapters_swap(self):
        self.assertTrue(reusable(decision(), "same", [*range(10, 18), 30, 31]))

    def test_asks_again_when_three_chapters_swap(self):
        self.assertFalse(reusable(decision(), "same", [*range(10, 17), 30, 31, 32]))

    def test_asks_again_when_the_question_or_its_leads_change(self):
        self.assertFalse(reusable(decision(), "different", CHAPTERS))

    def test_asks_again_after_an_error(self):
        self.assertFalse(reusable(decision(verdict="error"), "same", CHAPTERS))

    def test_asks_again_when_the_old_verdict_saw_no_chapters(self):
        self.assertFalse(reusable({"verdict": "unanswered"}, "same", CHAPTERS))

    def test_a_verdict_from_before_this_rule_is_judged_by_its_chapters(self):
        self.assertTrue(reusable(decision(basis=None), "same", CHAPTERS))
