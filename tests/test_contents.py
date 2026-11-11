import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_category_table import table_wiki, text


def long_page_wiki():
    wiki, ids = table_wiki()
    ada = next(e for e in wiki["entities"] if e["name"] == "Ada Marsh")
    ada["profile"]["lists"] = {"appearance": [{"value": "a grey oilskin coat", "chapter": 1, "quotes": []}],
                               "trivia": [{"value": "rows faster than anyone on the quay", "chapter": 2, "quotes": []}]}
    ada["profile"]["personality"] = [{"text": "Ada Marsh is patient.", "chapter": 2}]
    ada["history"] = [{"arc": "The first tide", "start": 1, "end": 2, "chapter": 2, "text": "Ada Marsh joins the Lamp Guild."}]
    return wiki, ids


def contents(markup):
    nav = re.search(r'<nav class="toc" aria-label="Contents">(.*?)</nav>', markup, re.S)
    return [(m[0], text(m[1])) for m in re.findall(r'<a data-sec="([^"]*)"[^>]*>(.*?)</a>', nav.group(1))] if nav else []


class ContentsListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wiki, ids = long_page_wiki()
        ada = ids["Ada Marsh"]
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
            out = site_views(path, f"{ada}@1", f"{ada}@2", f"{ada}@2?tab=facts", f"{ids['Harbour']}@3")
        cls.short, cls.long, cls.facts, cls.place = out[f"{ada}@1"], out[f"{ada}@2"], out[f"{ada}@2?tab=facts"], out[f"{ids['Harbour']}@3"]

    def test_a_long_page_lists_its_sections_in_page_order(self):
        self.assertEqual([title for _, title in contents(self.long)],
                         ["Summary", "Connections", "Appearance", "Personality", "History", "Trivia", "Facts", "Relations"])

    def test_every_entry_links_to_a_section_on_the_page(self):
        self.assertTrue(contents(self.long))
        for key, title in contents(self.long):
            self.assertIn(f'id="sec-{key}"', self.long, title)

    def test_a_section_on_another_tab_switches_to_that_tab(self):
        href = {title: link for link, title in re.findall(r'<a data-sec="[^"]*" data-in="[^"]*" href="([^"]*)">([^<]*)</a>', self.facts)}
        self.assertIn("tab=profile", href["History"])
        self.assertIn("tab=relations", href["Relations"])

    def test_a_short_page_and_a_section_not_yet_written_get_no_entry(self):
        self.assertEqual(contents(self.short), [])
        self.assertEqual(contents(self.place), [])
        self.assertNotIn("History", text(self.short))


if __name__ == "__main__":
    unittest.main()
