import unittest

from annalist.llm import parse_json_object


class StrayClosers(unittest.TestCase):
    def test_removes_a_stray_bracket_after_a_summary_and_keeps_every_entry(self):
        reply = '{"entities":[{"name":"A","summary":"First one."]},{"name":"B","summary":"Second."}],"facts":[]}'
        self.assertEqual(parse_json_object(reply), {"entities": [{"name": "A", "summary": "First one."}, {"name": "B", "summary": "Second."}], "facts": []})

    def test_removes_more_than_one_stray_bracket(self):
        reply = '{"entities":[{"name":"A"]},{"name":"B"]}]}'
        self.assertEqual(parse_json_object(reply), {"entities": [{"name": "A"}, {"name": "B"}]})

    def test_keeps_a_bracket_inside_a_string(self):
        self.assertEqual(parse_json_object('{"a":"x ] y","b":[1]}'), {"a": "x ] y", "b": [1]})

    def test_still_rejects_a_reply_a_stray_bracket_does_not_explain(self):
        with self.assertRaises(ValueError):
            parse_json_object('{"a":"b" "c":"d"}')
