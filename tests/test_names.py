import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from annalist.discover import candidates
from annalist.names import name_key, name_tokens
from annalist.state import Knowledge

ROOT = Path(__file__).resolve().parent.parent


class NameKeyTest(unittest.TestCase):
    def test_curly_and_straight_quotes_share_a_key(self):
        self.assertEqual(name_key("Fortuna’s Cat"), name_key("Fortuna's Cat"))
        self.assertEqual(name_key("“Doc” Holliday"), name_key('"Doc" Holliday'))
        self.assertEqual(name_tokens("O’Brien’s Hound"), name_tokens("O'Brien's Hound"))

    def test_entities_differing_only_by_apostrophe_merge(self):
        kb = Knowledge()
        first = kb.upsert_entity({"name": "D’Artagnan", "type": "character"}, 1)
        second = kb.upsert_entity({"name": "D'Artagnan", "type": "character"}, 2)
        self.assertEqual(first, second)
        self.assertEqual(len(kb.entities), 1)


PAIRS_SCRIPT = """
import json, sys
from pathlib import Path
from annalist.resolve import candidate_pairs
from annalist.state import Knowledge
workdir = Path(sys.argv[1])
kb = Knowledge()
kb.upsert_entity({"name": "Ryan Romano", "type": "character"}, 1)
kb.upsert_entity({"name": "Len Ottavio", "type": "character"}, 1)
kb.upsert_entity({"name": "the hooded cloaked masked stranger", "type": "character"}, 1)
pairs = candidate_pairs(workdir, kb, {}, 1)
print(json.dumps({" | ".join(k): v for k, v in sorted(pairs.items())}, sort_keys=True))
"""


class ResolveDeterminismTest(unittest.TestCase):
    def test_candidate_pairs_do_not_depend_on_hash_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chapters").mkdir()
            (Path(tmp) / "chapters" / "0001.txt").write_text(
                "Ryan Romano watched the hooded figure. The cloaked man nodded to Ryan Romano. "
                "A masked shape slipped past Ryan Romano.\n", encoding="utf-8")
            outputs = set()
            for seed in ("1", "2", "3", "4", "5"):
                proc = subprocess.run([sys.executable, "-c", PAIRS_SCRIPT, tmp], capture_output=True, text=True, cwd=ROOT,
                                      env={**os.environ, "PYTHONHASHSEED": seed}, check=True)
                outputs.add(proc.stdout)
            self.assertEqual(len(outputs), 1, outputs)
            self.assertIn("stub-descriptor", next(iter(outputs)))


class PronounNameTest(unittest.TestCase):
    def state(self):
        return {"chapter": 1, "extraction": {"synopsis": "", "entities": [
            {"name": "She", "type": "deity", "summary": "the goddess"},
            {"name": "Ines Hale", "type": "character", "aliases": ["her", "Lamp Girl"]}],
            "facts": [{"entity": "She", "claim": "She rules the moon.", "quotes": ["She rules the moon."]},
                      {"entity": "Ines Hale", "claim": "Ines keeps the lamp.", "quotes": ["Ines keeps the lamp."]}],
            "relations": [{"source": "Ines Hale", "target": "Him", "type": "prays to", "quotes": ["Ines prayed to Him."]},
                          {"source": "Ines Hale", "target": "Tomas Hale", "type": "daughter of", "quotes": ["y"]}]}}

    def test_a_pronoun_never_becomes_an_entry_or_an_alias(self):
        kb = Knowledge()
        kb.apply(self.state())
        self.assertEqual(sorted(kb.entities), ["Ines Hale", "Tomas Hale"])
        self.assertEqual(kb.entities["Ines Hale"]["aliases"], ["Lamp Girl"])
        self.assertEqual([(f["id"], f["entity"]) for f in kb.facts], [("F0001-002", "Ines Hale")])
        self.assertEqual([(r["id"], r["target"]) for r in kb.relations], [("R0001-002", "Tomas Hale")])

    def test_discovery_skips_a_capitalized_pronoun(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chapters").mkdir()
            for n in (1, 2):
                (Path(tmp) / "chapters" / f"{n:04d}.txt").write_text(
                    "The keepers prayed to She who rules the moon, and to Him, and to Saint Corvel by the quay.\n", encoding="utf-8")
            kb = Knowledge()
            kb.synopses = {1: "", 2: ""}
            self.assertEqual([c["name"] for c in candidates(tmp, kb)], ["Saint Corvel"])


if __name__ == "__main__":
    unittest.main()
