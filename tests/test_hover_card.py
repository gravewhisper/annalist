import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_graph import NODE
from tests.test_matrix import matrix_wiki

WINDOW = (1280, 720)


def link(top, left=100):
    return {"left": left, "top": top, "bottom": top + 20}


@unittest.skipIf(NODE is None, "node is not installed")
class HoverCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(matrix_wiki()), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def spot(self, r, w=320, h=450):
        view = f"hoverspot:{json.dumps([r, w, h, *WINDOW])}@1"
        return site_views(self.path, view)[view]

    def test_the_card_opens_below_a_link_with_room_under_it(self):
        self.assertEqual(self.spot(link(100), h=200)["top"], 126)

    def test_the_card_opens_above_a_link_near_the_bottom_of_the_window(self):
        spot = self.spot(link(690))
        self.assertEqual(spot["top"], 690 - 6 - 450)

    def test_a_card_too_tall_for_either_side_stays_inside_the_window(self):
        spot = self.spot(link(300), h=600)
        self.assertGreaterEqual(spot["top"], 8)
        self.assertLessEqual(spot["top"] + 600, WINDOW[1] - 8)

    def test_the_card_stays_inside_the_window_sideways(self):
        self.assertEqual(self.spot(link(100, left=1200), h=200)["left"], WINDOW[0] - 320 - 8)

    def test_the_card_is_fixed_to_the_window_so_it_never_lengthens_the_page(self):
        css = (ROOT / "annalist" / "site" / "app.css").read_text(encoding="utf-8")
        self.assertRegex(re.search(r"\.hover\{[^}]*\}", css).group(0), r"position:fixed")

    def test_a_card_never_grows_taller_than_the_window(self):
        css = (ROOT / "annalist" / "site" / "app.css").read_text(encoding="utf-8")
        self.assertRegex(re.search(r"\.hover\{[^}]*\}", css).group(0), r"max-height:calc\(100vh - 16px\);overflow:hidden")


if __name__ == "__main__":
    unittest.main()
