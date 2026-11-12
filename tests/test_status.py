import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from annalist.render import status_cell
from annalist.scorecard import Wiki
from annalist.state import MAIN_TIMELINE
from annalist.status import current_status, spoken_appearances, stated_appearances

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

    def test_a_death_in_a_dream_or_vision_never_makes_the_character_dead(self):
        timelines = {**TIMELINES, "dream": {"id": "dream", "kind": "vision", "label": "Tomas's nightmare", "period": "", "started": 3, "erased": None}}
        status = [obs("dead", 3, "dream")]
        self.assertIsNone(current_status(status, [], timelines, 3))
        self.assertEqual(status_cell(current_status(status, [(2, "main")], timelines, 3), link), "Alive (as of ch 2, inferred)")
        self.assertEqual(status_cell(current_status(status, [], timelines, 4, [(4, "main")]), link), "Alive (as of ch 4, inferred)")

    def test_spoken_appearances_resolve_aliases_and_skip_the_narrator(self):
        names = {"bram": "Bram Ostrow", "master ostrow": "Bram Ostrow"}
        rows = [{"chapter": 2, "asserted_by": "Bram", "timeline": "main"},
                {"chapter": 4, "asserted_by": "Master Ostrow"},
                {"chapter": 4, "asserted_by": "narrator", "timeline": "main"}]
        self.assertEqual(spoken_appearances(rows, lambda n, _: names.get(n.lower())), {"Bram Ostrow": [(2, "main"), (4, "main")]})


def fact(name, chapter, claim, status="stated", timeline="main"):
    return name, {"chapter": chapter, "entity": name, "claim": claim, "status": status, "timeline": timeline}, "entity"


def tie(source, chapter, wording, target):
    row = {"chapter": chapter, "source": source, "type": wording, "detail": "", "target": target, "status": "stated", "timeline": "main"}
    return [(source, row, "source"), (target, row, "target")]


class AppearanceInferenceTest(unittest.TestCase):
    def test_a_character_the_story_only_tells_of_is_alive_as_of_the_last_chapter_that_does(self):
        appeared = stated_appearances([fact("Livia Hale", 2, "Livia Hale is away at the lighthouse."),
                                       fact("Livia Hale", 5, "Livia Hale sent a letter from the coast.")])["Livia Hale"]
        self.assertIsNone(current_status([], [], TIMELINES, 1, appeared))
        self.assertEqual(status_cell(current_status([], [], TIMELINES, 3, appeared), link), "Alive (as of ch 2, inferred)")
        self.assertEqual(status_cell(current_status([], [], TIMELINES, 6, appeared), link), "Alive (as of ch 5, inferred)")

    def test_a_row_about_a_death_ends_the_inference_for_the_one_it_is_about_or_names(self):
        founder = re.compile(r"\bOld Corvel\b")
        appeared = stated_appearances([fact("Old Corvel", 3, "Old Corvel built the quay a century ago."),
                                       fact("Gannet Guild", 3, "The guild has kept the quay since Old Corvel died."),
                                       fact("Tomas Hale", 2, "Tomas Hale keeps the lamp."),
                                       fact("Tomas Hale", 4, "Tomas Hale was found dead on the stairs."),
                                       fact("Tomas Hale", 5, "Tomas Hale's lamp was relit.")],
                                      [("Old Corvel", founder)])
        self.assertEqual(appeared["Old Corvel"], [])
        self.assertEqual(appeared["Tomas Hale"], [(2, "main")])
        self.assertEqual(status_cell(current_status([], [], TIMELINES, 6, appeared["Tomas Hale"]), link), "Alive (as of ch 2, inferred)")

    def test_only_stated_rows_of_the_current_timeline_count(self):
        appeared = stated_appearances([fact("Bram Ostrow", 2, "Bram Ostrow may be hiding in the tower.", status="belief"),
                                       fact("Bram Ostrow", 8, "Bram Ostrow walked the quay.", timeline="past")]
                                      + tie("Bram Ostrow", 3, "rumoured to have killed", "Sister Wren"))
        self.assertEqual(appeared["Bram Ostrow"], [(3, "main"), (8, "past")])
        self.assertEqual(appeared["Sister Wren"], [])
        self.assertEqual(current_status([], [], TIMELINES, 9, appeared["Bram Ostrow"]).chapter, 3)

    def test_lines_and_observed_statuses_win_over_appearances(self):
        appeared = [(2, "main"), (9, "main")]
        self.assertEqual(current_status([], [(4, "main")], TIMELINES, 9, appeared).basis, "spoke")
        self.assertEqual(status_cell(current_status([obs("missing", 6)], [], TIMELINES, 9, appeared), link), "Missing (ch 6)")
        self.assertEqual(status_cell(current_status([obs("dead", 7, "past")], [], TIMELINES, 9, appeared), link), "Dead (ch 7)")


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

    def test_the_site_and_the_scorer_infer_alive_from_appearances_and_skip_a_dream_death_like_the_python_rule(self):
        timelines = {**TIMELINES, "dream": {"id": "dream", "kind": "vision", "label": "A nightmare", "period": "", "started": 3, "erased": None}}
        status = [obs("dead", 3, "dream"), obs("missing", 9)]
        spoke = [(6, "main")]
        appeared = [(2, "main"), (4, "main"), (7, "past"), (10, "main")]
        profile = {"fields": {"status": [{k: o[k] for k in ("value", "chapter", "timeline")} for o in status]},
                   "spoke": [list(s) for s in spoke], "appeared": [list(a) for a in appeared]}
        wiki = Wiki({"book": {}, "chapters": [{"n": n} for n in range(1, 12)], "timelines": list(timelines.values()), "relations": [], "facts": [],
                     "entities": [{"id": "e1", "name": "Tomas Hale", "type": "character", "first": 1, "profile": profile}]})
        for n in range(1, 12):
            expected = current_status(status, spoke, timelines, n, appeared)
            want = expected and [expected.value, expected.chapter, expected.basis,
                                 [o["value"] for o in expected.earlier], expected.erased_death]
            self.assertEqual(site_status(profile, timelines, n), want, f"chapter {n}")
            scored = wiki.status("e1", n)
            self.assertEqual(scored and [scored["value"], scored["chapter"], scored["basis"]], want and want[:3], f"chapter {n}")


if __name__ == "__main__":
    unittest.main()
