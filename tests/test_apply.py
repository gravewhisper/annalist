import json
import unittest

from tests.test_asof_leaks import SAME_PERSON, echo_script
from tests.test_build import MiniBuild, ROOT

RENDER_PURPOSES = ("summary", "personality", "appearance", "history")
RENDER_KEYS = ROOT / "tests" / "data" / "mini-render-keys.txt"


def render_keys(workdir):
    return sorted(p.name for p in (workdir / "cache").iterdir() if p.name.split("-")[0] in RENDER_PURPOSES)


class RenderKeysTest(unittest.TestCase):
    def test_a_two_volume_build_asks_the_render_prompts_it_always_asked(self):
        book = MiniBuild(echo_script())
        self.addCleanup(book.close)
        (book.workdir / "corrections.json").write_text(json.dumps(SAME_PERSON), encoding="utf-8")
        book.build("--volumes", "1-3,4-5")
        self.assertEqual(render_keys(book.workdir), RENDER_KEYS.read_text(encoding="utf-8").split(),
                         "a render prompt changed, so every built run pays for it again; if that is meant, rewrite " + RENDER_KEYS.name)


if __name__ == "__main__":
    unittest.main()
