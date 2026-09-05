"""Public registrations are frozen before relocating their implementation."""
import ast
import json
import unittest
from pathlib import Path

from tools.audit_architecture import inventory, route_contract

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "tests/fixtures/architecture_1_3_1b.json").read_text(encoding="utf-8"))


class ArchitectureContractTests(unittest.TestCase):
    def test_registered_routes_keep_methods_paths_and_order(self):
        from pixal.http.routes import ROUTES
        self.assertEqual([{"method": route.method, "path": route.path} for route in ROUTES],
                         BASELINE["routes"])

    def test_public_recipe_ids_remain_available(self):
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
        spec = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "RECIPE_SPECS"
                            for target in node.targets))
        self.assertEqual([ast.literal_eval(key) for key in spec.keys], BASELINE["recipe_ids"])

    def test_inventory_distinguishes_initializers_and_runtime_calls(self):
        report = inventory('VALUE = 1\nSTATE = dict()\ndef update():\n global STATE\n STATE = dict(value=VALUE)\n')
        self.assertEqual(report["call_initializers"], [{"line": 2, "names": ["STATE"]}])
        self.assertEqual(report["definitions"][0]["declared_globals"], ["STATE"])
        self.assertIn("VALUE", report["definitions"][0]["module_name_references"])
