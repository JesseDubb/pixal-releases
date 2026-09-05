"""Capture synthetic config behavior from the committed pre-extraction function.

Prints JSON; never imports server or opens an application/user configuration.
"""
import ast
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "5ab6aae"


class MemoryConfig:
    def __init__(self, value):
        self.value = value

    def exists(self):
        return self.value is not None

    def read_text(self, **kwargs):
        return json.dumps(self.value)

    def with_suffix(self, suffix):
        return SimpleNamespace(exists=lambda: True)


def capture():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:server.py"], cwd=ROOT).decode("utf-8")
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "load_config")
    namespace = {"KIMI_URL": "https://api.moonshot.ai/v1/chat/completions", "KIMI_MODEL": "kimi-k3",
                 "os": SimpleNamespace(environ={}), "json": json,
                 "UPSCALE_IMAGE_DEFAULT_MODE": "model", "UPSCALE_IMAGE_DEFAULT_VSR_MODE": "VSR Ultra",
                 "UPSCALE_VIDEO_DEFAULT_MODE": "VSR High", "CONFIG": MemoryConfig(None)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<baseline config>", "exec"), namespace)
    defaults = namespace["load_config"]()
    cases = []
    for saved in (None, {}, {"llm": {"model": "synthetic", "future_key": 7}},
                  {"comfy_url": " http://engine.test:8188 ", "comfy_console": "plain", "vram_profile": "16"},
                  {"unknown_top_level": {"opaque": True}, "video": {"h3_resolution": "max", "future": True}},
                  {"llm": {"model": "kept partial"}, "comfy_boot_seconds": "invalid"},
                  {"edit": ["bad shape"]}, {"explicit": "unknown", "lan_access": 1},
                  {"still": {"film_grain": True, "film_grain_amount": 2.1}}, []):
        namespace["CONFIG"] = MemoryConfig(saved)
        result = namespace["load_config"]()
        digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        cases.append({"saved": saved, "sha256": digest})
    return {"source_commit": BASELINE, "defaults": defaults, "cases": cases}


if __name__ == "__main__":
    print(json.dumps(capture(), indent=2))
