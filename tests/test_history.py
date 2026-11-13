import unittest

from annalist.export import entity_id
from annalist.pages import PageName
from annalist.render import history_prompts
from tests.test_asof_leaks import visible_text
from tests.test_build import build_script, MiniBuild, ran, site_views


FIRST = "Kept the harbour lamp through the storm (ch 2)."
SECOND = "Went down to the wreck on the shingle (ch 4)."


def prose(paragraph):
    return paragraph.split(" (ch")[0]


def history_script(starts=(1, 4)):
    script = build_script()
    for r in script["replies"]:
        if r["purpose"] == "arcs":
            r["reply"] = {"arcs": [{"name": "Whatever Comes Later", "start": s} for s in starts]}
    script["replies"][:0] = [{"purpose": "arc", "contains": "Arc: chapters 1 to 3", "reply": {"name": "The Missing Page", "summary": "Ines looks."}},
                             {"purpose": "arc", "contains": "Arc: chapters 4 to 5", "reply": {"name": "The Wreck", "summary": "Bram dives."}},
                             {"purpose": "history", "contains": 'story arc "The Missing Page"', "reply": {"paragraph": FIRST}},
                             {"purpose": "history", "contains": 'story arc "The Wreck"', "reply": {"paragraph": SECOND}}]
    return script


class HistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(history_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def history(self, name):
        return next(e.get("history", []) for e in self.wiki["entities"] if e["name"] == name)

    def site(self, name, n):
        view = f"{entity_id(name)}@{n}"
        return visible_text(site_views(self.book.workdir / "site" / "data" / "wiki.json", view)[view])

    def markdown(self, name, n=None):
        if n is not None:
            self.book.run_annalist("render", str(self.book.workdir), "--until", str(n))
        wiki = self.book.workdir / ("wiki" if n is None else f"wiki-ch{n:04d}")
        return next(wiki.rglob(name.lower().replace(" ", "-") + ".md")).read_text(encoding="utf-8")

    def test_each_arc_with_enough_of_a_characters_facts_gets_a_history_paragraph_shown_from_the_arcs_end(self):
        self.assertEqual(self.history("Tomas Hale"), [{"arc": "The Missing Page", "start": 1, "end": 3, "shown": 3, "text": FIRST}])
        self.assertEqual(self.history("Bram Ostrow"), [{"arc": "The Wreck", "start": 4, "end": 5, "shown": 5, "text": SECOND}])
        self.assertEqual(self.history("Captain Fenn"), [])

    def test_the_site_shows_an_arcs_history_only_once_the_slider_reaches_the_arcs_end(self):
        self.assertNotIn("History", self.site("Tomas Hale", 2))
        self.assertIn("History Ch 1 to 3 The Missing Page " + prose(FIRST), self.site("Tomas Hale", 3))
        self.assertIn(prose(FIRST), self.site("Tomas Hale", 5))
        self.assertNotIn("History", self.site("Bram Ostrow", 4))
        self.assertIn("History Ch 4 to 5 The Wreck " + prose(SECOND), self.site("Bram Ostrow", 5))

    def test_the_markdown_wiki_shows_an_arcs_history_only_once_rendered_past_the_arcs_end(self):
        self.assertNotIn("## History", self.markdown("Tomas Hale", 2))
        page = self.markdown("Tomas Hale", 3)
        self.assertIn("## History\n\n### The Missing Page\n\n*Chapters 1 to 3.*\n\n", page)
        self.assertIn(FIRST.replace("(ch 2)", "([ch 2](../../chapters/0002.txt))"), page)
        self.assertNotIn("## History", self.markdown("Bram Ostrow", 4))
        self.assertIn("### The Wreck", self.markdown("Bram Ostrow"))


class PartlyReadVolumeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(history_script())
        cls.book.build("--to", "4")
        cls.partial = cls.book.json("site/data/wiki.json")
        cls.again = cls.book.build("--to", "4")
        cls.book.script(history_script(starts=(1, 2)))
        cls.book.build()
        cls.whole = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def history(self, wiki, name):
        return next(e.get("history", []) for e in wiki["entities"] if e["name"] == name)

    def test_a_volume_read_partway_gets_history_for_its_closed_arcs_and_none_for_the_open_one(self):
        self.assertEqual(self.history(self.partial, "Tomas Hale"), [{"arc": "The Missing Page", "start": 1, "end": 3, "shown": 3, "text": FIRST}])
        self.assertEqual(self.history(self.partial, "Bram Ostrow"), [])
        self.assertEqual(self.partial["volumes"], [])
        view = f"{entity_id('Tomas Hale')}@4"
        page = visible_text(site_views(self.book.workdir / "site" / "data" / "wiki.json", view)[view])
        self.assertIn("History Ch 1 to 3 The Missing Page " + prose(FIRST), page)

    def test_rebuilding_with_the_same_chapters_read_divides_nothing_again(self):
        self.assertEqual(ran(self.again.stdout), [])

    def test_reading_more_chapters_keeps_a_closed_arc_and_divides_only_the_chapters_after_it(self):
        self.assertEqual(self.history(self.whole, "Tomas Hale"), self.history(self.partial, "Tomas Hale"))
        self.assertEqual([(a["name"], a["start"], a["end"]) for a in self.whole["volumes"][0]["arcs"]],
                         [("The Missing Page", 1, 3), ("The Wreck", 4, 5)])
        self.assertEqual(len(self.book.calls("arcs")), 2)


def fact(n, chapter, claim, **extra):
    return {"id": f"F{n}", "chapter": chapter, "status": "stated", "asserted_by": "narrator", "claim": claim,
            "quotes": [claim], "quote_ok": True, **extra}


class HistoryPromptTest(unittest.TestCase):
    def test_an_arc_prompt_holds_only_the_arcs_facts_and_ties_and_no_name_absorbed_later(self):
        entity = {"name": "Ada Quill", "type": "character", "aliases": ["the Lamp Thief"],
                  "absorbed": [{"name": "the Lamp Thief", "chapter": 3, "aliases": []}]}
        facts = [fact(k, 1, f"Ada mended net {k}.") for k in range(5)] + [fact(9, 2, "The Lamp Thief stole oil.", filed="the Lamp Thief")]
        facts += [fact(10 + k, 4, f"Ada sailed north {k}.") for k in range(4)]
        relations = [{"chapter": 2, "source": "Ada Quill", "target": "Hob Wick", "type": "sister of", "detail": "", "quotes": ["x"], "quote_ok": True},
                     {"chapter": 2, "source": "Ada Quill", "target": "Ned Rook", "type": "robbed", "detail": "", "quotes": ["y"], "quote_ok": True,
                      "filed": {"source": "the Lamp Thief"}},
                     {"chapter": 4, "source": "Ada Quill", "target": "Ned Rook", "type": "married", "detail": "", "quotes": ["z"], "quote_ok": True}]
        arcs = [{"name": "Nets", "start": 1, "end": 2}, {"name": "North", "start": 3, "end": 4}]
        prompts = history_prompts(entity, facts, relations, arcs, {}, PageName("Ada Quill", "Ada Quill", 1, 1, []))
        self.assertEqual([arc["name"] for arc, _ in prompts], ["Nets"])
        prompt = prompts[0][1]
        self.assertIn("Ada mended net 4.", prompt)
        self.assertIn("Ada Quill sister of Hob Wick", prompt)
        self.assertEqual([w for w in ("north", "Lamp Thief", "robbed", "married") if w in prompt], [])

    def test_an_arc_prompt_asks_to_keep_a_past_and_a_feeling_the_arc_reveals(self):
        entity = {"name": "Ada Quill", "type": "character", "aliases": []}
        facts = [fact(k, 1, f"Ada mended net {k}.") for k in range(4)]
        facts += [fact(7, 2, "Ada lost her brothers to the sea at twelve and took up their boat."),
                  fact(8, 2, "Ada never told the lighthouse keeper that she loved him.")]
        [(_, prompt)] = history_prompts(entity, facts, [], [{"name": "Nets", "start": 1, "end": 2}], {},
                                        PageName("Ada Quill", "Ada Quill", 1, 1, []))
        self.assertIn("lost her brothers to the sea at twelve", prompt)
        self.assertIn("never told the lighthouse keeper that she loved him", prompt)
        self.assertIn("Keep each fact or relation that tells the character's past before these chapters", prompt)
        self.assertIn("and each feeling or love for someone that one states", prompt)
        self.assertIn("in the words of the facts", prompt)


if __name__ == "__main__":
    unittest.main()
