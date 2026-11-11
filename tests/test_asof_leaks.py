import html
import json
import re
import shutil
import subprocess
import sys
import unittest

from tests.test_build import MINI, MiniBuild, PROFILE_QUOTE, ROOT, build_script

NODE = shutil.which("node")
ECHO = "ECHO"
ECHOED = {
    "discover": {"entries": [{"id": "C1", "type": "concept", "summary": ECHO}, {"id": "C2", "type": "concept", "summary": ECHO}]},
    "summary": {"summary": ECHO},
    "personality": {"paragraph": ECHO},
    "history": {"paragraph": ECHO},
    "arc": {"name": ECHO, "summary": ECHO},
    "volume": {"overview": ECHO, "character_development": [{"character": "Ines Varro", "development": ECHO, "chapters": [1]}]},
    "events": {"events": [{"event": ECHO, "facts": ["F0001-001"]}]},
    "sweep": {"answers": [{"id": "Q0002-01", "answered": True, "chapter": 4, "quote": "My name was Livia Hale. Tomas was my father.”",
                           "answer": ECHO}]},
    "proofread": {"entries": [{"name": "Tomas Hale", "fields": {"occupation": [{"chapter": 1, "value": ECHO, "quotes": [
                                  "Tomas was the keeper of the harbour lamp and a sworn member of the Lamplighters' Guild"]}]}},
                              {"name": "Bram Ostrow", "fields": {"trivia": [{"chapter": 5, "value": ECHO, "quotes": ["It was Bram who broke."]}]}},
                              {"name": "Sabine Oake", "title": ECHO, "title_chapter": 3, "quotes": ["Not to the Guild, and not to Master Oake."]}],
                  "relations": [{"source": "Ines Varro", "target": "Tomas Hale", "type": ECHO, "chapter": 2,
                                 "quotes": ["He trained an apprentice."]},
                                {"source": "Livia Hale", "target": "Ines Varro", "type": ECHO, "chapter": 5, "quotes": ["Livia Hale climbed beside her."]}],
                  "questions": [{"id": "Q0001-02", "chapter": 3, "answer": ECHO, "quotes": ["Sister Wren looked at him for a long moment."]},
                                {"id": "Q0001-03", "chapter": 5, "answer": ECHO, "quotes": ["I knew the barge."]}]},
}


SAME_PERSON = {"entries": [{"name": "Captain Fenn", "same_as": "Odile Marr", "chapter": 4,
                             "quotes": ["They buried Tomas Hale in the Guild plot behind the harbour chapel on a grey, windless morning."]},
                            {"name": "Bram Ostrow", "same_as": "Sabine Oake", "chapter": 5, "quotes": ["It was Bram who broke."]}],
               "questions": [{"id": "Q0003-04", "chapter": 5, "answer": "Bram carried the drawn key home wrapped in oilcloth.",
                              "quotes": ["It was Bram who broke."]}]}


TWO_ARCS = {"arcs": [{"name": ECHO, "start": 1}, {"name": ECHO, "start": 4}]}


def echo_script():
    script = build_script()
    for r in script["replies"]:
        if r["purpose"] in ECHOED and "contains" not in r:
            r["reply"] = ECHOED[r["purpose"]]
        elif r["purpose"] == "arcs":
            r["reply"] = TWO_ARCS
        elif r["purpose"] == "reread":
            r["reply"] = {**r["reply"], "payoff": ECHO}
        elif r["purpose"] == "profile":
            r["reply"] = {**r["reply"], "personality_evidence": [
                {"value": "steady", "chapter": 1, "quotes": [PROFILE_QUOTE], "asserted_by": "narrator"}]}
        elif r["purpose"] == "death":
            r["reply"] = {**r["reply"], "circumstances": ECHO}
        elif r["purpose"] == "extract" and r["chapter"] == 4:
            resolved = [q for q in r["reply"]["questions_resolved"] if q["id"] != "Q0002-01"]
            r["reply"] = {**r["reply"], "questions_resolved": resolved}
    return script


def words(text):
    return set(re.findall(r"[a-z]+", text.lower()))


def visible_text(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


class EchoBuild(MiniBuild):
    def echo(self, *args):
        proc = subprocess.run([sys.executable, "-m", "tests.echo_annalist", *args], cwd=ROOT, env=self.env,
                              capture_output=True, text=True, timeout=300)
        if proc.returncode:
            raise AssertionError(f"annalist {args[0]} exited {proc.returncode}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return proc


class AsOfLeakTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = echo_script()
        cls.book = EchoBuild(script)
        (cls.book.workdir / "corrections.json").write_text(json.dumps(SAME_PERSON), encoding="utf-8")
        cls.book.echo("build", str(MINI), str(cls.book.workdir), "--to", "4", "--yes")
        cls.book.echo("build", str(MINI), str(cls.book.workdir), "--yes")
        cls.wiki = cls.book.json("site/data/wiki.json")
        known = {c["n"]: words((cls.book.workdir / "chapters" / f"{c['n']:04d}.txt").read_text(encoding="utf-8"))
                 for c in cls.wiki["chapters"]}
        tool = set().union(*(words(f.read_text(encoding="utf-8")) for f in (ROOT / "annalist").rglob("*") if f.suffix in (".py", ".js", ".html")))
        for r in script["replies"]:
            said = words(json.dumps(r["reply"], ensure_ascii=False))
            if r.get("chapter"):
                known[r["chapter"]] |= said
            elif ECHO not in json.dumps(r["reply"]):
                tool |= said
        cls.later = {}
        for n in range(1, max(known)):
            seen = set().union(*(known[c] for c in known if c <= n))
            later = set().union(*(known[c] for c in known if c > n))
            cls.later[n] = {w for w in later - seen - tool if len(w) >= 4}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def assertNoLeak(self, shown):
        leaks = sorted({(n, where, w) for n, strings in shown.items() for where, text in strings for w in words(text) & self.later[n]})
        self.assertEqual(leaks, [], "\n".join(map(str, leaks)) + "\nwords the book first uses after chapter N, shown as of chapter N")

    def test_the_build_joins_the_pages_a_same_person_correction_names(self):
        ids = {e["name"]: e["id"] for e in self.wiki["entities"]}
        merged = {e["name"]: e.get("merged") for e in self.wiki["entities"]}
        self.assertEqual((merged["Captain Fenn"], merged["Bram Ostrow"]),
                         ({"into": ids["Odile Marr"], "chapter": 4}, {"into": ids["Sabine Oake"], "chapter": 5}))
        bram = next(e for e in self.wiki["entities"] if e["name"] == "Bram Ostrow")
        self.assertTrue([s for s in bram["summaries"] if s["chapter"] < 5])
        answered = next(q["resolved"] for q in self.wiki["questions"] if q["id"] == "Q0003-04")
        self.assertEqual((answered["shown"], "oilcloth" in answered["answer"]), (5, True))

    def test_the_fake_model_writes_its_prompt_words_into_every_echoed_field(self):
        v = self.wiki["volumes"][0]
        entities = self.wiki["entities"]
        echoed = {"discover": next(e for e in entities if e["name"] == "Frostmonth")["blurbs"][0][1],
                  "summary": next(e["summary"]["text"] for e in entities if e.get("summary")),
                  "personality": next(e["profile"]["personality"][0]["text"] for e in entities if (e.get("profile") or {}).get("personality")),
                  "history": next(e["history"][0]["text"] for e in entities if e.get("history")),
                  "arc": v["arcs"][0]["summary"], "arc name": v["arcs"][0]["name"],
                  "history heading": next(e["history"][0]["arc"] for e in entities if e.get("history")), "volume": v["overview"], "events": v["key_events"][0]["event"],
                  "death": v["deaths"][0]["circumstances"],
                  "sweep": next(q["resolved"]["answer"] for q in self.wiki["questions"] if q["id"] == "Q0002-01"),
                  "proofread": next(q["resolved"]["answer"] for q in self.wiki["questions"] if q["id"] == "Q0001-03")}
        self.assertEqual({k for k, text in echoed.items() if "novel" in words(text)}, set(echoed))

    def test_the_proofread_keeps_only_proposals_whose_words_the_book_has_used_by_their_chapter(self):
        review = self.book.json("proofread.json")
        kept = [r["name"] for r in review["entries"]] + [r["source"] for r in review["relations"]] + [r["id"] for r in review["questions"]]
        self.assertEqual(set(kept), {"Bram Ostrow", "Livia Hale", "Q0001-03"})
        hindsight = {r["row"].get("name") or r["row"].get("source") or r["row"].get("id") for r in review["rejected"] if r["reason"].startswith("uses ")}
        self.assertEqual(hindsight, {"Tomas Hale", "Sabine Oake", "Ines Varro", "Q0001-02"})

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_no_site_view_as_of_chapter_n_shows_a_word_the_book_first_uses_after_n(self):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        shown = {}
        for n in self.later:
            views = [f"{e['id']}@{n}" for e in self.wiki["entities"]] + [f"mysteries@{n}", f"home@{n}", f"graph@{n}"]
            views += [f"chapter:{c}@{n}" for c in range(1, n + 1)] + [f"volume:{v['id']}@{n}" for v in self.wiki["volumes"]]
            ids = [e["id"] for e in self.wiki["entities"]]
            pairs = [f"graph:path:{a}~{b}@{n}" for a in ids[:3] for b in ids if a != b] + [f"graph:factions@{n}", f"graph:ladder@{n}", f"graph:all@{n}"]
            pairs += [f"graph:family@{n}", f"graph:places@{n}"]
            pairs += [f"graph:{e['id']}@{n}" for e in self.wiki["entities"] if e["type"] == "character"] + [f"graph:matrix@{n}"]
            proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), *views, *pairs],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            out.update({view: out[view]["html"] for view in pairs})
            for tab in ("matrix", "family"):
                out[f"{tab}-labels@{n}"] = " ".join(re.findall(r'aria-label="([^"]*)"', out[f"graph:{tab}@{n}"]))
            graph = out.pop(f"graph@{n}")["model"]
            labels = [n_["label"] for n_ in graph["nodes"]] + [e["label"] for e in graph["edges"]]
            shown[n] = [(view, visible_text(markup)) for view, markup in out.items()] + [("graph", " ".join(labels))]
        self.assertNoLeak(shown)

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_home_page_counts_a_volume_s_arcs_only_once_the_volume_ends(self):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        volume = self.wiki["volumes"][0]
        views = [f"home@{n}" for n in range(1, volume["to"] + 1)]
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        homes = {int(view.split("@")[1]): visible_text(markup) for view, markup in json.loads(proc.stdout).items()}
        self.assertEqual({n for n, text in homes.items() if re.search(r"\bof \d+ arcs\b", text)}, set())
        self.assertEqual({n for n, text in homes.items() if "Complete" in text}, {volume["to"]})

    def test_no_markdown_page_rendered_as_of_chapter_n_shows_a_word_the_book_first_uses_after_n(self):
        shown = {}
        for n in self.later:
            self.book.echo("render", str(self.book.workdir), "--until", str(n))
            pages = (self.book.workdir / f"wiki-ch{n:04d}").rglob("*.md")
            shown[n] = [(str(p.relative_to(self.book.workdir)), p.read_text(encoding="utf-8")) for p in pages]
        self.assertNoLeak(shown)


LIVIA_PROFILE = {
    "age": [{"value": "twelve", "chapter": 2, "quotes": ["Livia Hale was twelve that winter."], "asserted_by": "narrator"}],
    "appearance": [{"value": "white scar across the back of her left hand", "chapter": 3,
                    "quotes": ["small and quick, with a white scar across the back of her left hand."], "asserted_by": "narrator"}],
    "personality_evidence": [{"value": "watchful", "chapter": 3, "quotes": ["Sister Wren looked at him for a long moment."],
                              "asserted_by": "narrator"}],
}


def merged_profile_script():
    script = build_script()
    script["replies"].insert(0, {"purpose": "profile", "contains": 'about the character "Livia Hale"', "reply": LIVIA_PROFILE})
    return script


@unittest.skipIf(NODE is None, "node is not installed")
class MergedProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(merged_profile_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        merged = next(e for e in cls.wiki["entities"] if e["name"] == "Sister Wren")["merged"]
        assert (merged["into"], merged["chapter"]) == (cls.id["Livia Hale"], 4)

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, name, n):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        view = f"{self.id[name]}@{n}"
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), view],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return visible_text(json.loads(proc.stdout)[view])

    def markdown(self, name, n):
        self.book.run_annalist("render", str(self.book.workdir), "--until", str(n))
        page = next((self.book.workdir / f"wiki-ch{n:04d}").rglob(name.lower().replace(" ", "-") + ".md"))
        return page.read_text(encoding="utf-8")

    def views(self):
        return [(self.site, {"twelve", "white scar", "watchful"}), (self.markdown, {"twelve", "white scar"})]

    def test_before_the_merge_each_page_shows_only_the_profile_its_own_name_earned(self):
        for view, values in self.views():
            with self.subTest(view=view.__name__):
                self.assertEqual({v for v in values if v in view("Livia Hale", 3).lower()}, {"twelve"})
                self.assertEqual({v for v in values if v in view("Sister Wren", 3).lower()}, values - {"twelve"})

    def test_before_the_merge_a_line_spoken_under_one_name_shows_alive_only_on_that_page(self):
        self.assertNotIn("alive", self.site("Livia Hale", 3).lower())
        self.assertIn("alive (as of ch 3, inferred)", self.site("Sister Wren", 3).lower())

    def test_no_graph_view_ties_a_secret_identity_to_its_true_name_before_the_reveal(self):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        wren, livia = self.id["Sister Wren"], self.id["Livia Hale"]
        people = [e["id"] for e in self.wiki["entities"] if e["type"] == "character"]
        for n in (3, 4):
            views = [f"graph:all@{n}", f"graph:matrix@{n}", *(f"graph:{p}@{n}" for p in people), *(f"graph:path:{a}~{b}@{n}" for a in (wren, livia) for b in self.id.values() if a != b)]
            proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), *views],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            tied = {v for v, g in out.items() if any({l["a"], l["b"]} == {wren, livia} for l in g["model"]["links"])}
            said = {v for v, g in out.items() if re.search(r"Same person|Also known as Sister Wren|to be Livia Hale", visible_text(g["html"]))}
            if n == 3:
                self.assertEqual(tied | said, set())
            else:
                self.assertIn(f"graph:all@{n}", tied & said)
                self.assertIn(f"graph:{livia}@{n}", tied & said)

    def test_from_the_merge_the_merged_page_shows_the_whole_profile(self):
        for view, values in self.views():
            with self.subTest(view=view.__name__):
                self.assertEqual({v for v in values if v in view("Livia Hale", 4).lower()}, values)

if __name__ == "__main__":
    unittest.main()
