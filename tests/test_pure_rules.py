"""Behavior recorded from the committed server, exercised at the new owner."""
import json
import unittest
from pathlib import Path

from pixal import versioning
from pixal.recipes import canvas, style_rules

ROOT = Path(__file__).resolve().parents[1]


class PureRuleTests(unittest.TestCase):
    def test_extracted_rules_match_pre_extraction_fixtures(self):
        fixture = json.loads((ROOT / "tests/fixtures/pure_rules_1_3_1b.json").read_text())
        for case in fixture["cases"]:
            name = case["function"]
            module = next(module for module in (versioning, canvas, style_rules) if hasattr(module, name))
            with self.subTest(function=name, args=case["args"]):
                function = getattr(module, name)
                if "error" in case:
                    with self.assertRaises((TypeError, ValueError)) as error:
                        function(*case["args"])
                    self.assertEqual(type(error.exception).__name__, case["error"]["type"])
                    self.assertEqual(str(error.exception), case["error"]["message"])
                else:
                    actual = json.loads(json.dumps(function(*case["args"])))
                    self.assertEqual(actual, case["result"])

    def test_legacy_aliases_reach_the_real_owner(self):
        import server
        for module, names in ((canvas, ("dims_for",)),
                              (versioning, ("parse_version", "compare_versions")),
                              (style_rules, ("validate_style_tuning", "style_slug", "fill_style_slots"))):
            for name in names:
                self.assertIs(getattr(server, name), getattr(module, name))
