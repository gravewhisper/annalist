import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from annalist.corrections import apply_to_wiki, load_corrections, reader_notes
from annalist.state import Knowledge
from tests.test_asof_leaks import visible_text
from tests.test_build import MiniBuild, build_script, site_views

REVEAL = "My name was Livia Hale."


def two_pages():
    return {
        "entities": [
            {"id": "n", "name": "Mira Vale", "name_chapter": 1, "type": "character", "first": 1, "aliases": [], "present": [1, 5],
             "profile": {"fields": {"age": [{"chapter": 1, "value": "thirty", "quotes": ["q"]}]}, "lists": {}, "spoke": [[1, "main"]], "personality": []}},
            {"id": "d", "name": "Grey Stranger", "name_chapter": 2, "type": "character", "first": 2, "aliases": [{"name": "the stranger", "chapter": 3}],
             "present": [2, 3, 6], "blurbs": [[2, "A man in grey."], [6, "Seen again."]],
             "profile": {"fields": {"hair": [{"chapter": 2, "value": "grey", "quotes": ["q"]}]}, "lists": {}, "spoke": [[2, "main"], [6, "main"]], "personality": []}},
            {"id": "h", "name": "Hood", "name_chapter": 1, "type": "character", "first": 1, "aliases": [], "merged": {"into": "d", "chapter": 3}},
        ],
        "facts": [{"id": "f1", "chapter": 2, "entity": "d"}, {"id": "f2", "chapter": 6, "entity": "d"}],
        "relations": [{"chapter": 2, "source": "d", "target": "n", "type": "watches"}, {"chapter": 6, "source": "d", "target": "n", "type": "watches"}],
    }


def same(chapter=4, name="Grey Stranger", same_as="Mira Vale"):
    return {"name": name, "same_as": same_as, "chapter": chapter, "quotes": ["q"]}


def by_id(corrected):
    return {e["id"]: e for e in corrected["entities"]}


class JoinOnTheSite(unittest.TestCase):
    def test_the_description_page_becomes_part_of_the_named_page_from_the_chapter(self):
        corrected, missing = apply_to_wiki(two_pages(), [same()])
        pages = by_id(corrected)
        self.assertEqual(missing, [])
        self.assertEqual(pages["d"]["merged"], {"into": "n", "chapter": 4})
        self.assertEqual(pages["n"]["aliases"], [{"name": "Grey Stranger", "chapter": 4}, {"name": "the stranger", "chapter": 4}])

    def test_rows_from_the_chapter_on_move_to_the_named_page_and_earlier_ones_wait_for_it(self):
        corrected, _ = apply_to_wiki(two_pages(), [same()])
        pages = by_id(corrected)
        self.assertEqual([(f["id"], f["entity"]) for f in corrected["facts"]], [("f1", "d"), ("f2", "n")])
        self.assertEqual([(r["chapter"], r["source"], r["target"]) for r in corrected["relations"]], [(2, "d", "n")])
        self.assertEqual(pages["n"]["profile"]["fields"]["hair"], [{"chapter": 2, "value": "grey", "quotes": ["q"], "shown": 4}])
        self.assertEqual(pages["d"]["profile"]["fields"]["hair"][0]["chapter"], 2)
        self.assertEqual((pages["d"]["present"], pages["n"]["present"]), ([2, 3], [1, 5, 6]))
        self.assertEqual((pages["d"]["blurbs"], pages["n"]["blurbs"]), ([[2, "A man in grey."]], [[6, "Seen again."]]))
        self.assertEqual(pages["n"]["profile"]["spoke"], [[1, "main"], [6, "main"]])

    def test_a_page_already_merged_into_the_description_joins_no_earlier_than_the_correction(self):
        corrected, _ = apply_to_wiki(two_pages(), [same()])
        self.assertEqual(by_id(corrected)["h"]["merged"], {"into": "n", "chapter": 4})

    def test_a_chapter_before_either_page_appears_is_skipped_with_a_warning(self):
        out = io.StringIO()
        with redirect_stdout(out):
            corrected, missing = apply_to_wiki(two_pages(), [same(chapter=1)])
        self.assertNotIn("merged", by_id(corrected)["d"])
        self.assertIn("before one of them first appears", out.getvalue())

    def test_an_unknown_name_on_either_side_is_reported(self):
        for fix, name in ((same(name="Nobody"), "Nobody"), (same(same_as="Nobody"), "Nobody")):
            corrected, missing = apply_to_wiki(two_pages(), [fix])
            self.assertEqual(missing, [name])
            self.assertEqual(corrected, two_pages())

    def test_two_names_of_one_page_are_left_alone(self):
        with redirect_stdout(io.StringIO()):
            corrected, _ = apply_to_wiki(two_pages(), [same(name="the stranger", same_as="Grey Stranger")])
        self.assertEqual(corrected, two_pages())


class LoadSamePerson(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.workdir = Path(folder.name)
        (self.workdir / "chapters").mkdir()
        (self.workdir / "chapters" / "0004.txt").write_text("He pushed his spectacles up and said nothing.", encoding="utf-8")

    def load(self, entry):
        (self.workdir / "corrections.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            return load_corrections(self.workdir)[0], out.getvalue()

    def test_keeps_a_link_whose_quote_is_in_its_chapter(self):
        entry, said = self.load({"name": "Bespectacled man", "same_as": "Arlen", "chapter": 4, "quotes": ["He pushed his spectacles up"]})
        self.assertEqual((entry["same_as"], said), ("Arlen", ""))

    def test_drops_a_link_whose_quote_is_not_in_its_chapter(self):
        entry, said = self.load({"name": "Bespectacled man", "same_as": "Arlen", "chapter": 4, "quotes": ["He took off his hat."]})
        self.assertNotIn("same_as", entry)
        self.assertIn("Bespectacled man.same_as ch4", said)

    def test_drops_a_link_with_no_quote(self):
        entry, _ = self.load({"name": "Bespectacled man", "same_as": "Arlen", "chapter": 4})
        self.assertNotIn("same_as", entry)

    def test_refuses_a_link_with_no_chapter(self):
        with self.assertRaises(SystemExit):
            self.load({"name": "Bespectacled man", "same_as": "Arlen", "quotes": ["He pushed his spectacles up"]})


class ReaderNote(unittest.TestCase):
    def test_the_reader_learns_the_link_only_in_chapters_after_it(self):
        kb = Knowledge(None, {}, ())
        kb.upsert_entity({"name": "Grey Stranger", "type": "character", "summary": "A man in grey."}, 2)
        notes = {n: reader_notes(kb, [same()], n) for n in (4, 5)}
        self.assertEqual(notes[4], {})
        self.assertEqual(notes[5], {"Grey Stranger": "same as Mira Vale from chapter 4"})


def unlinked_script():
    script = build_script()
    for r in script["replies"]:
        if r["purpose"] == "extract" and r["chapter"] == 4:
            for e in r["reply"]["entities"]:
                if e["name"] == "Livia Hale":
                    e["aliases"] = []
    script["replies"][:0] = [
        {"purpose": "profile", "contains": 'about the character "Livia Hale"',
         "reply": {"age": [{"value": "twelve", "chapter": 2, "quotes": ["Livia Hale was twelve that winter."], "asserted_by": "narrator"}]}},
        {"purpose": "profile", "contains": 'about the character "Sister Wren"',
         "reply": {"appearance": [{"value": "white scar across the back of her left hand", "chapter": 3,
                                   "quotes": ["small and quick, with a white scar across the back of her left hand."], "asserted_by": "narrator"}]}},
    ]
    return script


CORRECTIONS = {"entries": [
    {"name": "Sister Wren", "same_as": "Livia Hale", "chapter": 4, "quotes": [REVEAL]},
    {"name": "Captain Fenn", "same_as": "Odile Marr", "chapter": 5, "quotes": ["A line the book never has."]},
    {"name": "The Bespectacled Stranger", "same_as": "Ines Varro", "chapter": 3, "quotes": ["The sisters called her Sister Wren."]},
]}


class SamePersonBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(unlinked_script())
        cls.book.build()
        before = cls.book.json("site/data/wiki.json")
        cls.unlinked = {e["name"]: e.get("merged") for e in before["entities"] if e["name"] in ("Sister Wren", "Livia Hale")}
        cls.calls = len(cls.book.calls())
        (cls.book.workdir / "corrections.json").write_text(json.dumps(CORRECTIONS), encoding="utf-8")
        cls.rebuild = cls.book.build()
        cls.new_calls = cls.book.calls()[cls.calls:]
        cls.export = cls.book.run_annalist("export", str(cls.book.workdir), str(cls.book.workdir / "site"))
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, name, n):
        view = f"{self.id[name]}@{n}"
        return visible_text(site_views(self.book.workdir / "site" / "data" / "wiki.json", view)[view])

    def markdown(self, n):
        self.book.run_annalist("render", str(self.book.workdir), "--until", str(n))
        folder = self.book.workdir / f"wiki-ch{n:04d}" / "character"
        return {p.stem: p.read_text(encoding="utf-8") for p in folder.glob("*.md")}

    def test_without_the_correction_the_pipeline_keeps_two_pages(self):
        self.assertEqual(self.unlinked, {"Sister Wren": None, "Livia Hale": None})

    def test_the_rebuild_reruns_render_and_export_with_no_model_call(self):
        self.assertEqual(re.findall(r"^== (\w+)$", self.rebuild.stdout, re.M), ["render", "export"])
        self.assertEqual(self.new_calls, [])

    def test_the_site_joins_the_pages_from_the_chapter_of_the_clue(self):
        merged = next(e for e in self.wiki["entities"] if e["name"] == "Sister Wren")["merged"]
        self.assertEqual(merged, {"into": self.id["Livia Hale"], "chapter": 4})
        livia = {n: self.site("Livia Hale", n).lower() for n in (3, 4)}
        self.assertNotIn("wren", livia[3])
        self.assertNotIn("white scar", livia[3])
        self.assertIn("also known as sister wren", livia[4])
        self.assertIn("white scar", livia[4])
        self.assertIn("twelve", livia[4])
        self.assertIn("white scar", self.site("Sister Wren", 3))
        self.assertNotIn("Livia", self.site("Sister Wren", 3))

    def test_no_graph_view_ties_the_two_before_the_chapter(self):
        wren, livia = self.id["Sister Wren"], self.id["Livia Hale"]
        people = [e["id"] for e in self.wiki["entities"] if e["type"] == "character"]
        views = ["graph:all@3", "graph:matrix@3", *(f"graph:{p}@3" for p in people),
                 *(f"graph:path:{a}~{b}@3" for a in (wren, livia) for b in self.id.values() if a != b)]
        out = site_views(self.book.workdir / "site" / "data" / "wiki.json", *views)
        tied = {v for v, g in out.items() if any({l["a"], l["b"]} == {wren, livia} for l in g["model"]["links"])}
        said = {v for v, g in out.items() if re.search(r"Same person|Also known as Sister Wren|to be Livia Hale", visible_text(g["html"]))}
        self.assertEqual(tied | said, set())

    def test_the_markdown_wiki_keeps_two_pages_before_the_chapter_and_one_from_it(self):
        before, after = self.markdown(3), self.markdown(4)
        self.assertIn("sister-wren", before)
        self.assertNotIn("Wren", before["livia-hale"])
        self.assertNotIn("sister-wren", after)
        self.assertIn("Also known as: Sister Wren", after["livia-hale"])
        self.assertIn("The archivist was a young woman", after["livia-hale"])
        self.assertIn("white scar", after["livia-hale"].lower())

    def test_a_bad_quote_or_an_unknown_name_is_skipped_with_a_warning(self):
        self.assertIn("Captain Fenn.same_as ch5 has no quote found in that chapter", self.export.stdout)
        self.assertIn("'The Bespectacled Stranger', which matches no entry", self.export.stdout)
        self.assertNotIn("merged", next(e for e in self.wiki["entities"] if e["name"] == "Captain Fenn"))


if __name__ == "__main__":
    unittest.main()
