"""New application modules must not depend back on the legacy entry point."""
import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ImportBoundaryTests(unittest.TestCase):
    def test_no_module_imports_server_or_uses_star_imports(self):
        for path in (ROOT / "pixal").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    self.assertFalse(any(alias.name == "*" for alias in node.names), str(path))
                    names = [node.module or ""]
                else:
                    continue
                self.assertFalse(any(name == "server" or name.startswith("server.") for name in names), str(path))

    def test_imports_do_not_read_user_data_or_start_resources(self):
        modules = sorted(".".join(path.relative_to(ROOT).with_suffix("").parts)
                         for path in (ROOT / "pixal").rglob("*.py") if path.name != "__init__.py")
        code = '''
import aiohttp, asyncio, importlib, pathlib, socket, subprocess, sys
from unittest.mock import patch
from contextlib import ExitStack
def forbidden(*args, **kwargs):
    raise AssertionError("Application imports must not perform IO or start resources")
with ExitStack() as stack:
    for target in ("pathlib.Path.read_text", "pathlib.Path.read_bytes", "pathlib.Path.write_text",
                   "pathlib.Path.write_bytes", "pathlib.Path.mkdir", "pathlib.Path.glob",
                   "pathlib.Path.iterdir", "subprocess.Popen", "socket.socket.connect",
                   "aiohttp.ClientSession", "asyncio.create_task"):
        stack.enter_context(patch(target, side_effect=forbidden))
    for module in sys.argv[1:]:
        importlib.import_module(module)
assert "server" not in sys.modules
'''
        result = subprocess.run([sys.executable, "-B", "-c", code, *modules],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
