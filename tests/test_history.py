import unittest

from annalist.export import entity_id
from annalist.render import history_prompts
from tests.test_asof_leaks import TWO_ARCS, visible_text
from tests.test_build import build_script, MiniBuild, site_views


FIRST = "Kept the harbour lamp through the storm (ch 2)."
SECOND = "Went down to the wreck on the shingle (ch 4)."


def prose(paragraph):
    return paragraph.split(" (ch")[0]


def history_script():
    script = build_script()
    for r in script["replies"]:
        if r["purpose"] == "arcs":
            r["reply"] = TWO_ARCS
    script["replies"][:0] = [{"purpose": "history", "contains": 'story arc "The Missing Page"', "reply": {"paragraph": FIRST}},
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
        prompts = history_prompts(entity, facts, relations, arcs, {})
        self.assertEqual([arc["name"] for arc, _ in prompts], ["Nets"])
        prompt = prompts[0][1]
        self.assertIn("Ada mended net 4.", prompt)
        self.assertIn("Ada Quill sister of Hob Wick", prompt)
        self.assertEqual([w for w in ("north", "Lamp Thief", "robbed", "married") if w in prompt], [])


if __name__ == "__main__":
    unittest.main()
