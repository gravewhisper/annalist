import json
import re
import shutil
import unittest

from tests.test_build import MiniBuild, build_script, site_views
from tests.test_pipeline import support_reply

NODE = shutil.which("node")
KESTREL_SENTENCE = ("The ship was the Kestrel out of the north, and her master came ashore herself, "
                    "a broad woman in a blue coat with a silver ring in one ear.")
QUAY_SENTENCE = "The harbour lamp of Corvel Quay had burned every night for two hundred years, except one."


def bare_script():
    script = build_script()
    extract = next(r for r in script["replies"] if r["purpose"] == "extract" and r["chapter"] == 1)
    extraction = extract["reply"]
    extraction["relations"] = [r for r in extraction["relations"] if not {"Kestrel", "Corvel Quay"} & {r["source"], r["target"]}]
    support = next(r for r in script["replies"] if r["purpose"] == "support" and r["chapter"] == 1)
    support["reply"] = support_reply(extraction, 1)
    return script


@unittest.skipIf(NODE is None, "node is not installed")
class MinorMentionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(bare_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, *views):
        return site_views(self.book.workdir / "site" / "data" / "wiki.json", *views)

    def text(self, html):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

    def minor_section(self, html):
        head, _, tail = html.partition("Minor mentions")
        return head, tail

    def test_every_entry_carries_the_chapter_and_sentence_of_its_first_mention(self):
        kestrel = next(e for e in self.wiki["entities"] if e["name"] == "Kestrel")
        self.assertEqual(kestrel["mention"], {"chapter": 1, "quote": KESTREL_SENTENCE})
        for e in self.wiki["entities"]:
            self.assertLessEqual(e["mention"]["chapter"], e["first"], e["name"])
            quote = e["mention"].get("quote", "")
            self.assertLessEqual(len(quote), 300, e["name"])
            if quote:
                text = " ".join((self.book.workdir / "chapters" / f"{e['mention']['chapter']:04d}.txt").read_text(encoding="utf-8").split())
                self.assertIn(quote, text, e["name"])

    def test_a_public_export_drops_the_mention_quote_but_keeps_its_chapter(self):
        out = self.book.root / "public"
        self.book.run_annalist("export", str(self.book.workdir), str(out), "--public")
        wiki = json.loads((out / "data" / "wiki.json").read_text(encoding="utf-8"))
        kestrel = next(e for e in wiki["entities"] if e["name"] == "Kestrel")
        self.assertEqual(kestrel["mention"], {"chapter": 1})

    def test_an_entry_with_no_facts_or_relations_is_a_minor_mention_on_its_category_page(self):
        html = self.site("route:cat:artifact@5")["route:cat:artifact@5"]["html"]
        rows, minor = self.minor_section(html)
        self.assertNotIn("Kestrel", self.text(rows))
        self.assertIn("Salt Ledger", self.text(rows))
        self.assertIn("4 entries as of chapter 5", self.text(rows))
        self.assertIn(f"Kestrel Ch 1 {KESTREL_SENTENCE}", self.text(minor))
        self.assertNotIn(f'data-ent="{self.id["Kestrel"]}"', html)

    def test_an_entry_is_minor_until_the_chapter_that_gives_it_a_relation(self):
        quay = self.id["Corvel Quay"]
        views = self.site("route:cat:place@2", "route:cat:place@3", f"{quay}@2", f"{quay}@3", "chapter:1@2", "chapter:1@3")
        rows, minor = self.minor_section(views["route:cat:place@2"]["html"])
        self.assertNotIn(f'data-ent="{quay}"', rows)
        self.assertIn("1 entries as of chapter 2", self.text(rows))
        self.assertIn(f"Corvel Quay Ch 1 {QUAY_SENTENCE}", self.text(minor))
        rows, minor = self.minor_section(views["route:cat:place@3"]["html"])
        self.assertIn(f'data-ent="{quay}"', rows)
        self.assertEqual(minor, "")
        self.assertNotIn("Facts (", views[f"{quay}@2"])
        self.assertIn(QUAY_SENTENCE, self.text(views[f"{quay}@2"]))
        self.assertIn("Relations (1)", views[f"{quay}@3"])
        self.assertIn("Corvel Quay", self.text(views["chapter:1@2"]))
        self.assertNotIn(f'data-ent="{quay}"', views["chapter:1@2"])
        self.assertIn(f'data-ent="{quay}"', views["chapter:1@3"])

    def test_a_minor_entry_is_left_out_of_counts_search_and_the_graph(self):
        views = self.site("home@5", "search:Kestrel@5", "search:Corvel@2", "search:Corvel@3",
                          "graph:all@2?isolates=1&allTypes=1", "graph:all@3?isolates=1&allTypes=1", "graph:all@5?isolates=1&allTypes=1")
        live = [e for e in self.wiki["entities"] if not (e.get("merged") and e["merged"]["chapter"] <= 5)]
        self.assertIn(f"<b>{len(live) - 1}</b>entries", views["home@5"])
        self.assertNotIn("Kestrel", self.text(views["home@5"]))
        self.assertNotIn("Kestrel", views["search:Kestrel@5"])
        self.assertNotIn("Corvel Quay", views["search:Corvel@2"])
        self.assertIn("Corvel Quay", views["search:Corvel@3"])
        labels = {view: {n["label"] for n in views[view]["model"]["nodes"]} for view in views if view.startswith("graph")}
        self.assertNotIn("Corvel Quay", labels["graph:all@2?isolates=1&allTypes=1"])
        self.assertIn("Corvel Quay", labels["graph:all@3?isolates=1&allTypes=1"])
        self.assertNotIn("Kestrel", labels["graph:all@5?isolates=1&allTypes=1"])
        self.assertIn("Salt Ledger", labels["graph:all@5?isolates=1&allTypes=1"])

    def test_the_markdown_wiki_lists_the_entry_under_minor_mentions_instead_of_giving_it_a_page(self):
        wiki = self.book.workdir / "wiki"
        self.assertFalse((wiki / "artifact" / "kestrel.md").exists())
        self.assertTrue((wiki / "place" / "corvel-quay.md").exists())
        index = (wiki / "index.md").read_text(encoding="utf-8")
        artifacts = index.split("## artifact", 1)[1].split("\n## ", 1)[0]
        rows, minor = self.minor_section(artifacts)
        self.assertNotIn("Kestrel", rows)
        self.assertIn("Kestrel", minor)
        self.assertIn("ch 1", minor)
        self.assertIn(KESTREL_SENTENCE, minor)
        self.assertNotIn("kestrel.md", index)

    def test_review_counts_the_entries_shown_only_as_minor_mentions(self):
        review = (self.book.workdir / "review.md").read_text(encoding="utf-8")
        self.assertIn("- Entries shown only as minor mentions: 1", review)
        found = next(c for c in self.book.json("review.json")["checks"] if c["title"] == "Entries shown only as minor mentions")
        self.assertEqual([f["name"] for f in found["findings"]], ["Kestrel"])
