import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from annalist.epub import cmd_extract
from annalist.files import last_chapter, state_paths
from annalist.state import load_states
from tests.test_build import build_script, MINI, MiniBuild


class StoryEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def book(self, **values):
        (self.workdir / "book.json").write_text(json.dumps(values), encoding="utf-8")

    def test_only_a_positive_whole_number_names_the_last_chapter(self):
        self.assertIsNone(last_chapter(self.workdir))
        for value, expected in ((3, 3), (0, None), (True, None), ("3", None), (-2, None)):
            self.book(last_chapter=value)
            self.assertEqual(last_chapter(self.workdir), expected, value)

    def test_extract_drops_the_chapters_and_volume_after_the_story_ends(self):
        cmd_extract(Namespace(epub=str(MINI), workdir=str(self.workdir), min_words=0, volumes="One=1-2,Extras=3-6"))
        self.assertEqual(len(json.loads((self.workdir / "chapters.json").read_text())), 6)
        self.book(last_chapter=3)
        cmd_extract(Namespace(epub=str(MINI), workdir=str(self.workdir), min_words=0, volumes="One=1-2,Extras=3-6"))
        self.assertEqual([c["index"] for c in json.loads((self.workdir / "chapters.json").read_text())], [1, 2, 3])
        volumes = json.loads((self.workdir / "volumes.json").read_text())["volumes"]
        self.assertEqual([(v["name"], v["from"], v["to"]) for v in volumes], [("One", 1, 2), ("Extras", 3, 3)])


class StoryEndStatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(build_script())
        cls.book.build()

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_chapters_after_the_story_end_are_left_out_of_what_every_stage_loads(self):
        workdir = self.book.workdir
        whole = load_states(workdir)
        book = json.loads((workdir / "book.json").read_text())
        try:
            (workdir / "book.json").write_text(json.dumps({**book, "last_chapter": 3}), encoding="utf-8")
            self.assertEqual([int(p.stem) for p in state_paths(workdir)], [1, 2, 3])
            cut = load_states(workdir)
            self.assertEqual(max(f["chapter"] for f in cut.facts), 3)
            self.assertLess(len(cut.facts), len(whole.facts))
            self.assertEqual(sorted(cut.synopses), [1, 2, 3])
        finally:
            (workdir / "book.json").write_text(json.dumps(book), encoding="utf-8")
