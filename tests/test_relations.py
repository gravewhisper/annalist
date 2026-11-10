import json
import re
import shutil
import subprocess
import unittest

from annalist.render import group_relations
from annalist.state import timeline_role
from tests.test_status import SITE_JS, TIMELINES


def rel(source, target, chapter, timeline="main", rtype="sister of", detail=""):
    return {"source": source, "type": rtype, "detail": detail, "target": target, "chapter": chapter, "timeline": timeline,
            "status": "stated", "quotes": [f"quote {chapter}"]}


ROWS = [rel("Fortuna", "Atom Cat", 3), rel("Fortuna", "Atom Cat", 7), rel("Fortuna", "Atom Cat", 9),
        rel("Fortuna", "Atom Cat", 4, "run1"), rel("Atom Cat", "Fortuna", 5, rtype="brother of"),
        rel("Fortuna", "Atom Cat", 8, "past")]
DETAIL_ROWS = [rel("Fortuna", "Atom Cat", 3, rtype="suspects", detail="of the theft"), rel("Fortuna", "Atom Cat", 5, rtype="Suspects", detail="Of the theft."),
               rel("Fortuna", "Atom Cat", 6, rtype="suspects", detail="of arson"), rel("Fortuna", "Atom Cat", 7, rtype="suspects")]


def role_at(until):
    return lambda r: timeline_role(TIMELINES.get(r.get("timeline", "main")), until)


class RelationGroupTest(unittest.TestCase):
    def test_identical_relations_collapse_but_stay_apart_from_erased_and_flashback_rows(self):
        groups = group_relations(ROWS, role_at(9))
        self.assertEqual([[r["chapter"] for r in g] for g in groups], [[3, 7, 9], [4], [5], [8]])

    def test_a_run_counts_as_current_until_it_is_erased(self):
        groups = group_relations(ROWS[:4], role_at(4))
        self.assertEqual([[r["chapter"] for r in g] for g in groups], [[3, 7, 9, 4]])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_site_groups_relations_the_same_way(self):
        source = SITE_JS.read_text(encoding="utf-8")
        parts = [re.search(pattern, source, re.S).group(0) for pattern in (
            r"function role\(tid\) \{.*?\n\}\n", r"const wordKey = .*?\n", r"const tieKey = .*?\n", r"function groupRels\(rows\) \{.*?\n\}\n")]
        for rows, until in ((ROWS, 4), (ROWS, 9), (DETAIL_ROWS, 9)):
            script = (f"const D = {{tl: {json.dumps(TIMELINES)}}}; const S = {{n: {until}}};\n" + "".join(parts)
                      + f"console.log(JSON.stringify(groupRels({json.dumps(rows)}).map(g => [g.chapters, g.quotes.length])));")
            got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
            want = [[[r["chapter"] for r in g], len(g)] for g in group_relations(rows, role_at(until))]
            self.assertEqual(got, want, f"chapter {until}")
        self.assertEqual(len(group_relations(DETAIL_ROWS, role_at(9))), 3)


if __name__ == "__main__":
    unittest.main()
