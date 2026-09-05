"""Public settings projection: resolved inventory plus one configuration snapshot.

No probes, scans, configuration reloads or mutable application globals. Inventory
is constructed per request by the integration adapter, not retained as a cache.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pixal.config.values import dlss5_style, finite_still_value


@dataclass(frozen=True)
class SettingsInventory:
    llm: Mapping
    critic: Mapping
    upscale: Mapping
    edit: Mapping
    vae: Mapping
    pid: Mapping
    h3: Mapping
    video: Mapping
    still: Mapping
    model_roots: Sequence[str]
    catalog_size: int
    vram: Mapping
    comfy_url: str


def settings_response(cfg: dict, inventory: SettingsInventory, *, version: str,
                      channel: str, idle_minutes: float, de_shine_strength: float,
                      dlss5_styles: Sequence[str], h3_resolution: str) -> dict:
    """Preserve the existing wire shape, including masked credentials and defaults."""
    llm = cfg["llm"]
    key = llm.get("api_key", "")
    still = cfg.get("still") or {}
    video = cfg["video"]
    return {
        "pixal_version": version,
        "pixal_channel": channel,
        # Explicit allowlist: neither the key nor future private LLM fields leak.
        "llm": {"base_url": llm["base_url"], "model": llm["model"],
                "key_set": bool(key), "key_tail": key[-4:] if key else "",
                "local_model": llm.get("local_model", ""),
                "local_keep": llm.get("local_keep", True),
                "local_gpu_layers": llm.get("local_gpu_layers", -1),
                "local_idle_minutes": llm.get("local_idle_minutes", idle_minutes),
                "official_prompting": llm.get("official_prompting", True),
                "local_llms": inventory.llm["local_llms"],
                "official_families": inventory.llm["official_families"]},
        "critic": {"model": cfg["critic"]["model"], **inventory.critic},
        "upscale": {**cfg["upscale"], **inventory.upscale},
        "edit": {**cfg["edit"],
                 "inpaint_color_match": bool(cfg["edit"].get("inpaint_color_match", False)),
                 **inventory.edit},
        "vae": {**cfg["vae"], **inventory.vae},
        "pid": {**cfg["pid"], **inventory.pid},
        "h3": dict(inventory.h3),
        "video": {"default_engine": video["default_engine"],
                  "default_model": video["default_model"],
                  "upscale_2x": bool(video.get("upscale_2x", False)),
                  "h3_resolution": video.get("h3_resolution", h3_resolution),
                  "h3_dialogue_tags": video.get("h3_dialogue_tags", "quotes"),
                  **inventory.video},
        "still": {"film_grain": bool(still.get("film_grain", False)),
                  "film_grain_amount": finite_still_value(
                      cfg, "film_grain_amount", default=1.6, minimum=0.1, maximum=8.0),
                  "de_shine": bool(still.get("de_shine", False)),
                  "de_shine_strength": finite_still_value(
                      cfg, "de_shine_strength", default=de_shine_strength, minimum=0.1, maximum=1.0),
                  "dlss5": bool(still.get("dlss5", False)),
                  "dlss5_style": dlss5_style(cfg, dlss5_styles),
                  "dlss5_tone": finite_still_value(
                      cfg, "dlss5_tone", default=1.5, minimum=0.0, maximum=2.0),
                  **inventory.still},
        "extra_model_roots": cfg["extra_model_roots"],
        "model_roots": list(inventory.model_roots),
        "catalog_size": inventory.catalog_size,
        "vram": dict(inventory.vram),
        "comfy_url": inventory.comfy_url,
        "comfy_editor": cfg["comfy_editor"],
        "comfy_console": cfg["comfy_console"],
        "explicit": cfg["explicit"],
    }
