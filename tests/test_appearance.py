import unittest

from tests.test_asof_leaks import visible_text
from tests.test_build import build_script, MiniBuild, site_views

BRAM = {"appearance": [
    {"value": "salt in his hair", "chapter": 1, "quotes": ["Bram Ostrow came in from the quay with salt in his hair."], "asserted_by": "narrator"},
    {"value": "a head taller than Ines", "chapter": 4, "quotes": ["He was a head taller than her and had hauled Guild ropes since he was ten."],
     "asserted_by": "narrator"}]}
SABINE = {"appearance": [{"value": "tall and grey", "chapter": 1, "quotes": ["a tall grey woman who smiled with her mouth and kept her hands folded."],
                          "asserted_by": "narrator"}]}


def appearance_script():
    script = build_script()
    script["replies"][:0] = [{"purpose": "profile", "contains": 'about the character "Bram Ostrow"', "reply": BRAM},
                             {"purpose": "profile", "contains": 'about the character "Sabine Oake"', "reply": SABINE},
                             {"purpose": "appearance", "contains": 'page about "Bram Ostrow"', "reply": {"paragraph": "Bram Ostrow stands a head taller than Ines (ch 4)."}}]
    return script


class AppearanceParagraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(appearance_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, name, n):
        view = f"{self.id[name]}@{n}"
        return visible_text(site_views(self.book.workdir / "site" / "data" / "wiki.json", view)[view])

    def markdown(self, name, n):
        self.book.run_annalist("render", str(self.book.workdir), "--until", str(n))
        page = next((self.book.workdir / f"wiki-ch{n:04d}").rglob(name.lower().replace(" ", "-") + ".md"))
        return page.read_text(encoding="utf-8")

    def test_the_appearance_paragraph_shows_from_its_checkpoint_on_and_keeps_the_observations_in_the_fold(self):
        for n in (4, 5):
            with self.subTest(chapter=n):
                page = self.site("Bram Ostrow", n)
                self.assertIn("stands a head taller than Ines ( ch 4 ). Written from evidence up to chapter 4 Show Hide the evidence (2) salt in his hair", page)
                markdown = self.markdown("Bram Ostrow", n)
                self.assertIn("stands a head taller", markdown)
                self.assertIn("salt in his hair", markdown.split("<details>")[1])

    def test_before_its_checkpoint_the_page_lists_the_observations_instead(self):
        page = self.site("Bram Ostrow", 3)
        self.assertNotIn("stands a head taller", page)
        self.assertIn("salt in his hair", page)
        markdown = self.markdown("Bram Ostrow", 3)
        self.assertNotIn("stands a head taller", markdown)
        self.assertIn("salt in his hair", markdown)

    def test_a_character_with_one_observation_keeps_the_list_and_costs_no_call(self):
        self.assertIn("tall and grey", self.site("Sabine Oake", 5))
        self.assertIn("tall and grey", self.markdown("Sabine Oake", 5))
        self.assertEqual(len(self.book.calls("appearance")), 1)


if __name__ == "__main__":
    unittest.main()
