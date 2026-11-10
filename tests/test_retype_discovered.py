import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from annalist.retype import cmd_retype
from annalist.state import load_states


def state(n, facts):
    return {"chapter": n, "extraction": {"synopsis": "", "entities": [], "facts": facts}}


class RetypeSeesEveryStub(unittest.TestCase):
    def test_an_entry_a_stale_discover_list_covers_is_still_typed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            (root / "chapters").mkdir()
            facts = {1: [], 2: [{"entity": "Greyhold", "claim": "Greyhold is a keep.", "quotes": ["Greyhold"], "asserted_by": "narrator", "status": "stated"}]}
            for n in (1, 2):
                (root / "chapters" / f"{n:04d}.txt").write_text("Greyhold is a keep.", encoding="utf-8")
                (root / "state" / f"{n:04d}.json").write_text(json.dumps(state(n, facts[n])), encoding="utf-8")
            (root / "book.json").write_text(json.dumps({"title": "T", "backend": {"name": "fake"}}), encoding="utf-8")
            discovered = {"entities": [{"name": "Greyhold", "type": "place", "summary": "A keep.", "chapter": 1}], "rejected": []}
            (root / "discover.json").write_text(json.dumps(discovered), encoding="utf-8")
            with patch("annalist.retype.cached_llm", return_value={"items": [{"id": 1, "type": "place", "reason": "a keep"}]}) as asked:
                cmd_retype(Namespace(workdir=str(root), jobs=1))
            self.assertEqual(asked.call_count, 1)
            self.assertIn("Name: Greyhold [uncategorized]", asked.call_args[0][2])
            (root / "discover.json").unlink()
            self.assertEqual(load_states(root).entities["Greyhold"]["type"], "place")


if __name__ == "__main__":
    unittest.main()
