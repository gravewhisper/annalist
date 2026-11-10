import json
import tempfile
import unittest
from pathlib import Path

from annalist.state import load_states

ROOT = Path(__file__).resolve().parent

PEOPLE = ("Serrin Vale", "Count Orvell", "Dame Tolly", "Ansel Rook")
THINGS = {"Ashglass Ring": "artifact", "Harbour Guild": "organization"}
WRAPPED = 'Nobody could tell that "Count Orvell" was wearing the ring.'
BARE = "Count Orvell was wearing the ring."
SPEECH = '"Count Orvell is wearing the ring," said Dame Tolly.'


def rel(source, rtype, target, quote, status="stated"):
    return {"source": source, "type": rtype, "target": target, "detail": "", "quotes": [quote], "asserted_by": "narrator", "status": status}


def covers(wearer="Serrin Vale", worn="Count Orvell", status="belief"):
    return rel(wearer, "impersonates", worn, "He is not the man he was.", status)


def uses(quote, source="Count Orvell", target="Ashglass Ring"):
    return rel(source, "uses", target, quote)


class Book:
    def __init__(self, workdir, chapters):
        self.workdir = workdir
        (workdir / "state").mkdir()
        for n, rows in chapters.items():
            state = {"chapter": n, "extraction": {
                "entities": [{"name": p, "type": "character", "aliases": []} for p in PEOPLE]
                            + [{"name": name, "type": kind, "aliases": []} for name, kind in THINGS.items()],
                "relations": [r for r in rows if "source" in r], "facts": [r for r in rows if "entity" in r]}}
            (workdir / "state" / f"{n:04d}.json").write_text(json.dumps(state), encoding="utf-8")

    def rows(self, until=None, **kw):
        return load_states(self.workdir, until=until, **kw).relations


class DisguiseTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def fresh(self, chapters):
        place = self.dir / str(len(list(self.dir.iterdir())))
        place.mkdir()
        return Book(place, chapters)

    def uses_by(self, book, **kw):
        return [(r["chapter"], r["source"]) for r in book.rows(**kw) if r["type"] == "uses"]

    def test_a_name_in_its_own_quote_marks_goes_to_the_impersonator(self):
        self.assertEqual(self.uses_by(self.fresh({4: [covers()], 5: [uses(WRAPPED)]})), [(5, "Serrin Vale")])

    def test_curly_marks_count_the_same(self):
        book = self.fresh({4: [covers()], 5: [uses("Nobody could tell that “Count Orvell” was wearing the ring.")]})
        self.assertEqual(self.uses_by(book), [(5, "Serrin Vale")])

    def test_the_name_on_the_other_end_of_a_relation_moves_too(self):
        book = self.fresh({4: [covers()], 5: [rel("Dame Tolly", "danced with", "Count Orvell", 'She danced with "Count Orvell" all night.')]})
        self.assertEqual([(r["source"], r["target"]) for r in book.rows() if r["type"] == "danced with"], [("Dame Tolly", "Serrin Vale")])

    def test_a_fact_about_the_worn_name_moves(self):
        fact = {"entity": "Count Orvell", "claim": "He wore the ring.", "quotes": [WRAPPED]}
        book = self.fresh({4: [covers()], 5: [fact]})
        self.assertEqual([f["entity"] for f in load_states(book.workdir).facts], ["Serrin Vale"])

    def test_a_fact_with_a_bare_name_stays(self):
        fact = {"entity": "Count Orvell", "claim": "He wore the ring.", "quotes": [BARE]}
        book = self.fresh({4: [covers()], 5: [fact]})
        self.assertEqual([f["entity"] for f in load_states(book.workdir).facts], ["Count Orvell"])

    def test_a_row_in_the_same_chapter_as_the_impersonation_moves(self):
        self.assertEqual(self.uses_by(self.fresh({4: [uses(WRAPPED), covers()]})), [(4, "Serrin Vale")])

    def test_a_row_before_the_impersonation_stays(self):
        self.assertEqual(self.uses_by(self.fresh({3: [uses(WRAPPED)], 4: [covers()]})), [(3, "Count Orvell")])

    def test_a_bare_name_stays(self):
        self.assertEqual(self.uses_by(self.fresh({4: [covers()], 5: [uses(BARE)]})), [(5, "Count Orvell")])

    def test_a_whole_speech_containing_the_name_stays(self):
        for quote in (SPEECH, '"I saw Count Orvell," she said.', '"Count Orvell!" she cried.', "'Is that Count Orvell?' she asked.",
                      "'Count Orvell's carriage waits,' said Dame Tolly."):
            with self.subTest(quote):
                self.assertEqual(self.uses_by(self.fresh({4: [covers()], 5: [uses(quote)]})), [(5, "Count Orvell")])

    def test_nothing_shows_before_its_own_chapter_or_the_impersonation(self):
        book = self.fresh({4: [covers()], 5: [uses(WRAPPED)]})
        self.assertEqual(self.uses_by(book, until=4), [])
        self.assertEqual(book.rows(until=3), [])
        self.assertEqual(self.uses_by(book, until=5), [(5, "Serrin Vale")])

    def test_an_unmerged_load_keeps_the_rows_as_filed(self):
        self.assertEqual(self.uses_by(self.fresh({4: [covers()], 5: [uses(WRAPPED)]}), merges=False), [(5, "Count Orvell")])

    def test_only_the_verb_itself_establishes_an_impersonation(self):
        for wording in ("suspected of impersonating Count Orvell", "impersonated by", "disguised as a clown to meet"):
            with self.subTest(wording):
                row = rel("Dame Tolly", wording, "Count Orvell", "She wondered.")
                self.assertEqual(self.uses_by(self.fresh({4: [row], 5: [uses(WRAPPED)]})), [(5, "Count Orvell")])

    def test_other_wordings_establish_it(self):
        for wording in ("disguised as", "posing as", "pretends to be", "masquerades as"):
            with self.subTest(wording):
                row = rel("Serrin Vale", wording, "Count Orvell", "He wore the face.")
                self.assertEqual(self.uses_by(self.fresh({4: [row], 5: [uses(WRAPPED)]})), [(5, "Serrin Vale")])

    def test_a_quoted_organization_is_not_a_person_worn(self):
        guild = "The sign read 'Harbour Guild' in faded paint."
        book = self.fresh({4: [rel("Serrin Vale", "posing as", "Harbour Guild", "He wore their coat.")],
                           5: [rel("Harbour Guild", "hired", "Dame Tolly", guild)]})
        self.assertEqual([(r["source"], r["target"]) for r in book.rows() if r["type"] == "hired"], [("Harbour Guild", "Dame Tolly")])

    def test_a_row_between_the_two_people_does_not_become_a_self_loop(self):
        book = self.fresh({4: [covers()], 5: [rel("Count Orvell", "struck", "Serrin Vale", '"Count Orvell" struck him.')]})
        self.assertEqual([(r["source"], r["target"]) for r in book.rows() if r["type"] == "struck"], [("Count Orvell", "Serrin Vale")])

    def test_an_impersonation_in_a_vision_leaves_the_main_story_alone(self):
        place = self.dir / "vision"
        (place / "state").mkdir(parents=True)
        vision = {"chapter": 4, "timelines": {"new": [{"id": "v1", "kind": "vision"}], "labels": {"R1": "v1"}},
                  "extraction": {"entities": [{"name": p, "type": "character", "aliases": []} for p in PEOPLE], "relations": [covers()]}}
        later = {"chapter": 5, "extraction": {"entities": [{"name": "Ashglass Ring", "type": "artifact", "aliases": []}], "relations": [uses(WRAPPED)]}}
        for state in (vision, later):
            (place / "state" / f"{state['chapter']:04d}.json").write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual([r["source"] for r in load_states(place).relations if r["type"] == "uses"], ["Count Orvell"])

    def test_the_latest_impersonator_wears_the_name(self):
        book = self.fresh({2: [covers("Ansel Rook")], 4: [covers()], 5: [uses(WRAPPED)]})
        self.assertEqual(self.uses_by(book), [(5, "Serrin Vale")])

    def test_two_impersonators_at_once_leave_the_row_alone(self):
        book = self.fresh({4: [covers("Ansel Rook"), covers()], 5: [uses(WRAPPED)]})
        self.assertEqual(self.uses_by(book), [(5, "Count Orvell")])


if __name__ == "__main__":
    unittest.main()
