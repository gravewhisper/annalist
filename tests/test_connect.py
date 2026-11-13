import html as html_lib
import itertools
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT

NODE = shutil.which("node")
ADDED = {"is", "was", "has", "a", "an", "the"}

ROLES = ("friend ally rival enemy servant butler mentor pupil apprentice tenant owner keeper founder leader member captain agent "
         "client patron heir cousin uncle niece widow suitor guardian steward healer").split()
PREPS = ("of", "to", "at", "for")
PRESENT = ("employs", "owns", "visits", "trusts", "guards", "hunts", "teaches", "follows", "protects", "betrays", "fears", "writes to",
           "sells bread to", "lends money to", "reports to", "prays to", "lives with")
PAST = ("killed", "hired", "married", "visited", "betrayed", "rescued", "wrote", "stole", "saw", "made", "gave", "took", "held", "led", "met",
        "bought", "sold", "sent", "found", "taught", "fought", "swore loyalty to", "lent money to", "ran away from")
STATES = ("located in", "married to", "related to", "allied with", "imprisoned in", "employed by", "born in", "hostile to", "loyal to",
          "indebted to", "worth twelve of", "known as", "buried in", "installed in")
ADVERBS = ("also", "formerly", "possibly", "secretly", "once", "reportedly")
QUALIFIERS = ("former", "suspected", "alleged", "secret", "sworn", "chief", "elder")
BONDS = ("feud with", "rivalry with", "secret courtship with", "partnership with", "agreement with", "debt to")
AUX = ("is a member of", "was hired by", "has a debt to", "can summon", "will receive gold from", "would marry", "may own")
ING = ("working for", "hunting", "guarding", "staying with")
NAMED = ("investigates target of alger wilson's information", "led klein to choose", "forwards audrey's prayer to",
         "taught by dunn in", "carries klein's letter to", "suspects of hiding audrey's ring from")


def synthetic_wordings():
    out = []
    out += [f"{r} {p}" for r, p in itertools.product(ROLES, PREPS)]
    out += [f"{q} {r} of" for q, r in itertools.product(QUALIFIERS, ROLES)]
    out += [f"{a} {r} of" for a, r in itertools.product(ADVERBS, ROLES)]
    out += [f"{a} {v}" for a, v in itertools.product(ADVERBS, PRESENT + PAST)]
    out += list(PRESENT + PAST + STATES + BONDS + AUX + ING + NAMED)
    out += [f"{a} and {b}" for a, b in itertools.combinations(PRESENT[:8], 2)]
    out += [f"{a} and {b} of" for a, b in itertools.combinations(ROLES[:10], 2)]
    out += [f"{s}, {r} of" for s, r in zip(STATES, ROLES)]
    return list(dict.fromkeys(out))

NAMES = [("Audrey Hall", "character", 1), ("Klein Moretti", "character", 1), ("Old Neil", "character", 1), ("Tarot Club", "organization", 1),
         ("Alger Wilson", "character", 1), ("Dunn Smith", "character", 1), ("Lantern", "artifact", 1), ("Hermit", "character", 2),
         ("Sage", "character", 6), ("Loner", "character", 1), ("Islet", "place", 1)]


def connect_wiki():
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": first, "type": t, "first": first, "aliases": [], "blurbs": [[first, f"{n} is here."]]}
                for i, (n, t, first) in enumerate(NAMES, 1)]
    ids = {e["name"]: e["id"] for e in entities}
    entities[NAMES.index(("Hermit", "character", 2))]["merged"] = {"into": ids["Dunn Smith"], "chapter": 4}

    def rel(c, a, t, b, fam, quote=None, unverified=False):
        row = {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": "stated", "by": "narrator",
               "quotes": [quote or f"{a} and {b} in chapter {c}."]}
        return {**row, "unverified": True} if unverified else row

    relations = [rel(c, "Audrey Hall", "follower of", "Klein Moretti", "alliance") for c in (1, 2, 3)]
    relations += [rel(1, "Audrey Hall", "member of", "Tarot Club", "membership"), rel(1, "Alger Wilson", "member of", "Tarot Club", "membership"),
                  rel(1, "Alger Wilson", "friend of", "Dunn Smith", "alliance"), rel(1, "Dunn Smith", "colleague of", "Old Neil", "alliance"),
                  rel(1, "Loner", "lives on", "Islet", "place")]
    relations += [rel(2, "Audrey Hall", "investigates target of alger wilson's information", "Alger Wilson", "investigation", "Audrey watched Alger closely."),
                  rel(2, "Audrey Hall", "investigates target of alger wilson's information", "Alger Wilson", "investigation", "FAKE QUOTE NEVER SAID", unverified=True),
                  rel(2, "Audrey Hall", "prays to", "Hermit", "faith")]
    relations += [rel(3, "Old Neil", "mentor of", "Klein Moretti", "teaching", "Old Neil taught Klein the rituals."),
                  rel(3, "Audrey Hall", "friend of", "Dunn Smith", "alliance")]
    relations += [rel(c, "Audrey Hall", "owns", "Lantern", "ownership") for c in range(1, 6)]
    relations += [rel(c, "Old Neil", "made", "Lantern", "ownership") for c in (3, 4, 5)]
    relations += [rel(6, "Audrey Hall", "friend of", "Sage", "alliance"), rel(6, "Audrey Hall", "pupil of", "Old Neil", "teaching")]
    synopses = ["The old man crossed the hall and the club met.", "A member of the club prayed.", "The old teacher spoke in the hall.",
                "Nothing changed.", "The hermit was found.", "A sage arrived."]
    return {"book": {"title": "Connections", "max": 6, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": synopses[n - 1]} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


def plain(markup):
    spaced = re.sub(r"</?(?:div|li|ol|blockquote|p|button)\b[^>]*>", " ", markup)
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", spaced))).strip()


@unittest.skipIf(NODE is None, "node is not installed")
class SiteCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = connect_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {i: n for n, i in cls.id.items()}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def site(self, *views):
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(self.path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)


class PathFinderTest(SiteCase):
    def pair(self, a, b, n, query=""):
        view = f"graph:path:{self.id.get(a, a)}~{self.id.get(b, b)}@{n}" + (f"?{query}" if query else "")
        return self.site(view)[view]

    def chains(self, out):
        return [[self.name[i] for i in r["nodes"]] for r in out["model"]["routes"]]

    def summary(self, out):
        return plain(re.search(r'<p class="pathsum"[^>]*>(.*?)</p>', out["html"], re.S).group(1))

    def test_the_shortest_chain_shrinks_as_chapters_add_relations(self):
        at1, at2 = self.pair("Audrey Hall", "Old Neil", 1), self.pair("Audrey Hall", "Old Neil", 2)
        self.assertEqual(self.chains(at1), [["Audrey Hall", "Tarot Club", "Alger Wilson", "Dunn Smith", "Old Neil"]])
        self.assertTrue(self.summary(at1).startswith("Audrey Hall and Old Neil are 4 steps apart by chapter 1."))
        self.assertEqual(self.chains(at2), [["Audrey Hall", "Alger Wilson", "Dunn Smith", "Old Neil"]])
        self.assertTrue(self.summary(at2).startswith("Audrey Hall and Old Neil are 3 steps apart by chapter 2."))

    def test_tied_chains_put_people_first_then_the_ties_that_span_more_chapters(self):
        at5 = self.pair("Audrey Hall", "Old Neil", 5)
        self.assertEqual(self.chains(at5), [["Audrey Hall", "Klein Moretti", "Old Neil"], ["Audrey Hall", "Dunn Smith", "Old Neil"],
                                            ["Audrey Hall", "Lantern", "Old Neil"]])
        self.assertEqual(len(re.findall(r'<li class="route', at5["html"])), 3)
        self.assertIn("Chain 1 · through Klein Moretti", plain(at5["html"]))

    def test_a_relation_from_a_later_chapter_is_never_used_or_shown(self):
        at5, at6 = self.pair("Audrey Hall", "Old Neil", 5), self.pair("Audrey Hall", "Old Neil", 6)
        self.assertNotIn("pupil", at5["html"])
        self.assertEqual(self.chains(at6)[0], ["Audrey Hall", "Old Neil"])
        self.assertTrue(self.summary(at6).startswith("Audrey Hall and Old Neil are directly connected by chapter 6."))
        self.assertIn("Audrey Hall is a pupil of Old Neil", plain(at6["html"]))

    def test_an_entry_not_yet_introduced_is_never_named(self):
        out = self.pair("Audrey Hall", "Sage", 5)
        self.assertEqual(out["model"]["routes"], [])
        self.assertNotIn("Sage", out["html"])
        self.assertIn("not introduced by chapter 5", self.summary(out))
        self.assertEqual(self.chains(self.pair("Audrey Hall", "Sage", 6)), [["Audrey Hall", "Sage"]])

    def test_a_merged_name_resolves_to_its_entry_as_of_the_chapter(self):
        at3, at5 = self.pair("Hermit", "Old Neil", 3), self.pair("Hermit", "Old Neil", 5)
        self.assertEqual(self.chains(at3)[0], ["Hermit", "Audrey Hall", "Klein Moretti", "Old Neil"])
        self.assertEqual(self.chains(at5), [["Dunn Smith", "Old Neil"]])
        self.assertNotIn("Hermit", at5["html"])
        self.assertIn("Both names lead to Dunn Smith by chapter 5.", self.summary(self.pair("Hermit", "Dunn Smith", 5)))
        self.assertEqual(self.chains(self.pair("Hermit", "Dunn Smith", 3)), [["Hermit", "Audrey Hall", "Dunn Smith"]])

    def test_no_chain_says_so_for_the_chapter(self):
        out = self.pair("Audrey Hall", "Loner", 5)
        self.assertEqual(out["model"]["routes"], [])
        self.assertEqual(self.summary(out), "Audrey Hall and Loner are not connected yet by chapter 5.")
        self.assertNotIn("<svg", out["html"])

    def test_turning_off_an_entry_kind_keeps_chains_from_passing_through_it(self):
        people = self.pair("Audrey Hall", "Old Neil", 1, "type=character")
        self.assertEqual(people["model"]["routes"], [])
        self.assertEqual(self.summary(people), "Audrey Hall and Old Neil are not connected yet through the kinds of entry shown by chapter 1.")
        no_things = self.pair("Audrey Hall", "Old Neil", 5, "hideType=artifact")
        self.assertEqual(self.chains(no_things), [["Audrey Hall", "Klein Moretti", "Old Neil"], ["Audrey Hall", "Dunn Smith", "Old Neil"]])
        ends = self.pair("Audrey Hall", "Lantern", 5, "type=character")
        self.assertEqual(self.chains(ends)[0], ["Audrey Hall", "Lantern"])

    def test_each_step_reads_as_a_sentence_with_its_kind_chapter_and_verified_quote(self):
        out = self.pair("Audrey Hall", "Old Neil", 5)
        best = re.search(r'<li class="route best">(.*?)</ol></li>', out["html"], re.S).group(1)
        hops = re.findall(r'<li class="hop"[^>]*>(.*?)</li>', best, re.S)
        heads = [plain(re.sub(r'<button.*', "", h, flags=re.S)) for h in hops]
        self.assertEqual(heads, ["Audrey Hall is a follower of Klein Moretti since Ch 1", "Old Neil is a mentor of Klein Moretti since Ch 3"])
        self.assertIn("var(--r-alliance)", hops[0])
        self.assertIn("var(--r-teaching)", hops[1])
        self.assertRegex(hops[1], r'<div class="discbody" id="\w+" hidden>.*<blockquote>Old Neil taught Klein the rituals\.</blockquote>')
        at2 = self.pair("Audrey Hall", "Alger Wilson", 2)
        self.assertIn("<blockquote>Audrey watched Alger closely.</blockquote>", at2["html"])
        self.assertIn("Audrey Hall investigates target of Alger Wilson's information Alger Wilson", plain(at2["html"]))
        self.assertNotIn("FAKE QUOTE", at2["html"])

    def test_the_network_drawing_highlights_the_first_chain(self):
        out = self.pair("Audrey Hall", "Old Neil", 5)
        best = [self.id[n] for n in ("Audrey Hall", "Klein Moretti", "Old Neil")]
        self.assertEqual(out["model"]["path"]["nodes"], best)
        lit = {frozenset((a, b)) for cls, a, b in re.findall(r'<path class="([^"]*)" data-a="(\w+)" data-b="(\w+)"', out["html"]) if "path" in cls.split()}
        self.assertEqual(lit, {frozenset(best[:2]), frozenset(best[1:])})
        nodes = {i for cls, i in re.findall(r'<g class="([^"]*)" data-gn="(\w+)"', out["html"]) if "path" in cls.split()}
        self.assertEqual(nodes, set(best))
        drawn = {n["id"] for n in out["model"]["nodes"]}
        self.assertEqual(drawn, {self.id[n] for n in ("Audrey Hall", "Klein Moretti", "Dunn Smith", "Lantern", "Old Neil")})

    def tag(self, out, name):
        return re.search(rf'<g class="[^"]*" data-gn="{self.id[name]}"[^>]*>.*?</g>', out["html"]).group(0)

    def label(self, out, name):
        return re.search(rf'<text class="lbl[^"]*" data-for="{self.id[name]}"[^>]*>(.*?)</text>', out["html"]).group(1)

    def test_the_drawing_uses_small_named_dots_with_no_initials(self):
        out = self.pair("Audrey Hall", "Old Neil", 5)
        self.assertNotIn('class="ini"', out["html"])
        for name in ("Audrey Hall", "Klein Moretti", "Dunn Smith", "Lantern", "Old Neil"):
            self.assertEqual(self.label(out, name), name)
            self.assertLessEqual(float(re.search(r'data-r="([\d.]+)"', self.tag(out, name)).group(1)), 12)

    def test_the_first_chain_reads_in_order_on_one_line_and_other_chains_get_their_own(self):
        out = self.pair("Audrey Hall", "Old Neil", 5)
        at = {self.name[nd["id"]]: (nd["x"], nd["y"]) for nd in out["model"]["nodes"]}
        best = ["Audrey Hall", "Klein Moretti", "Old Neil"]
        self.assertEqual(sorted(best, key=lambda n: at[n][0]), best)
        self.assertEqual(len({at[n][1] for n in best}), 1)
        self.assertEqual(len({at[n][1] for n in ("Klein Moretti", "Dunn Smith", "Lantern")}), 3)

    def test_the_box_is_only_as_tall_as_the_chains_need(self):
        self.assertRegex(self.pair("Audrey Hall", "Sage", 6)["html"], r'<svg class="[^"]*\blanes1\b')
        self.assertRegex(self.pair("Audrey Hall", "Old Neil", 5)["html"], r'<svg class="[^"]*\blanes3\b')

    def test_a_chain_marks_only_entries_and_ties_first_seen_in_the_chapter(self):
        out = self.pair("Audrey Hall", "Sage", 6)
        self.assertIn('class="ring"', self.tag(out, "Sage"))
        self.assertNotIn('class="ring"', self.tag(out, "Audrey Hall"))
        tie = next(cls for cls, a, b in re.findall(r'<path class="([^"]*)" data-a="(\w+)" data-b="(\w+)"', out["html"]) if self.id["Sage"] in (a, b))
        self.assertIn("new", tie.split())
        self.assertNotIn('class="ring"', self.pair("Audrey Hall", "Old Neil", 5)["html"])

    def test_a_chain_fades_the_dead_with_a_cross_only_from_their_death(self):
        wiki = connect_wiki()
        neil = next(e for e in wiki["entities"] if e["name"] == "Old Neil")
        neil["profile"] = {"fields": {"status": [{"chapter": 5, "value": "dead", "quotes": []}]}, "lists": {}, "spoke": [], "personality": []}
        path = Path(self.dir.name) / "dead.json"
        path.write_text(json.dumps(wiki), encoding="utf-8")
        view = f"graph:path:{self.id['Audrey Hall']}~{self.id['Old Neil']}"
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), f"{view}@4", f"{view}@5"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        before, after = out[f"{view}@4"], out[f"{view}@5"]
        self.assertNotIn("†", before["html"])
        self.assertIn("dead", re.search(r'<g class="([^"]*)"', self.tag(after, "Old Neil")).group(1).split())
        self.assertEqual(self.label(after, "Old Neil"), 'Old Neil<tspan class="dagger"> †</tspan>')
        self.assertIn("Old Neil died ch 5", self.tag(after, "Old Neil"))

    def test_the_pair_lives_in_the_address_so_a_shared_link_reopens_it(self):
        a, b = self.id["Audrey Hall"], self.id["Old Neil"]
        route = f"graph:path:{a}~{b}"
        rows = self.site(f"links:{route}@3")[f"links:{route}@3"]["rows"]
        self.assertIn({"go": route, "p": route, "n": 3}, [{k: r[k] for k in ("go", "p", "n")} for r in rows])
        self.assertIn(f"graph:path:{b}~{a}", [r["p"] for r in rows])
        self.assertTrue(all(r["n"] == 3 for r in rows))
        self.assertEqual(self.site(f"route:{route}@3")[f"route:{route}@3"]["p"], route)

    def test_the_search_boxes_hold_the_chosen_names_and_pick_the_other_end(self):
        out = self.pair("Audrey Hall", "", 3)
        self.assertIn('value="Audrey Hall"', out["html"])
        self.assertRegex(out["html"], r'id="pb" [^>]*value=""')
        self.assertEqual(self.summary(out), "Pick a second entry to see how Audrey Hall is connected to it by chapter 3.")


class EntryPageTest(SiteCase):
    def page(self, name, n):
        view = f"{self.id[name]}@{n}"
        return self.site(view)[view]

    def rows(self, page):
        box = re.search(r'<div class="egobox">.*', page, re.S).group(0)
        return [plain(li) for li in re.findall(r"<li>(.*?)</li>", box)]

    def test_each_connection_reads_as_a_sentence_with_both_ends_in_order(self):
        rows = self.rows(self.page("Audrey Hall", 3))
        self.assertIn("Audrey Hall is a follower of Klein Moretti since ch 1", rows)
        self.assertIn("Audrey Hall is a member of Tarot Club since ch 1", rows)
        self.assertIn("Audrey Hall owns Lantern since ch 1", rows)
        self.assertIn("Audrey Hall investigates target of Alger Wilson's information Alger Wilson since ch 2", rows)
        neil = self.rows(self.page("Old Neil", 3))
        self.assertIn("Old Neil is a mentor of Klein Moretti since ch 3", neil)

    def test_the_infobox_no_longer_repeats_the_connections(self):
        page = self.page("Audrey Hall", 5)
        infobox = re.search(r'<aside class="infobox">.*?</aside>', page, re.S).group(0)
        self.assertNotIn("Connections", infobox)
        self.assertNotIn("Klein Moretti", infobox)

    def test_the_page_offers_to_find_how_the_entry_is_connected_to_another(self):
        page = self.page("Audrey Hall", 3)
        a = self.id["Audrey Hall"]
        self.assertIn(f'data-go="graph:path:{a}~"', page)
        self.assertIn("How is Audrey Hall connected to…", plain(page))


class PhrasingTest(SiteCase):
    def phrased(self, wordings, n=5):
        path = Path(self.dir.name) / "wordings.txt"
        path.write_text("\n".join(wordings) + "\n", encoding="utf-8")
        view = f"phrases:{path}@{n}"
        return self.site(view)[view]

    def test_role_wordings_gain_a_verb_and_verbs_stay_as_they_are(self):
        expected = {
            "follower of": "is a follower of", "member of": "is a member of", "employs": "employs", "owns": "owns",
            "acquaintance of": "is an acquaintance of", "boss of": "is the boss of", "sequence 8 of": "is sequence 8 of",
            "located in": "is located in", "owned by": "is owned by", "born in": "was born in", "hostile to": "is hostile to",
            "in charge of": "is in charge of", "possibly member of": "is possibly a member of", "also known as": "is also known as",
            "killed": "killed", "lived in": "lived in", "wrote": "wrote", "secret courtship with": "has a secret courtship with",
            "worth twelve of": "is worth twelve of", "suspected member of": "is a suspected member of", "suspected of being": "is suspected of being",
            "suspected the identity of": "suspected the identity of", "same person as": "is the same person as", "part of": "is part of",
            "user of": "is a user of", "interchangeable at high sequences with": "is interchangeable at high sequences with",
            "financially supports": "financially supports", "is a member of": "is a member of", "ally of": "is an ally of",
        }
        self.assertEqual(self.phrased(list(expected)), expected)

    def test_names_written_in_lower_case_come_back_capitalised_and_common_words_do_not(self):
        out = self.phrased(["investigates target of alger wilson's information, collaborates with", "led klein to choose",
                            "forwards audrey's prayer to", "guards the old hall of", "taught by old neil in"])
        self.assertEqual(list(out.values()), ["investigates target of Alger Wilson's information, collaborates with", "led Klein to choose",
                                              "forwards Audrey's prayer to", "guards the old hall of", "is taught by Old Neil in"])

    def test_every_generated_wording_keeps_its_words_in_order_and_adds_only_a_verb_and_article(self):
        wordings = synthetic_wordings()
        out = self.phrased(wordings)
        self.assertEqual(set(out), set(wordings))
        for wording, said in out.items():
            given, got = wording.lower().split(), said.lower().split()
            rest = iter(got)
            self.assertTrue(all(w in rest for w in given), (wording, said))
            extra = list(got)
            for w in given:
                extra.remove(w)
            self.assertLessEqual(set(extra), ADDED, (wording, said))
            self.assertLessEqual(len(extra), 2, (wording, said))
            first = given[0]
            if first in {"is", "was", "has", "can", "will", "would", "may"} or re.fullmatch(r"[a-z]+[^su]s", first):
                self.assertEqual(said.lower(), wording.lower(), wording)
            for name in ("alger wilson", "klein", "audrey", "dunn"):
                self.assertNotRegex(said, rf"(?<![\w]){name}(?![\w])", wording)


if __name__ == "__main__":
    unittest.main()
