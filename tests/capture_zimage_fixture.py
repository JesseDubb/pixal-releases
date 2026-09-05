"""Capture only from the briefed checkpoint, in temporary roots with fake I/O."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def capture():
    sys.path.insert(0, str(ROOT))
    destination = ROOT / "tests/fixtures/zimage_10_14.json"
    if destination.exists():
        raise RuntimeError("Refusing to replace frozen fixture")
    source = subprocess.run(["git", "show", "ed5fa71:server.py"], cwd=ROOT,
                            capture_output=True, check=True).stdout.decode("utf-8")
    with tempfile.TemporaryDirectory(prefix="pixal-zimage-fixture-") as tmp, ExitStack() as stack:
        root = Path(tmp)
        (root / "data").mkdir()
        (root / "ComfyUI/models").mkdir(parents=True)
        stack.enter_context(patch.dict(os.environ, PIXAL_DATA_DIR=str(root / "data"),
                                      PIXAL_COMFY_DIR=str(root / "ComfyUI")))
        def forbidden(*args, **kwargs):
            raise AssertionError("No network/process actions in graph capture")
        for target in ("subprocess.Popen", "subprocess.run", "socket.socket.connect",
                       "socket.socket.connect_ex", "aiohttp.ClientSession",
                       "threading.Thread.start", "asyncio.create_task"):
            stack.enter_context(patch(target, side_effect=forbidden))
        old = types.ModuleType("checkpoint_zimage")
        old.__file__ = str(ROOT / "server.py")
        exec(compile(source, old.__file__, "exec"), old.__dict__)
        sys.path.insert(0, str(ROOT))
        from test_zimage_fixture_parity import build_case
        scenes = ["A blue ceramic cup beside an open book.",
                  "A cyclist pauses beneath a red maple tree.",
                  "Three paper boats float in a shallow stone fountain."]
        base = {"rel": "Synthetic/zimage_base.safetensors", "kind": "diffusion_models",
                "family": "zimage", "variant": "base", "supported": True,
                "execution_profile": "zimage_base"}
        turbo = {**base, "rel": "Synthetic/zimage_turbo.safetensors", "variant": "turbo",
                 "execution_profile": "zimage_turbo_v4"}
        anime = {**base, "rel": "Synthetic/clear_anime.safetensors",
                 "execution_profile": "zimage_clear_anime"}
        plan = {"version": 1, "recipe": "zimage",
                "recipe_revision": old.RECIPE_SPECS["zimage"]["lora_stack_revision"],
                "mode": "replace_editable", "entries": [
                    {"name": "Synthetic/ink.safetensors", "strength": 0.35},
                    {"name": "Synthetic/soft.safetensors", "strength": 0.6},
                    {"name": "Synthetic/off.safetensors", "enabled": False}]}
        combinations = [
            ("base-default", "build_zimage", base, {}),
            ("base-canvas-overrides", "build_zimage", base, {
                "aspect": "3:4 (Portrait Standard)", "mp": 1.0, "negative": "synthetic negative",
                "overrides": [{"node": "8", "input": "steps", "value": 17},
                              {"node": "6", "input": "width", "value": 704}]}),
            ("base-lora-plan", "build_zimage", base, {"width": 640, "height": 832, "lora_plan": plan}),
            ("turbo-default", "build_zimage", turbo, {"negative": "ignored by distilled profile"}),
            ("turbo-gguf-loras", "build_zimage", {**turbo, "rel": "Synthetic/zimage_turbo.gguf"},
             {"width": 768, "height": 512, "loras": ["Synthetic/ink.safetensors:0.25"]}),
            ("base-character", "build_zimage", base, {"width": 512, "height": 512, "character": {
                "id": "synthetic", "name": "Synthetic Adult", "style": "an adult with short silver hair", "gender": "other"}}),
            ("fantasy-base", "build_fantasy", base, {"width": 512, "height": 768}),
            ("anime-clear", "build_anime", anime, {"width": 768, "height": 512})]
        cases = []
        for index, scene in enumerate(scenes):
            for seed in (7, 424242):
                for label, builder, entry, options in combinations:
                    case = {"id": f"{index}-{seed}-{label}", "builder": builder,
                            "scene": scene, "seed": seed, "model_entry": entry, "options": options}
                    case["expected"] = json.dumps(build_case(old, case), sort_keys=True)
                    cases.append(case)
        destination.write_text(json.dumps({"checkpoint": "ed5fa71", "cases": cases},
                                          sort_keys=True, indent=1) + "\n", encoding="utf-8")
        print(f"Captured {len(cases)} checkpoint graph/caption/info cases")


if __name__ == "__main__":
    capture()
