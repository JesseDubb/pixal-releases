"""Synthetic settings-GET contract from committed code; no server import or IO probes."""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "b1cc727"
GETTERS = ("still_film_grain_amount", "still_de_shine_strength",
           "still_dlss5_style", "still_dlss5_tone")


class FixturePath:
    @property
    def parent(self):
        return self

    def __truediv__(self, name):
        return self

    def is_dir(self):
        return True

    def is_file(self):
        return False


def environment(cfg, reads):
    async def refresh():
        pass

    def load():
        reads.append(1)
        return copy.deepcopy(cfg)

    def constant(value):
        return lambda *a, **k: copy.deepcopy(value)

    ns = {
        "load_config": load, "refresh_comfy_nodes": refresh, "math": math,
        "web": SimpleNamespace(json_response=lambda value: value),
        "PIXAL_VERSION": "1.3.1b", "PIXAL_CHANNEL": "beta", "LLM_IDLE_EVICT_S": 600,
        "DE_SHINE_STRENGTH": 0.85, "DLSS5_STYLES": ("default", "natural", "cinematic"),
        "UPSCALE_IMAGE_MODES": ("model", "pid", "vsr"),
        "UPSCALE_VSR_TIERS": ("VSR Low", "VSR Medium", "VSR High", "VSR Ultra"),
        "UPSCALE_VIDEO_MODES": ("VSR Low", "VSR Medium", "VSR High", "VSR Ultra", "LTX 2.5 2x"),
        "UPSCALE_VIDEO_FPS_OPTIONS": (0, 30, 48, 60),
        "QWEN_EDIT_MODEL": "synthetic-qwen", "KLEIN_MODEL": "synthetic-klein",
        "ZIMAGE_VAE_CANDIDATES": ("synthetic-vae",),
        "SPECIAL_DECODERS": {"wan2x": {"label": "Wan 2x", "factor": 2, "vae": "synthetic-vae"}},
        "PID_DECODE_NODE": "synthetic-pid", "H3_RESOLUTION_DEFAULT": "standard",
        "H3_RESOLUTIONS": {"standard": {"label": "Standard", "mp": 1.0},
                           "high": {"label": "High", "mp": 1.8},
                           "max": {"label": "Max", "mp": 3.1}},
        "DLSS5_DLL_NAME": "synthetic.dll", "COMFY": "http://synthetic.invalid:8188",
        "dlss5_runtime_dir": FixturePath,
    }
    facts = {
        "local_llm_models": ["synthetic.gguf"], "official_prompt_families": ["krea2"],
        "brain_vision": {"available": False}, "installed_vl_models": ["synthetic-vl"],
        "_pretty_name": {"nsfw": False}, "upscale_model_options": [{"name": "synthetic-upscale"}],
        "_pid_upscale_available": False, "_video_upscale_node": "VSR",
        "_ltx25_upscale_missing": ["missing weights"],
        "recipe_model_candidates": [{"rel": "synthetic-model", "size": 123}],
        "model_catalog": [{"rel": "synthetic-model"}], "_catalog_has": True,
        "_special_decoder_available": True, "_pid_node_available": False,
        "h3_settings_payload": {"ref_model": "synthetic", "ref": {"stale": False}},
        "h3_upscale_available": False,
        "video_engine_options": [{"id": "h3", "label": "H3", "models": [
            {"id": "fl2va", "label": "FL2VA"},
            {"id": "ref2va", "label": "REF2VA", "available": False}]}],
        "dlss5_available": False, "h3_one_frame_available": True,
        "model_roots": ["S:/synthetic-models"],
        "vram_profile_state": {"profile": "auto", "detected": "32", "effective": "32"},
    }
    ns.update({key: constant(value) for key, value in facts.items()})
    return ns


def baseline_code():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:server.py"], cwd=ROOT).decode("utf-8")
    names = {"settings_get", *GETTERS}
    nodes = [n for n in ast.parse(source).body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert len(nodes) == len(names)
    return compile(ast.Module(body=nodes, type_ignores=[]), "<baseline settings GET>", "exec")


async def capture():
    defaults = json.loads((ROOT / "tests/fixtures/config_1_3_1b.json").read_text())["defaults"]
    configurations = [copy.deepcopy(defaults)]
    old = copy.deepcopy(defaults)
    old.pop("still")
    for key in ("local_gpu_layers", "local_idle_minutes", "official_prompting"):
        old["llm"].pop(key)
    configurations.append(old)
    for still in ({"film_grain_amount": "nan", "de_shine_strength": "bad",
                   "dlss5_style": "not a style", "dlss5_tone": None},
                  {"film_grain": True, "film_grain_amount": 99, "de_shine": True,
                   "de_shine_strength": -1, "dlss5": True, "dlss5_style": "cinematic",
                   "dlss5_tone": 9}):
        cfg = copy.deepcopy(defaults)
        cfg["still"] = still
        cfg["llm"]["api_key"] = "synthetic-secret-1234"
        cfg["llm"]["extension_secret"] = "never expose this"
        configurations.append(cfg)
    code, cases = baseline_code(), []
    for cfg in configurations:
        reads = []
        ns = environment(cfg, reads)
        exec(code, ns)
        response = await ns["settings_get"](None)
        cases.append({"config": cfg, "response": response, "direct_config_reads": len(reads)})
    return {"source_commit": BASELINE, "cases": cases}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(capture()), indent=2))
