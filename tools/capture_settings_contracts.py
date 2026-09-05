"""Capture pre-extraction settings behavior using synthetic, in-memory inputs.

Compiles only the reviewed settings handler from Git, never imports server,
contacts an engine or opens live configuration. Prints a fixture to stdout.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "b1cc727"
POLICY = {
    "image_modes": ["model", "pid", "vsr"],
    "vsr_tiers": ["VSR Low", "VSR Medium", "VSR High", "VSR Ultra"],
    "video_modes": ["VSR Low", "VSR Medium", "VSR High", "VSR Ultra", "LTX 2.5 2x"],
    "scale_range": [1.0, 4.0], "video_fps": [0, 30, 48, 60],
    "special_decoders": ["wan2x"], "dlss5_styles": ["default", "natural", "cinematic"],
    "h3_resolutions": ["standard", "high", "max"],
}
CATALOG = {
    "upscalers": ["2x\\synthetic.pth"], "vae": ["VAE\\synthetic.safetensors"],
    "models": {"qwen_edit": ["Qwen\\edit.safetensors"],
               "klein_edit": ["Klein\\edit.safetensors"],
               "klein_inpaint": ["Klein\\edit.safetensors"]},
    "h3_models": {"ref": ["H3\\reference.safetensors", "H3\\hybrid.safetensors"],
                  "fl": ["H3\\first.safetensors", "H3\\hybrid.safetensors"]},
    "h3_encoders": ["small"],
    "video_engines": [{"id": "h3", "models": [{"id": "fl2va"}, {"id": "ref2va"}]},
                      {"id": "ltx25", "models": [{"id": "default", "available": False}]}],
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def bodies():
    yield {}
    yield {"unknown": {"future": True}}
    fields = {
        "llm.base_url": ["  http://synthetic.invalid/v1  ", ""],
        "llm.model": ["  synthetic  ", ""], "llm.api_key": ["  synthetic-key  ", ""],
        "llm.local_model": ["  synthetic.gguf ", "", 12],
        "llm.local_keep": [True, False, "false"],
        "llm.local_gpu_layers": [-1, 0, 12, -2, True, "2", 1.5],
        "llm.local_idle_minutes": [0, 1.5, -1, True, "5"],
        "llm.official_prompting": [True, False], "critic.model": [" model ", ""],
        "upscale.image_model": ["synthetic.pth", "2x\\synthetic.pth", "", "missing"],
        "edit.model": ["qwen/edit.safetensors", "Klein\\edit.safetensors", "", "missing"],
        "edit.inpaint_model": ["Klein/edit.safetensors", "Qwen\\edit.safetensors", ""],
        "edit.inpaint_color_match": [True, False, "true"],
        "vae.zimage": ["VAE/synthetic.safetensors", "", "missing"],
        "vae.special": ["wan2x", "", None, "missing"], "vae.special_force": [True, False],
        "upscale.image_mode": ["model", "vsr", "pid", "unknown"],
        "upscale.image_vsr_mode": ["VSR Ultra", "LTX 2.5 2x", ""],
        "upscale.image_vsr_scale": [0, 2, 9, "2.5", "bad", None],
        "upscale.video_mode": ["VSR High", "LTX 2.5 2x", "unknown"],
        "upscale.video_scale": [0, 2, 9, "2.5", "bad", None],
        "upscale.video_fps": [0, 39, 54, 200, "30", "bad", None],
        "pid.identity_finish": [True, False, "false"],
        "still.film_grain": [True, False, "false"],
        "still.film_grain_amount": [-1, 1.6, 99, "2.2", "nan", None],
        "still.de_shine": [True, False, 1],
        "still.de_shine_strength": [-1, 0.85, 99, "nan", None],
        "still.dlss5": [True, False, "true"],
        "still.dlss5_style": ["default", "natural", "cinematic", "wrong"],
        "still.dlss5_tone": [-1, 1.5, 99, "nan", None],
        "h3.ref_model": ["H3/reference.safetensors", "h3/HYBRID.safetensors", "", "wrong"],
        "h3.fl_model": ["H3/first.safetensors", "H3/hybrid.safetensors", "", "wrong"],
        "h3.text_encoder": ["small", "", "wrong"],
        "video.default_engine": ["h3", "ltx25", "", "wrong"],
        "video.default_model": ["fl2va", "default", "", "wrong"],
        "video.upscale_2x": [True, False, "false"],
        "video.h3_resolution": ["standard", "high", "max", "wrong", None],
        "video.h3_dialogue_tags": ["tags", "quotes", "wrong"],
        "comfy_editor": [True, False], "comfy_console": ["tui", "plain", "wrong"],
        "extra_model_roots": [[" S:/models ", "", 7, " T:/模型 "], "ignored"],
        "comfy_url": [" http://synthetic.invalid:8188 ", "", None],
        "vram_profile": ["auto", "32", "24", "16", "wrong"],
        "explicit": ["auto", "on", "off", "wrong"],
    }
    for field, values in fields.items():
        parts = field.split(".")
        for value in values:
            yield {parts[0]: {parts[1]: value}} if len(parts) == 2 else {field: value}
    yield {"video": {"default_engine": "h3", "default_model": "fl2va"}}
    yield {"llm": {"model": "accepted locally"}, "comfy_url": "http://new.invalid",
           "explicit": "bad"}
    yield {"still": {"film_grain": "bad", "de_shine": "also bad"}}
    yield {"extra_model_roots": [], "llm": {"local_gpu_layers": 0},
           "video": {"default_engine": "h3", "default_model": "ref2va"}}


def baseline_handler():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:server.py"], cwd=ROOT).decode("utf-8")
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "settings_post")
    return compile(ast.Module(body=[node], type_ignores=[]), "<baseline settings>", "exec")


def environment(cfg, saved):
    async def nothing(*args):
        pass

    def resolve(name):
        if name in ("synthetic.pth", CATALOG["upscalers"][0]):
            return CATALOG["upscalers"][0]
        raise ValueError("synthetic upscaler not installed: " + name)

    ns = {"math": math, "asyncio": asyncio, "COMFY": "http://old.invalid:8188",
          "load_config": lambda: cfg, "save_config": lambda c: saved.append(copy.deepcopy(c)),
          "web": SimpleNamespace(json_response=lambda body, status=200: (status, body)),
          "HUB": SimpleNamespace(broadcast=lambda **k: None), "brain_badge": lambda: {},
          "free_brain_vram": nothing, "apply_comfy_url": lambda url: None,
          "_LM": {}, "_CATALOG": {}, "_SIDECAR_META": {},
          "resolve_upscale_model": resolve,
          "recipe_model_candidates": lambda r: [{"rel": n} for n in CATALOG["models"][r]],
          "_catalog_has": lambda kind, name: name in CATALOG.get(kind, []),
          "h3_lane_options": lambda lane: [{"rel": n} for n in CATALOG["h3_models"][lane]],
          "H3_TEXT_ENCODER_OPTIONS": [{"id": "small", "encoder": "enc", "projection": "proj"}],
          "_video_asset": lambda *args: True,
          "video_engine_options": lambda: copy.deepcopy(CATALOG["video_engines"])}
    mapping = {"UPSCALE_IMAGE_MODES": "image_modes", "UPSCALE_VSR_TIERS": "vsr_tiers",
               "UPSCALE_VIDEO_MODES": "video_modes", "UPSCALE_VIDEO_SCALE_RANGE": "scale_range",
               "UPSCALE_VIDEO_FPS_OPTIONS": "video_fps", "SPECIAL_DECODERS": "special_decoders",
               "DLSS5_STYLES": "dlss5_styles", "H3_RESOLUTIONS": "h3_resolutions"}
    ns.update({key: POLICY[value] for key, value in mapping.items()})
    return ns


async def capture():
    defaults = json.loads((ROOT / "tests/fixtures/config_1_3_1b.json").read_text())["defaults"]
    defaults["extension"] = {"future": "preserve"}
    code, cases = baseline_handler(), []
    for body in bodies():
        cfg, saved = copy.deepcopy(defaults), []
        ns = environment(cfg, saved)
        exec(code, ns)

        async def request_json():
            return copy.deepcopy(body)

        status, response = await ns["settings_post"](SimpleNamespace(json=request_json))
        cases.append({"body": body, "status": status, "response": response,
                      "saved_sha256": digest(saved[0]) if saved else None})
    return {"source_commit": BASELINE, "defaults": defaults, "policy": POLICY,
            "catalog": CATALOG, "cases": cases}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(capture()), indent=2, ensure_ascii=True))
