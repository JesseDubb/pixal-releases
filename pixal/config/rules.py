"""Configuration defaults and legacy merge rules, with explicit inputs only."""

def default_config(*, kimi_url: str, kimi_model: str, api_key: str,
                   image_mode: str, image_vsr_mode: str, video_mode: str) -> dict:
    cfg = {"llm": {"base_url": kimi_url.rsplit("/chat", 1)[0],
                   "api_key": api_key,
                   "model": kimi_model,
                   "local_model": "",         # GGUF path for the managed local brain
                   "local_keep": True,        # keep it in VRAM between replies
                   # ...but not forever: hand the card back after this many
                   # idle minutes. 0 disables the reaper entirely.
                   "local_idle_minutes": 10,
                   # -1 = every layer on the GPU (the hardcoded flag before
                   # 8.7), 0 = CPU, positive = that many layers. The 16 GB
                   # knob: the brain shares the card or the render swaps.
                   "local_gpu_layers": -1,
                   # 9.60: the writer runs the model maker's own expansion
                   # prompt (prompts/official/<family>.txt) in place of Pixal's
                   # craft rules. Off = the same prompts as before, verbatim.
                   # Default ON since 2026-08-27: the fresh product A/B
                   # (Official 2, Pixal 1, draw 1) and Jesse's own picks
                   # all came from the official arm; Off stays available.
                   "official_prompting": True},
           "critic": {"model": "Qwen3-VL-4B-Instruct"},
           # Upscaling is a finishing step, not a recipe: the image side runs any
           # installed ESRGAN-style model, the video side runs the RTX VSR filter.
           "upscale": {"image_model": "", "image_mode": image_mode,
                       # The still-side VSR tier + scale (9.79) are SEPARATE
                       # keys from video_mode/video_scale: those are the
                       # user's clip settings, and a still preference must
                       # not drag them around - video_scale=1.0 (the fps-only
                       # finish) would silently turn the still enlarger into
                       # a no-op.
                       "image_vsr_mode": image_vsr_mode,
                       "image_vsr_scale": 2.0,
                       "video_mode": video_mode,
                       "video_scale": 2.0,
                       # 0 = the clip's own rate (9.53); 30/48/60 RIFE-
                       # interpolates the finisher pass to that rate.
                       "video_fps": 0},
           # Which Qwen-Image-Edit release runs an instruction edit. "" = the
           # recipe default. Releases differ in encoder node (see
           # set_qwen_edit_encoder), so this is a real choice, not a preference.
           # "inpaint_model" is the masked lane's own pick (9.29): a painted
           # mask routes the edit to Klein, and until this key existed that
           # lane was hard-pinned to KLEIN_MODEL no matter what was installed.
           # "speed" picks between the model's own distillation and its
           # un-accelerated schedule; the step counts behind both come from
           # EDIT_ACCELERATORS, never from the user, because a distillation
           # belongs to one transformer.
           "edit": {"model": "", "inpaint_model": "",
                    # Default-off Klein inpaint color correction (10.12).
                    "inpaint_color_match": False, "speed": "turbo"},
           # Which H3 builds the lanes reach for when a render names none
           # (9.91). Two slots because H3 has two lanes and they take
           # different weights: ref_model serves the reference lanes
           # (h3_ref_still, h3_ref_still_2x, h3_ref2v), fl_model the
           # first/last-frame ones (h3_still, h3_still_2x, h3_i2v,
           # h3_multishot). "" = resolve by scan: one installed candidate
           # is the default, several keep the standing preference. A
           # hybrid fl2va/ref2va build is a candidate for BOTH slots. A
           # pick whose file leaves the catalog degrades to the scan
           # answer (reported on /api/settings) rather than raising. This
           # is NOT the Animate popup's opening chip - that stays
           # video.default_model, a different question.
           "h3": {"ref_model": "", "fl_model": "",
                # Which text encoder every H3 lane loads (9.94): "" = the
                # stock 32B, exactly as before; an id from
                # H3_TEXT_ENCODER_OPTIONS loads that small encoder through
                # ClipProjLoader with its projection. One decision, not
                # five - the node's mode/device stay fixed. A pick whose
                # files leave the catalog degrades to the 32B (reported on
                # /api/settings) rather than raising.
                "text_encoder": ""},
           # Optional decoder swap for the Z-Image/Flux VAE - "" keeps the
           # profile's own matched VAE. See zimage_vae_candidates().
           "vae": {"zimage": "", "special": "", "special_force": False},
           # NVIDIA PiD as the finishing decoder. identity_finish routes the
           # Identity Edit sampler's final latent through PiD at 4x instead of
           # the Wan VAE - experimental: Krea 2 shares Qwen-Image's latent
           # space, but PiD's qwenimage decoder was not trained on Krea 2.
           "pid": {"identity_finish": False},
           # Which engine the Animate popup opens on, and which model inside
           # it. "" = the server's order (LTX 2.5 first, stock FL2VA inside
           # H3). Deliberate defaults, set in Settings - the popup itself
           # still switches freely per clip. "upscale_2x" is the H3 2x row's
           # opening position under the same contract (9.31) - it can never

           # be a finished-clip action, so a standing default is the whole
           # setting. "h3_dialogue_tags" (9.38) picks how spoken lines are
           # written in H3 briefs: "quotes" is the MiniMax-H3 #76 form,
           # `(S1) says "..."`, and the default since the 2026-08-25 same-seed
           # A/B (no opening blip, no cue read aloud); "tags" is MiniMax's
           # trained <d>[Lang] ... </d>, which some seeds open with a
           # half-second of gibberish.
           # "h3_resolution" (9.55) is the Resolution row's opening position
           # under the same contract as "upscale_2x": the popup still picks
           # the canvas per clip, and the bigger tiers multiply the render's
           # time (a 10s Max clip is ~20 min on a 5090).
           "video": {"default_engine": "", "default_model": "",
                     "upscale_2x": False, "h3_resolution": "standard",
                     "h3_dialogue_tags": "quotes"},
           # 10.1: film grain replaced skin1x. Jesse retired the 1x skin
           # model ("that skin 1 ... just didnt do a good job" - it read as
           # skin only on close portraits, posterization wider, rejected
           # twice at 1:1); the judged dewax grain takes its seat. A config
           # written when skin_finish existed still loads - the dead key is
           # simply never read.
           "still": {"film_grain": False, "film_grain_amount": 1.6,
                     # 9.93: de-shine, numpy on the delivered frame. Needs no
                     # file, node or VRAM, so the toggle is the whole gate -
                     # still OFF until judged, like every other finisher.
                     "de_shine": False,
                     # 10.9: the one exposed de-shine dial, the blend
                     # strength; the doc's 0.85 is the judged default.
                     "de_shine_strength": 0.85,
                     # 10.5: DLSS 5, the chain's FIRST finisher - a whole-frame
                     # neural re-render through the ComfyUI-DLSS5-NR node. Same
                     # doctrine as grain: fresh installs render untouched.
                     "dlss5": False, "dlss5_style": "default",
                     "dlss5_tone": 1.5},
           "extra_model_roots": [],
           "comfy_url": "",
           "comfy_root": "",
           "setup_done": False,
           # Measured cold-start time, so the boot meter is calibrated to this
           # machine. 0 = never measured; the UI falls back to a constant.
           "comfy_boot_seconds": 0.0,
           # VRAM profile: "auto" follows the detected card; "32"/"24"/"16"
           # pin a tier (community testers simulate smaller cards; a laptop
           # eGPU can read wrong). Advisory layer only - the butler enforces.
           "vram_profile": "auto",
           # Pop ComfyUI's own graph editor in a browser tab when its console
           # boots. Off by default: the popup is jarring mid-chat, and the node
           # editor is a power tool, not part of the studio flow.
           "comfy_editor": False,
           # How ComfyUI's own window looks. "tui" wraps the launcher in
           # comfy_tui.py - a phase meter, a card meter, and an errors-only log
           # that outlives the window. "plain" is the raw .bat console, which is
           # the escape hatch if the wrapper ever misreads this machine.
           "comfy_console": "tui",
           # Chrome PWA id pixal.vbs opens the app window with - per machine,
           # only exists after that machine installs the PWA; "" makes the vbs
           # fall back to chrome --app= (no PWA needed).
           "chrome_app_id": "",
           # Bind every interface instead of loopback, so a phone, a tablet or
           # a VR headset on the same Wi-Fi can open the studio. Off by
           # default - this is the one setting that puts Pixal on a network.
           # access_gate still stands: any Host that is not localhost has to
           # present ?key=<access_key> once, which then rides a cookie.
           "lan_access": False,
           # Keep the studio open with no window connected. Off by default: at
           # the desk, closing the window SHOULD take the model stack down with
           # it. On for a remote session, where a backgrounded phone tab is not
           # the same thing as "done for the day". See exit_when_unwatched().
           "stay_up": False,
           # Whether a render may be explicit, which decides one thing: if the
           # wardrobe lock is appended to the prompt (see wardrobe_lock_for -
           # the fineporn base drops clothing without it). "auto" reads the
           # words the user actually wrote; "on" and "off" stop it guessing.
           # It only bites with Prompt enhance OFF, where there is no brain in
           # the path to infer nsfw - with enhance on the brain still decides.
           "explicit": "auto",
           "access_key": ""}
    return cfg


def merge_saved_config(cfg: dict, saved: dict) -> dict:
    """Apply the existing on-disk whitelist in place; nested extension keys survive."""
    cfg["llm"].update(saved.get("llm") or {})
    cfg["critic"].update(saved.get("critic") or {})
    cfg["upscale"].update(saved.get("upscale") or {})
    cfg["edit"].update(saved.get("edit") or {})
    cfg["h3"].update(saved.get("h3") or {})
    cfg["vae"].update(saved.get("vae") or {})
    cfg["pid"].update(saved.get("pid") or {})
    cfg["video"].update(saved.get("video") or {})
    cfg["still"].update(saved.get("still") or {})
    cfg["extra_model_roots"] = saved.get("extra_model_roots") or []
    cfg["comfy_url"] = (saved.get("comfy_url") or "").strip()
    cfg["comfy_root"] = (saved.get("comfy_root") or "").strip()
    cfg["setup_done"] = bool(saved.get("setup_done"))
    # Top-level runtime values must be admitted here. ConfigStore preserves
    # unknown on-disk extension fields when saving; omission is not deletion.
    cfg["comfy_boot_seconds"] = float(saved.get("comfy_boot_seconds") or 0.0)
    if str(saved.get("vram_profile") or "") in ("auto", "32", "24", "16"):
        cfg["vram_profile"] = str(saved["vram_profile"])
    cfg["chrome_app_id"] = (saved.get("chrome_app_id") or "").strip()
    cfg["comfy_editor"] = bool(saved.get("comfy_editor"))
    if str(saved.get("comfy_console") or "") in ("tui", "plain"):
        cfg["comfy_console"] = str(saved["comfy_console"])
    cfg["lan_access"] = bool(saved.get("lan_access"))
    cfg["stay_up"] = bool(saved.get("stay_up"))
    if str(saved.get("explicit") or "") in ("auto", "on", "off"):
        cfg["explicit"] = str(saved["explicit"])
    cfg["access_key"] = (saved.get("access_key") or "").strip()
    return cfg
