import json
import subprocess
import unittest

from tests.test_asof_leaks import NODE, visible_text
from tests.test_build import MiniBuild, PROFILE_QUOTE, ROOT, build_script

KEEPER_QUOTE = "At half past four Ines lit the harbour lamp and wrote the hour in the Salt Ledger"
HOME_QUOTE = "The harbour lamp of Corvel Quay had burned every night for two hundred years, except one."
INES_PROFILE = {
    "age": [{"value": "nineteen", "chapter": 1, "quotes": [PROFILE_QUOTE], "asserted_by": "narrator"}],
    "occupation": [{"value": "apprentice to the lamp keeper", "chapter": 1, "quotes": [PROFILE_QUOTE], "asserted_by": "narrator"},
                   {"value": "keeper of the harbour lamp", "chapter": 5, "quotes": [KEEPER_QUOTE], "asserted_by": "narrator"}],
    "residence": [{"value": "Corvel Quay", "chapter": 1, "quotes": [HOME_QUOTE], "asserted_by": "narrator"}],
}


def occupation_script():
    script = build_script()
    script["replies"].insert(0, {"purpose": "profile", "contains": 'about the character "Ines Varro"', "reply": INES_PROFILE})
    return script


class OccupationResidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(occupation_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.ines = next(e for e in cls.wiki["entities"] if e["name"] == "Ines Varro")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, n):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        view = f"{self.ines['id']}@{n}"
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), view],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)[view]

    def markdown(self, n):
        self.book.run_annalist("render", str(self.book.workdir), "--until", str(n))
        return next((self.book.workdir / f"wiki-ch{n:04d}").rglob("ines-varro.md")).read_text(encoding="utf-8")

    def test_the_profile_keeps_quoted_occupation_and_residence_values(self):
        fields = self.book.json("profiles.json")["characters"]["Ines Varro"]["fields"]
        self.assertEqual([(o["value"], o["chapter"], o["quote_ok"]) for o in fields["occupation"]],
                         [("apprentice to the lamp keeper", 1, True), ("keeper of the harbour lamp", 5, True)])
        self.assertEqual([(o["value"], o["chapter"], o["quote_ok"]) for o in fields["residence"]], [("Corvel Quay", 1, True)])

    def test_the_exported_wiki_holds_both_fields(self):
        fields = self.ines["profile"]["fields"]
        self.assertEqual([(o["value"], o["chapter"]) for o in fields["occupation"]],
                         [("apprentice to the lamp keeper", 1), ("keeper of the harbour lamp", 5)])
        self.assertEqual([(o["value"], o["chapter"]) for o in fields["residence"]], [("Corvel Quay", 1)])

    def test_the_markdown_infobox_shows_a_new_occupation_only_from_its_chapter(self):
        early, late = self.markdown(4), self.markdown(5)
        self.assertIn("| **Occupation** | Apprentice to the lamp keeper", early)
        self.assertNotIn("keeper of the harbour lamp", early.lower())
        self.assertIn("| **Occupation** | Keeper of the harbour lamp", late)
        self.assertIn("previously Apprentice to the lamp keeper", late)
        self.assertIn("| **Residence** | Corvel Quay", early)

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_site_infobox_shows_a_new_occupation_only_from_its_chapter_and_links_the_residence(self):
        corvel = next(e["id"] for e in self.wiki["entities"] if e["name"] == "Corvel Quay")
        early, late = self.site(4), self.site(5)
        self.assertIn("Occupation Apprentice to the lamp keeper (ch 1)", visible_text(early))
        self.assertNotIn("keeper of the harbour lamp", visible_text(early).lower())
        self.assertIn("Occupation Keeper of the harbour lamp (ch 5)", visible_text(late))
        self.assertIn("previously Apprentice to the lamp keeper (ch 1)", visible_text(late))
        self.assertIn(f'<tr><th>Residence</th><td><a class="ent" data-ent="{corvel}"', early)


if __name__ == "__main__":
    unittest.main()
