import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from annalist.render import status_cell
from annalist.state import MAIN_TIMELINE
from annalist.status import current_status, spoken_appearances

TIMELINES = {"main": MAIN_TIMELINE,
             "run1": {"id": "run1", "kind": "run", "label": "First loop", "period": "", "started": 2, "erased": 5},
             "past": {"id": "past", "kind": "flashback", "label": "Nine winters ago", "period": "", "started": 8, "erased": None}}


def obs(value, chapter, timeline="main"):
    return {"value": value, "chapter": chapter, "timeline": timeline, "quote_ok": True, "quotes": ["q"]}


def link(n):
    return f"ch {n}"


class StatusInferenceTest(unittest.TestCase):
    def test_a_character_who_speaks_without_any_status_is_alive_as_of_their_last_line_so_far(self):
        spoke = [(3, "main"), (7, "main")]
        self.assertEqual(status_cell(current_status([], spoke, TIMELINES, 5), link), "Alive (as of ch 3, inferred)")
        self.assertEqual(status_cell(current_status([], spoke, TIMELINES, 10), link), "Alive (as of ch 7, inferred)")
        self.assertIsNone(current_status([], spoke, TIMELINES, 2))

    def test_a_death_in_the_current_timeline_stands_until_a_later_status_even_if_the_character_is_quoted(self):
        spoke = [(1, "main"), (6, "main")]
        self.assertEqual(status_cell(current_status([obs("dead", 4)], spoke, TIMELINES, 6), link), "Dead (ch 4)")
        self.assertEqual(status_cell(current_status([obs("dead", 4), obs("revived", 6)], spoke, TIMELINES, 6), link),
                         "Revived (ch 6), previously Dead (ch 4)")

    def test_a_death_in_a_run_counts_until_the_run_is_erased(self):
        status = [obs("dead", 3, "run1")]
        spoke = [(1, "main"), (6, "main")]
        self.assertEqual(status_cell(current_status(status, spoke, TIMELINES, 4), link), "Dead (ch 3)")
        self.assertEqual(status_cell(current_status(status, [], TIMELINES, 5), link), "Alive (died only in an erased timeline, ch 3)")
        self.assertEqual(status_cell(current_status(status, spoke, TIMELINES, 6), link),
                         "Alive (as of ch 6, inferred), died only in an erased timeline (ch 3)")

    def test_a_stated_status_wins_and_lines_in_a_flashback_do_not_count(self):
        self.assertEqual(status_cell(current_status([obs("revived", 6)], [(9, "main")], TIMELINES, 9), link), "Revived (ch 6)")
        self.assertEqual(status_cell(current_status([obs("dead", 4)], [(8, "past")], TIMELINES, 9), link), "Dead (ch 4)")

    def test_spoken_appearances_resolve_aliases_and_skip_the_narrator(self):
        names = {"bram": "Bram Ostrow", "master ostrow": "Bram Ostrow"}
        rows = [{"chapter": 2, "asserted_by": "Bram", "timeline": "main"},
                {"chapter": 4, "asserted_by": "Master Ostrow"},
                {"chapter": 4, "asserted_by": "narrator", "timeline": "main"}]
        self.assertEqual(spoken_appearances(rows, lambda n, _: names.get(n.lower())), {"Bram Ostrow": [(2, "main"), (4, "main")]})


SITE_JS = Path(__file__).resolve().parent.parent / "annalist" / "site" / "app.js"


def site_status(profile, timelines, n):
    source = SITE_JS.read_text(encoding="utf-8")
    parts = [re.search(pattern, source, re.S).group(0) for pattern in (
        r"const until = .*?;\n", r"function role\(tid\) \{.*?\n\}\n", r"function currentStatus\(profile\) \{.*?\n\}\n")]
    script = (f"const D = {{tl: {json.dumps(timelines)}}}; const S = {{n: {n}}};\n" + "".join(parts)
              + f"const s = currentStatus({json.dumps(profile)});\n"
              + "console.log(JSON.stringify(s && [s.value, s.chapter, s.basis, s.earlier.map(o => o.value), s.erasedDeath ?? null]));")
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SiteStatusTest(unittest.TestCase):
    def test_the_site_infers_the_same_status_as_the_python_rule_at_every_chapter(self):
        status = [obs("dead", 3, "run1"), obs("dead", 6), obs("revived", 9)]
        spoke = [(1, "main"), (4, "run1"), (7, "main"), (8, "past"), (10, "main")]
        profile = {"fields": {"status": [{k: o[k] for k in ("value", "chapter", "timeline")} for o in status]},
                   "spoke": [list(s) for s in spoke]}
        for n in range(1, 12):
            expected = current_status(status, spoke, TIMELINES, n)
            want = expected and [expected.value, expected.chapter, expected.basis,
                                 [o["value"] for o in expected.earlier], expected.erased_death]
            self.assertEqual(site_status(profile, TIMELINES, n), want, f"chapter {n}")


if __name__ == "__main__":
    unittest.main()
