import json
import re
import unittest

from tests.test_asof_leaks import visible_text
from tests.test_build import MiniBuild, build_script, site_views

REVEAL = "My name was Livia Hale."
REWRITTEN = "REWRITTEN"
PROSE = ("summary", "history", "personality")


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


def only_about(script, names):
    replies = [r for r in script["replies"] if r["purpose"] not in PROSE or "contains" in r]
    replies += [{"purpose": "summary", "contains": f'page about "{n}"', "reply": {"summary": f"{REWRITTEN} {n}."}} for n in names]
    replies += [{"purpose": "personality", "contains": f'page about "{n}"', "reply": {"paragraph": f"{REWRITTEN} {n} (ch 5)."}} for n in names]
    replies += [{"purpose": "history", "contains": f'History of "{n}"', "reply": {"paragraph": f"{REWRITTEN} {n} (ch 5)."}} for n in names]
    return {"replies": replies}


CORRECTIONS = {"entries": [
    {"name": "Sister Wren", "same_as": "Livia Hale", "chapter": 4, "quotes": [REVEAL]},
    {"name": "Bram Ostrow", "same_as": "Odile Marr", "chapter": 5, "quotes": ["It was Bram who broke."]},
    {"name": "Captain Fenn", "same_as": "Odile Marr", "chapter": 5, "quotes": ["A line the book never has."]},
    {"name": "The Bespectacled Stranger", "same_as": "Ines Varro", "chapter": 3, "quotes": ["The sisters called her Sister Wren."]},
]}
JOINED = {"Sister Wren": ("Livia Hale", 4), "Bram Ostrow": ("Odile Marr", 5)}


def prose(wiki, n):
    shown = {}
    for e in wiki["entities"]:
        main = e.get("summary") if e.get("summary") and e["summary"]["chapter"] <= n else None
        shown[e["name"]] = ((main or {}).get("text"), [s["text"] for s in e.get("summaries", []) if s["chapter"] <= n],
                            [h["text"] for h in e.get("history", []) if h["shown"] <= n],
                            [p["text"] for p in (e.get("profile") or {}).get("personality", []) if p["chapter"] <= n])
    return shown


class SamePersonBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = unlinked_script()
        cls.book = MiniBuild(script)
        cls.book.build()
        cls.before = cls.book.json("site/data/wiki.json")
        cls.unlinked = {e["name"]: e.get("merged") for e in cls.before["entities"] if e["name"] in ("Sister Wren", "Livia Hale")}
        cls.calls = len(cls.book.calls())
        (cls.book.workdir / "corrections.json").write_text(json.dumps(CORRECTIONS), encoding="utf-8")
        cls.book.script(only_about(script, {page for page, _ in JOINED.values()}))
        cls.rebuild = cls.book.build(check=False)
        cls.new_calls = cls.book.calls()[cls.calls:]
        cls.book.script(script)
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

    def test_the_rebuild_asks_the_model_only_about_the_pages_a_correction_joined_into(self):
        self.assertEqual(self.rebuild.returncode, 0, self.rebuild.stderr[-2000:])
        self.assertEqual(re.findall(r"^== (\w+)$", self.rebuild.stdout, re.M), ["render", "export"])
        self.assertEqual({c["purpose"] for c in self.new_calls}, {"summary", "history"})

    def test_a_joined_page_reads_the_new_text_from_the_chapter_of_the_clue_and_the_old_text_before_it(self):
        for part, (page, chapter) in JOINED.items():
            with self.subTest(page=page):
                self.assertEqual(prose(self.wiki, chapter - 1)[page], prose(self.before, chapter - 1)[page])
                self.assertNotIn(REWRITTEN, json.dumps(prose(self.wiki, chapter - 1)[page]))
                self.assertIn(REWRITTEN, json.dumps(prose(self.wiki, 5)[page]))

    def test_before_a_correction_s_chapter_no_page_s_text_reflects_it(self):
        for n in range(1, 4):
            self.assertEqual(prose(self.wiki, n), {k: v for k, v in prose(self.before, n).items()}, f"chapter {n}")
        changed = {name for name, text in prose(self.wiki, 4).items() if text != prose(self.before, 4).get(name)}
        self.assertEqual(changed, {"Livia Hale"})

    def test_a_description_page_keeps_its_own_summaries_from_before_the_chapter(self):
        bram = next(e for e in self.wiki["entities"] if e["name"] == "Bram Ostrow")
        old = next(e for e in self.before["entities"] if e["name"] == "Bram Ostrow")
        self.assertEqual(bram["merged"]["chapter"], 5)
        self.assertEqual([s for s in bram["summaries"] if s["chapter"] < 5], [s for s in old["summaries"] if s["chapter"] < 5])
        self.assertTrue([s for s in bram["summaries"] if s["chapter"] < 5])

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
        self.assertIn("warning: correction Captain Fenn.same_as ch5 has no quote found in that chapter, skipped", self.export.stdout)
        self.assertIn("warning: corrections.json names 'The Bespectacled Stranger', which matches no entry, skipped", self.export.stdout)
        self.assertNotIn("merged", next(e for e in self.wiki["entities"] if e["name"] == "Captain Fenn"))


if __name__ == "__main__":
    unittest.main()
