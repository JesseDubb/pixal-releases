"""Settings patch rules, independent of HTTP, persistence and runtime globals.

Apply to a detached working configuration and save only after this returns.
Catalog resolution is lazy: toggling a boolean must not scan installed models.
The historical strict/lenient field behavior and validation order are deliberate.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class InvalidSetting(ValueError):
    """A rejected setting, translated to the existing HTTP 400 response."""


@dataclass(frozen=True)
class SettingsChoices:
    image_modes: tuple[str, ...]
    vsr_tiers: tuple[str, ...]
    video_modes: tuple[str, ...]
    scale_range: tuple[float, float]
    video_fps: tuple[int, ...]
    special_decoders: tuple[str, ...]
    dlss5_styles: tuple[str, ...]
    h3_resolutions: tuple[str, ...]


class SettingsCatalog(Protocol):
    def resolve_upscaler(self, name: str) -> str: ...
    def model_names(self, recipe: str) -> Sequence[str]: ...
    def has_vae(self, name: str) -> bool: ...
    def h3_model_names(self, lane: str) -> Sequence[str]: ...
    def h3_encoder_available(self, name: str) -> bool: ...
    def video_engines(self) -> Sequence[dict]: ...


def _strict_bool(target, source, key):
    if key in source:
        value = source[key]
        if not isinstance(value, bool):
            raise InvalidSetting(f"not a bool: {value}")
        target[key] = value


def _finite_dial(target, source, key, low, high):
    if key not in source:
        return
    try:
        value = float(source[key])
    except (TypeError, ValueError):
        value = float("nan")
    if not math.isfinite(value):
        raise InvalidSetting(f"not a number: {source[key]}")
    target[key] = min(max(value, low), high)


def _optional_scale(cfg, source, key, limits):
    # Legacy scales degrade rather than reject, unlike the finisher dials.
    if source.get(key) is not None:
        try:
            cfg["upscale"][key] = min(max(float(source[key]), limits[0]), limits[1])
        except (TypeError, ValueError):
            pass


def _has_name(want, names):
    return any(name.replace("/", "\\").lower() == want.lower() for name in names)


def apply_settings_patch(cfg: dict, body: dict, *, choices: SettingsChoices,
                         catalog: SettingsCatalog) -> None:
    """Validate and mutate only the supplied working copy; never persist it."""
    llm = body.get("llm") or {}
    for key in ("base_url", "model", "api_key"):
        if llm.get(key):
            cfg["llm"][key] = llm[key].strip()
    if "local_model" in llm and isinstance(llm["local_model"], str):
        cfg["llm"]["local_model"] = llm["local_model"].strip()
    if "local_keep" in llm:
        cfg["llm"]["local_keep"] = bool(llm["local_keep"])
    if "local_gpu_layers" in llm:
        want = llm["local_gpu_layers"]
        if isinstance(want, bool) or not isinstance(want, int) or want < -1:
            raise InvalidSetting(f"not a gpu layer count: {want}")
        cfg["llm"]["local_gpu_layers"] = want
    if "local_idle_minutes" in llm:
        want = llm["local_idle_minutes"]
        if isinstance(want, bool) or not isinstance(want, (int, float)) or want < 0:
            raise InvalidSetting(f"not a minute count: {want}")
        cfg["llm"]["local_idle_minutes"] = want  # 0 keeps the brain resident.
    if "official_prompting" in llm:
        cfg["llm"]["official_prompting"] = bool(llm["official_prompting"])
    critic = body.get("critic") or {}
    if critic.get("model"):
        cfg["critic"]["model"] = critic["model"].strip()
    upscale = body.get("upscale") or {}
    if "image_model" in upscale and isinstance(upscale["image_model"], str):
        want = upscale["image_model"].strip()
        try:
            cfg["upscale"]["image_model"] = catalog.resolve_upscaler(want) if want else ""
        except ValueError as error:
            raise InvalidSetting(str(error)) from error
    edit = body.get("edit") or {}
    if "model" in edit and isinstance(edit["model"], str):
        want = edit["model"].strip().replace("/", "\\")
        names = (*catalog.model_names("qwen_edit"), *catalog.model_names("klein_edit"))
        if want and not _has_name(want, names):
            raise InvalidSetting(f"not an installed edit model: {want}")
        cfg["edit"]["model"] = want
    if "inpaint_model" in edit and isinstance(edit["inpaint_model"], str):
        want = edit["inpaint_model"].strip().replace("/", "\\")
        if want and not _has_name(want, catalog.model_names("klein_inpaint")):
            raise InvalidSetting(f"not an installed Klein Inpaint model: {want}")
        cfg["edit"]["inpaint_model"] = want
    if "inpaint_color_match" in edit and isinstance(edit["inpaint_color_match"], bool):
        cfg["edit"]["inpaint_color_match"] = edit["inpaint_color_match"]
    vae = body.get("vae") or {}
    if "zimage" in vae and isinstance(vae["zimage"], str):
        want = vae["zimage"].strip().replace("/", "\\")
        if want and not catalog.has_vae(want):
            raise InvalidSetting(f"VAE is not installed: {want}")
        cfg["vae"]["zimage"] = want
    if "special" in vae:
        want = (vae["special"] or "").strip()
        if want and want not in choices.special_decoders:
            raise InvalidSetting(f"not a special decoder: {want}")
        cfg["vae"]["special"] = want
    if "special_force" in vae:
        cfg["vae"]["special_force"] = bool(vae["special_force"])
    if upscale.get("image_mode") in choices.image_modes:
        cfg["upscale"]["image_mode"] = upscale["image_mode"]
    if "image_vsr_mode" in upscale:
        want = upscale["image_vsr_mode"]
        if want not in choices.vsr_tiers:
            raise InvalidSetting(f"not one of {'|'.join(choices.vsr_tiers)}: {want}")
        cfg["upscale"]["image_vsr_mode"] = want
    _optional_scale(cfg, upscale, "image_vsr_scale", choices.scale_range)
    pid = body.get("pid") or {}
    if "identity_finish" in pid:
        cfg["pid"]["identity_finish"] = bool(pid["identity_finish"])
    still = body.get("still") or {}
    target = cfg.get("still", {})
    _strict_bool(target, still, "film_grain")
    _finite_dial(target, still, "film_grain_amount", 0.1, 8.0)
    _strict_bool(target, still, "de_shine")
    _finite_dial(target, still, "de_shine_strength", 0.1, 1.0)
    _strict_bool(target, still, "dlss5")
    if "dlss5_style" in still:
        style = still["dlss5_style"]
        if style not in choices.dlss5_styles:
            raise InvalidSetting(f"unknown dlss5 style: {style}")
        target["dlss5_style"] = style
    _finite_dial(target, still, "dlss5_tone", 0.0, 2.0)
    if target and "still" not in cfg:
        cfg["still"] = target
    h3 = body.get("h3") or {}
    for key, lane in (("ref_model", "ref"), ("fl_model", "fl")):
        if key in h3 and isinstance(h3[key], str):
            want = h3[key].strip().replace("/", "\\")
            if want and not _has_name(want, catalog.h3_model_names(lane)):
                words = {"ref": "reference", "fl": "first/last-frame"}[lane]
                raise InvalidSetting(f"not an installed H3 {words} build: {want}")
            cfg.setdefault("h3", {})[key] = want
    if "text_encoder" in h3 and isinstance(h3["text_encoder"], str):
        want = h3["text_encoder"].strip()
        if want and not catalog.h3_encoder_available(want):
            raise InvalidSetting(f"not an installed H3 text encoder: {want}")
        cfg.setdefault("h3", {})["text_encoder"] = want
    video = body.get("video") or {}
    if "default_engine" in video and isinstance(video["default_engine"], str):
        want = video["default_engine"].strip()
        if want and want not in {e["id"] for e in catalog.video_engines()}:
            raise InvalidSetting(f"not a video engine: {want}")
        cfg["video"]["default_engine"] = want
    if "default_model" in video and isinstance(video["default_model"], str):
        want = video["default_model"].strip()
        # Listed but unavailable chips remain settable; rendering checks readiness.
        if want and want not in {m["id"] for e in catalog.video_engines() for m in e["models"]}:
            raise InvalidSetting(f"not a video model: {want}")
        cfg["video"]["default_model"] = want
    if "upscale_2x" in video:
        _strict_bool(cfg["video"], video, "upscale_2x")
    if "h3_resolution" in video:
        want = video["h3_resolution"]
        if not isinstance(want, str) or want not in choices.h3_resolutions:
            raise InvalidSetting(f"not one of {'|'.join(choices.h3_resolutions)}: {want}")
        cfg["video"]["h3_resolution"] = want
    if "h3_dialogue_tags" in video:
        want = video["h3_dialogue_tags"]
        if want not in ("tags", "quotes"):
            raise InvalidSetting(f"not one of tags|quotes: {want}")
        cfg["video"]["h3_dialogue_tags"] = want
    if "comfy_editor" in body:
        cfg["comfy_editor"] = bool(body["comfy_editor"])
    if "comfy_console" in body:
        want = str(body.get("comfy_console") or "")
        if want not in ("tui", "plain"):
            raise InvalidSetting(f"not a console style: {want}")
        cfg["comfy_console"] = want
    if upscale.get("video_mode") in choices.video_modes:
        cfg["upscale"]["video_mode"] = upscale["video_mode"]
    _optional_scale(cfg, upscale, "video_scale", choices.scale_range)
    if upscale.get("video_fps") is not None:
        try:
            want = int(upscale["video_fps"])
        except (TypeError, ValueError):
            want = None
        if want is not None:
            cfg["upscale"]["video_fps"] = min(choices.video_fps, key=lambda o: (abs(o - want), o))
    if isinstance(body.get("extra_model_roots"), list):
        cfg["extra_model_roots"] = [r.strip() for r in body["extra_model_roots"]
                                    if isinstance(r, str) and r.strip()]
    if "comfy_url" in body:
        cfg["comfy_url"] = (body.get("comfy_url") or "").strip()
    for key, offered, label in (("vram_profile", ("auto", "32", "24", "16"), "VRAM profile"),
                                 ("explicit", ("auto", "on", "off"), "explicit mode")):
        if key in body:
            want = str(body.get(key) or "")
            if want not in offered:
                raise InvalidSetting(f"not an {label}: {want}" if key == "explicit"
                                     else f"not a {label}: {want}")
            cfg[key] = want
