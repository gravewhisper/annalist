import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from annalist.deaths import verified_revivals
from annalist.evidence import add_evidence
from annalist.state import Knowledge
from annalist.status import current_status

TEXTS = {1: "Ilse lived.", 2: "Ilse fell dead on the road. Oda lived on.", 3: "They buried Ilse.",
         4: "Ilse opened her eyes and stood up alive. \"I am back,\" Ilse said.", 5: "Ilse walked on."}
OK = {"quote_ok": True, "timeline": "main", "asserted_by": "narrator", "quotes": ["Ilse fell dead on the road."]}


def spoke(name, n):
    return {"id": f"F{n}", "chapter": n, "entity": name, "claim": f"{name} spoke.", "quotes": [TEXTS[n][:10]], "asserted_by": name,
            "status": "stated", "timeline": "main"}


class Revivals(unittest.TestCase):
    def setup_kb(self, root):
        (root / "chapters").mkdir()
        for n, text in TEXTS.items():
            (root / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")
        kb = Knowledge()
        kb.synopses = {n: "" for n in TEXTS}
        for person in ("Ilse", "Oda"):
            kb.upsert_entity({"name": person, "type": "character", "aliases": []}, 1)
        kb.facts = [spoke("Ilse", 1), spoke("Ilse", 4), spoke("Oda", 3)]
        return kb

    def run_check(self, reply):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = self.setup_kb(root)
            profiles = {"Ilse": {"fields": {"status": [{"value": "dead", "chapter": 2, **OK}]}, "extra": {}, "lists": {}},
                        "Oda": {"fields": {"status": [{"value": "alive", "chapter": 1, **OK}]}, "extra": {}, "lists": {}}}
            with patch("annalist.deaths.cached_llm", side_effect=lambda w, purpose, prompt, check=None: self.answer(reply, purpose, prompt, check)) as asked:
                found = verified_revivals(root, kb, profiles, [], 5, 1)
            book = {"extra_fields": {}, "field_values": {}}
            for name, profile in profiles.items():
                add_evidence(root, kb, name, profile, {}, found, book)
            return found, profiles, kb, asked.call_count

    def answer(self, reply, purpose, prompt, check):
        self.assertEqual(purpose, "revival")
        self.assertIn("Ilse", prompt)
        self.assertIsNone(check(reply))
        return reply

    def test_one_check_per_flagged_character_and_a_quote_checked_revival(self):
        reply = {"returned": True, "chapter": 4, "quotes": ["Ilse opened her eyes and stood up alive."], "reason": "She wakes."}
        found, profiles, kb, calls = self.run_check(reply)
        self.assertEqual(calls, 1)
        self.assertEqual([(d["name"], d["value"], d["chapter"], d["quote_ok"]) for d in found], [("Ilse", "revived", 4, True)])
        status = profiles["Ilse"]["fields"]["status"]
        self.assertEqual([(o["value"], o["chapter"]) for o in status], [("dead", 2), ("revived", 4)])
        self.assertEqual(current_status(status, [(4, "main")], kb.timelines, 3).value, "dead")
        self.assertEqual(current_status(status, [(4, "main")], kb.timelines, 4).value, "revived")

    def test_no_return_leaves_the_death_standing(self):
        found, profiles, _, calls = self.run_check({"returned": False, "reason": "A channeled spirit."})
        self.assertEqual(calls, 1)
        self.assertEqual(found, [])
        self.assertEqual([o["value"] for o in profiles["Ilse"]["fields"]["status"]], ["dead"])

    def test_a_bad_chapter_or_quote_is_rejected_by_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = self.setup_kb(root)
            profiles = {"Ilse": {"fields": {"status": [{"value": "dead", "chapter": 2, **OK}]}, "extra": {}, "lists": {}}}
            seen = []

            def capture(workdir, purpose, prompt, check=None):
                seen.append(check)
                return {"returned": False, "reason": ""}

            with patch("annalist.deaths.cached_llm", side_effect=capture):
                verified_revivals(root, kb, profiles, [], 5, 1)
            check = seen[0]
            self.assertIsNotNone(check({"returned": True, "chapter": 2, "quotes": ["Ilse fell dead on the road."]}))
            self.assertIsNotNone(check({"returned": True, "chapter": 4, "quotes": ["words that are not in the chapter at all"]}))


if __name__ == "__main__":
    unittest.main()
