"""Pure Z-Image family assembly from resolved planning inputs.

No catalog/config/path lookup occurs here. Capability facts and sampler seat
are resolved by the adapter; the three supplied graph operations are pure
shared helpers, injected to preserve legacy patch points.
"""
import json


def build_zimage(*, template, recipe_id, seed, canvas, model, lora_stack,
                 sampler_seat, overrides, capabilities, caption, character_name,
                 negative, filename_prefix, job_info, set_unet_loader,
                 set_clip_loader, apply_lora_nodes):
    g = json.loads(json.dumps(template))
    width, height = canvas
    model_entry = model
    entries, dropped = lora_stack
    settings = sampler_seat
    clip_name, vae_name = capabilities["clip"], capabilities["vae"]
    cap = caption
    set_unet_loader(g, "1", model_entry)
    set_clip_loader(g, "2", clip_name, settings["clip_type"])
    g["3"]["inputs"]["vae_name"] = vae_name

    if recipe_id == "fantasy" and not cap.lower().startswith("d&d painterly"):
        cap = "D&D Painterly, " + cap
    elif recipe_id == "anime" and not cap.lower().startswith(("anime", "japanese anime")):
        cap = "anime, Japanese anime, " + cap
    g["4"]["inputs"]["text"] = cap
    if settings["zero_negative"]:
        # Distilled: guidance is baked in and the official Turbo pipeline does
        # not read a negative at all. Zeroing it is the documented behaviour.
        g["5"] = {"class_type": "ConditioningZeroOut",
                  "inputs": {"conditioning": ["4", 0]}}
    else:
        # A saved preset may carry its own. Until 2026-09-03 this builder took
        # no `negative` at all, so a style that set one had it dropped by the
        # kwarg filter in the chat path and silently rendered without it.
        g["5"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["2", 0],
                             "text": negative}}

    if width:
        g["6"]["inputs"]["width"] = int(width)
    if height:
        g["6"]["inputs"]["height"] = int(height)

    tail = apply_lora_nodes(g, "1", entries, "z:lora")
    if settings["sampler_graph"] == "amazing_v4":
        # Amazing Z-Image v4's measured Turbo schedule. The raw model feeds two
        # Euler passes; applying AuraFlow here caused severe artifacts.
        g.pop("7", None)
        g.pop("8", None)
        g["z:v4:sampler"] = {"class_type": "KSamplerSelect",
                              "inputs": {"sampler_name": settings["sampler"]}}
        g["z:v4:sigmas"] = {"class_type": "KarrasScheduler", "inputs": {
            "steps": 8, "sigma_max": 0.99, "sigma_min": 0.08, "rho": 0.3}}
        g["z:v4:split"] = {"class_type": "SplitSigmas",
                            "inputs": {"sigmas": ["z:v4:sigmas", 0], "step": 2}}
        g["z:v4:first"] = {"class_type": "SetFirstSigma",
                            "inputs": {"sigmas": ["z:v4:split", 1], "sigma": 0.906}}
        g["z:v4:extend"] = {"class_type": "ExtendIntermediateSigmas", "inputs": {
            "sigmas": ["z:v4:first", 0], "steps": 2, "start_at_sigma": 1.0,
            "end_at_sigma": 0.8, "spacing": "linear"}}
        common = {"model": [tail, 0], "cfg": settings["cfg"],
                  "positive": ["4", 0], "negative": ["5", 0],
                  "sampler": ["z:v4:sampler", 0]}
        g["z:v4:high"] = {"class_type": "SamplerCustom", "inputs": {
            **common, "add_noise": True, "noise_seed": int(seed),
            "sigmas": ["z:v4:split", 0], "latent_image": ["6", 0]}}
        g["z:v4:low"] = {"class_type": "SamplerCustom", "inputs": {
            **common, "add_noise": False, "noise_seed": int(seed),
            "sigmas": ["z:v4:extend", 0], "latent_image": ["z:v4:high", 0]}}
        g["9"]["inputs"]["samples"] = ["z:v4:low", 0]
    else:
        g["7"]["inputs"].update(model=[tail, 0], shift=settings["shift"])
        g["8"]["inputs"].update(seed=int(seed), steps=settings["steps"],
                                cfg=settings["cfg"], sampler_name=settings["sampler"],
                                scheduler=settings["scheduler"])
    g["10"]["inputs"]["filename_prefix"] = filename_prefix
    for o in overrides:
        g[str(o["node"])]["inputs"][o["input"]] = o["value"]
    info = {**job_info,
            "size": f"{g['6']['inputs']['width']}x{g['6']['inputs']['height']}",
            "character": character_name}
    # Read back off the graph, not off the argument: on a distilled profile the
    # branch above zeroes the negative whatever was asked for, and the ledger
    # should say what RAN. The recipe rule - info is what ran, the plan is what
    # you asked for - is the same one the LoRA stack already follows.
    if g["5"]["class_type"] == "CLIPTextEncode":
        info["negative"] = g["5"]["inputs"]["text"]
    return g, cap, info
