"""Keep ordinary pytest discovery away from the developer's private state.

This runs before test modules import the legacy server (whose Hub still loads
chats at import time). Tests needing specific data build their own fixtures.
Real-engine/browser work is a separate, explicitly opted-in workflow.
"""
import os
import tempfile
from pathlib import Path

import pytest

_temporary = tempfile.TemporaryDirectory(prefix="pixal-tests-")
_root = Path(_temporary.name)
_data = _root / "data"
_engine = _root / "ComfyUI"
for _directory in (_data, _engine / "models", _engine / "input", _engine / "output"):
    _directory.mkdir(parents=True, exist_ok=True)
_environment = pytest.MonkeyPatch()
_environment.setenv("PIXAL_DATA_DIR", str(_data))
_environment.setenv("PIXAL_COMFY_DIR", str(_engine))
_environment.setenv("MOONSHOT_API_KEY", "")


def pytest_unconfigure(config):
    _environment.undo()
    _temporary.cleanup()
