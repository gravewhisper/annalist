import contextlib
import io
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from annalist.export import build
from annalist.render import cmd_render

CHAPTER = ("Ilka met the warden at the gate, and the warden was silent. The lantern bearer spoke with a bodyguard, and the bodyguard "
           "nodded. The word warden is common here, and every warden and bodyguard knows it. The Warden rank is old. Corvin Hale bowed to Sarenne. The harbor slept and the harbor woke while the Harbor waited. "
           "Mirela Danescu read the tide for a reader, and Madam Mirela said the tide reader must rest. Oskar trimmed the lamp "
           "while the lamp warden slept. Brenna Stone sat on a stone, and the stone was cold as any stone. ")


def seed(root):
    named = {1: [{"name": "Lantern bearer in the crypt", "type": "character", "aliases": []},
                 {"name": "Miss Bodyguard", "type": "character", "aliases": []},
                 {"name": "Bodyguard by the door", "type": "character", "aliases": []},
                 {"name": "Mr. Q", "type": "character", "aliases": []},
                 {"name": "Warden", "type": "rank", "aliases": []},
                 {"name": "Tide Reader expert", "type": "character", "aliases": []},
                 {"name": "Lamp warden by the stair", "type": "character", "aliases": []},
                 {"name": "Keeper in the cellar", "type": "character", "aliases": []}],
             2: [{"name": "Tide Reader expert", "type": "character", "aliases": ["Mirela", "Madam Mirela", "Tide Reader Madam Mirela"]},
                 {"name": "Lamp warden by the stair", "type": "character", "aliases": ["Lamp Warden Oskar", "Oskar"]},
                 {"name": "Keeper in the cellar", "type": "character", "aliases": ["Brenna", "Brenna Stone"]}],
             3: [{"name": "Lantern bearer in the crypt", "type": "character", "aliases": ["Corvin Hale", "Corvin"]},
                 {"name": "Miss Bodyguard", "type": "character", "aliases": ["Sarenne", "Miss Sarenne"]},
                 {"name": "The Harbor", "type": "character", "aliases": ["Mr. Harbor"]}],
             4: [{"name": "Mr. Q", "type": "character", "aliases": ["Warden"]},
                 {"name": "Tide Reader expert", "type": "character", "aliases": ["Mirela Danescu"]}]}
    (root / "state").mkdir()
    (root / "chapters").mkdir()
    for n in range(1, 5):
        (root / "chapters" / f"{n:04d}.txt").write_text(CHAPTER, encoding="utf-8")
        (root / "state" / f"{n:04d}.json").write_text(json.dumps({"chapter": n, "extraction": {"synopsis": "", "entities": named.get(n, [])}}), encoding="utf-8")
    merge = {"a": "Miss Bodyguard", "b": "Bodyguard by the door", "canonical": "Miss Bodyguard", "same": True,
             "revealed": {"basis": "text", "chapter": 2}}
    (root / "merges.json").write_text(json.dumps({"pairs": [merge]}), encoding="utf-8")
    (root / "chapters.json").write_text(json.dumps([{"index": n, "title": str(n)} for n in range(1, 5)]), encoding="utf-8")
    (root / "book.json").write_text(json.dumps({"title": "T"}), encoding="utf-8")


class RevealedTitles(unittest.TestCase):
    def pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed(root)
            return {(e["name"], e["type"]): e for e in build(root, {})[1]["entities"]}

    def test_descriptor_page_takes_the_real_name_from_its_reveal_chapter(self):
        page = self.pages()[("Corvin Hale", "character")]
        self.assertEqual(page["name_chapter"], 3)
        self.assertEqual(page["aliases"][0]["name"], "Lantern bearer in the crypt")
        self.assertEqual(page["aliases"][0]["chapter"], 1)

    def test_a_described_page_is_unnamed_only_until_its_real_name_is_known(self):
        pages = self.pages()
        self.assertEqual(pages[("Corvin Hale", "character")].get("named_from"), 3)
        self.assertTrue(pages[("Corvin Hale", "character")].get("nameless"))
        self.assertNotIn("named_from", pages[("Keeper in the cellar", "character")] if ("Keeper in the cellar", "character") in pages else {})

    def test_page_with_absorbed_descriptor_takes_the_real_name(self):
        page = self.pages()[("Sarenne", "character")]
        self.assertEqual(page["name_chapter"], 3)
        self.assertIn("Miss Bodyguard", [a["name"] for a in page["aliases"]])

    def test_an_honorific_on_a_common_word_is_not_a_real_name(self):
        self.assertIn(("The Harbor", "character"), self.pages())

    def test_a_stated_full_name_is_the_title_over_a_form_with_a_role_and_descriptor_before_the_name(self):
        page = self.pages()[("Mirela Danescu", "character")]
        self.assertEqual(page["name_chapter"], 4)
        self.assertEqual({a["name"]: a["chapter"] for a in page["aliases"]},
                         {"Tide Reader expert": 1, "Mirela": 2, "Madam Mirela": 2, "Tide Reader Madam Mirela": 2})

    def test_the_plain_name_is_the_title_over_a_descriptor_before_it_when_no_full_name_is_stated(self):
        page = self.pages()[("Oskar", "character")]
        self.assertEqual(page["name_chapter"], 2)
        self.assertIn("Lamp Warden Oskar", [a["name"] for a in page["aliases"]])

    def test_a_surname_that_is_also_a_common_word_stays_in_the_title(self):
        self.assertIn(("Brenna Stone", "character"), self.pages())

    def test_rank_word_alias_is_not_the_title_and_keeps_its_own_chapter(self):
        pages = self.pages()
        page = pages[("Mr. Q", "character")]
        self.assertEqual(page["name_chapter"], 1)
        self.assertEqual({a["name"]: a["chapter"] for a in page["aliases"]}, {"Warden": 4})
        self.assertIn(("Warden", "rank"), pages)


QUOTES = ["The word warden is common here, and every warden and bodyguard knows it.", "The Warden rank is old.",
          "The harbor slept and the harbor woke while the Harbor waited.", "Oskar trimmed the lamp while the lamp warden slept.",
          "Brenna Stone sat on a stone, and the stone was cold as any stone."]
ARCS = [{"name": "Gate", "start": 1, "end": 2}, {"name": "Tide", "start": 3, "end": 4}]


def written_about(subject):
    return [{"purpose": "summary", "contains": f'page about "{subject}"', "reply": {"summary": f"Summary of {subject}."}},
            {"purpose": "history", "contains": f'History of "{subject}"', "reply": {"paragraph": f"History of {subject}."}}]


def seed_prose(root, corrections=None):
    seed(root)
    for n in (1, 4):
        path = root / "state" / f"{n:04d}.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["extraction"]["facts"] = [{"entity": "Tide Reader expert", "claim": f"The Tide Reader expert kept watch {k}.", "quotes": [q]}
                                        for k, q in enumerate(QUOTES)]
        path.write_text(json.dumps(state), encoding="utf-8")
    (root / "arcs.json").write_text(json.dumps({"volumes": [{"arcs": ARCS}]}), encoding="utf-8")
    (root / "book.json").write_text(json.dumps({"title": "T", "backend": {"name": "fake", "script": "script.json"}}), encoding="utf-8")
    replies = [r for subject in ("Mirela Danescu", "Tide Reader expert", "Mirela of the Tides") for r in written_about(subject)]
    (root / "script.json").write_text(json.dumps({"replies": replies}), encoding="utf-8")
    if corrections:
        (root / "corrections.json").write_text(json.dumps(corrections), encoding="utf-8")


def rendered_page(corrections=None):
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}, clear=True):
        root = Path(tmp)
        seed_prose(root, corrections)
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_render(Namespace(workdir=str(root), until=None, html=False, jobs=1))
        wiki = build(root, {})[1]
    page = next(e for e in wiki["entities"] if "Tide Reader expert" in [e["name"], *(a["name"] for a in e["aliases"])])
    return {"summary": page["summary"]["text"], "summaries": [(s["chapter"], s["text"]) for s in page["summaries"]],
            "history": [(h["arc"], h["shown"], h["text"]) for h in page["history"]]}


class RevealedProse(unittest.TestCase):
    def test_a_described_page_s_prose_uses_the_description_before_the_reveal_and_the_real_name_from_it(self):
        self.assertEqual(rendered_page(), {
            "summary": "Summary of Mirela Danescu.",
            "summaries": [(1, "Summary of Tide Reader expert."), (4, "Summary of Mirela Danescu.")],
            "history": [("Gate", 2, "History of Tide Reader expert."), ("Tide", 4, "History of Mirela Danescu.")]})


if __name__ == "__main__":
    unittest.main()
