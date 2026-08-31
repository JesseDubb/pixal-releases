"""Brief 9.91 - Settings owns which H3 model is default.

Three times in one afternoon (2026-08-31) the app named one model and rendered
with another, because more than one place decided what a recipe's default is.
Jesse's call: stop deriving it, store it. Two slots - h3.ref_model for the
reference lanes (h3_ref_still, h3_ref_still_2x, h3_ref2v), h3.fl_model for the
first/last-frame lanes (h3_still, h3_still_2x, h3_i2v, h3_multishot). "" =
resolve by scan; a set slot wins outright; a stale slot degrades to the scan
answer and says so. A hybrid fl2va/ref2va build is a candidate for BOTH slots.

What these tests pin:

  ConfigShape    - the h3 block's defaults, the old-config backfill, and a
                   saved pick's round-trip, all through a temp-dir config.
  LaneMembership - h3_build_lanes: stock fl2va -> fl only, stock ref2va ->
                   ref only, a hybrid -> both; compatible_recipes files a
                   hybrid under all four H3 still recipes.
  ScanDefault    - (accept 1+2) one installed candidate of a type IS the
                   default; several keep the standing preference (b30-49 by
                   name for the ref lane, stock fl2va for the fl lane), so no
                   machine's behaviour changes silently on upgrade.
  SetSlot        - (accept 3) a set slot wins over scan and preference, on
                   BOTH sides: the /api/options payload and the built graph's
                   UNETLoader.
  Hybrid         - (accept 4) a hybrid is offered in both slots, both slots
                   accept it by POST, and the still lanes render it. The
                   Animate lane guards are unchanged: a ref2va-carrying chip
                   is still refused by i2v/multishot - the chip is the lane
                   switch (9.12), and the slots do not reopen it.
  StaleSlot      - (accept 5) a pick whose file left the catalog degrades to
                   the scan answer on both sides, nothing raises, and the
                   settings payload reports the stale pick.
  ExplicitWins   - (accept 6) build_*(..., model=X) loads X, always.
  VideoSlots     - the video builders take their model=None default from the
                   slot's chip: i2v/multishot from fl_model, ref2v from
                   ref_model.
  Agreement      - (accept 7) for every recipe with at least one runnable
                   model, the model HUB.options reports equals the model the
                   render lane resolves - a loop over RECIPE_SPECS under four
                   slot states, so instance 4 fails in CI instead of on
                   Jesse's screen.
  Settings       - the endpoint payload carries both slots with candidates,
                   the Automatic resolution and the stale flag; POST validates
                   the same contract edit.model has.

Same sanctioned simulation as every sibling file: stubbed catalog, stubbed
character, temp-dir configs, no generation, no ComfyUI, no GPU.
"""

import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_h3_model_slots", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

STOCK = server.H3_MODEL
REF2VA = server.H3_REF2V_MODEL
HYBRID_B15 = "Minimax H3\\minimax_h3_hybrid_fl2va_ref2va_b15-29-int8.safetensors"
HYBRID_B20 = "Minimax H3\\minimax_h3_hybrid_fl2va_ref2va_b20-49-int8.safetensors"
HYBRID_B25 = "Minimax H3\\minimax_h3_hybrid_fl2va_ref2va_b25-39-int8.safetensors"
HYBRID_B30 = "Minimax H3\\minimax_h3_hybrid_fl2va_ref2va_b30-49-int8.safetensors"
FL_FINETUNE = "Minimax H3\\10eros_max_fl2va_beta2.safetensors"
REF_FINETUNE = "Minimax H3\\surrealism_ref2va_v2.safetensors"
GONE = "Minimax H3\\deleted_ref2va_build.safetensors"

CHARACTER = {"id": "mia", "name": "Mia", "age": 24, "race": "Korean",
             "sex": "female", "style": "silver pixie cut, lean runner's build",
             "identity_ref": "mia.png"}


def add(root, kind, rel, size=1):
    return {"rel": rel, "kind": kind, "root": str(root), "size": size,
            "mtime": 0.0}


def h3_stack(root, builds=(STOCK, REF2VA), **kw):
    """The shared H3 assets plus the given transformer builds."""
    entries = [add(root, "diffusion_models", rel) for rel in builds]
    entries += [add(root, "vae", server.H3_VIDEO_VAE),
                add(root, "vae", server.H3_AUDIO_VAE),
                add(root, "text_encoders", server.H3_CLIP)]
    if kw.get("image_vae"):
        entries.append(add(root, "vae", server.H3_IMAGE_VAE))
    return entries


def every_recipe_default(root):
    """Every recipe's authored default on disk, so the agreement loop has at
    least one runnable model per recipe."""
    rels = {spec["default_model"] for spec in server.RECIPE_SPECS.values()}
    return [add(root, "diffusion_models", rel) for rel in sorted(rels)]


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def cfg_with(h3=None):
    return {"h3": h3 or {"ref_model": "", "fl_model": ""},
            "extra_model_roots": []}


def full_cfg(h3=None):
    """The settings endpoint's whole-config stand-in, the edit tests' shape."""
    return {"llm": {"base_url": "", "model": ""},
            "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
            "pid": {}, "video": {"default_engine": "", "default_model": ""},
            "h3": h3 or {"ref_model": "", "fl_model": ""},
            "extra_model_roots": [], "comfy_editor": False,
            "comfy_console": "tui", "explicit": "auto", "vram_profile": "auto"}


class FakeRequest:
    """The aiohttp stand-in every settings_post test file keeps local."""
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def anchored(root):
    """A temp ComfyUI dir whose input/ holds the anchor's reference photo."""
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / CHARACTER["identity_ref"]).write_bytes(b"reference")
    return (patch.object(server, "CDIR", root),
            patch.object(server, "CHARACTERS", {CHARACTER["id"]: CHARACTER}))


def unet_name(graph):
    """The transformer the graph loads, whichever node id loads it."""
    return next(node["inputs"]["unet_name"] for node in graph.values()
                if node["class_type"] == "UNETLoader")


def build_ref_still(entries, cfg, **kwargs):
    with TemporaryDirectory() as td:
        root = Path(td)
        cdir, chars = anchored(root)
        sidecar, roots = no_disk()
        with cdir, chars, sidecar, roots, \
             patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)):
            return server.build_h3_ref_still("A red barn at dusk", 424242,
                                             character="mia", **kwargs)


def build_still(entries, cfg, **kwargs):
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        sidecar, roots = no_disk()
        with sidecar, roots, \
             patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)):
            return server.build_h3_still("A red barn at dusk", 424242, **kwargs)


def hub_options(entries, cfg):
    """HUB.options over the stubbed catalog - the payload side of the agreement."""
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        sidecar, roots = no_disk()
        with patch.object(server, "CDIR", root), \
             patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)), \
             sidecar, roots, \
             patch.object(server, "lm_enrich"), \
             patch.object(server, "_LORA_TITLE_CACHE", root / "titles.json"):
            return server.Hub().options()


def recipe_rows(entries, cfg):
    return {row["id"]: row for row in hub_options(entries, cfg)["recipes"]}


class ConfigShapeTests(unittest.TestCase):
    """The h3 block: defaults, backfill, round-trip - temp-dir config only."""

    def test_the_defaults_are_two_empty_slots(self):
        with TemporaryDirectory() as td:
            with patch.object(server, "CONFIG", Path(td) / "config.json"):
                self.assertEqual(server.load_config()["h3"],
                                 {"ref_model": "", "fl_model": "",
                                  # 9.94 grew the block by the encoder pick;
                                  # the two slot defaults are unchanged
                                  "text_encoder": ""})

    def test_an_old_config_without_the_block_backfills(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps({"edit": {"model": "x"}}),
                            encoding="utf-8")
            with patch.object(server, "CONFIG", path):
                self.assertEqual(server.load_config()["h3"],
                                 {"ref_model": "", "fl_model": "",
                                  "text_encoder": ""})

    def test_a_saved_pick_round_trips(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps(
                {"h3": {"ref_model": REF2VA, "fl_model": STOCK}}),
                encoding="utf-8")
            with patch.object(server, "CONFIG", path):
                cfg = server.load_config()
        self.assertEqual(cfg["h3"]["ref_model"], REF2VA)
        self.assertEqual(cfg["h3"]["fl_model"], STOCK)


class LaneMembershipTests(unittest.TestCase):
    """h3_build_lanes: the ONE membership rule, and its profile fallout."""

    def profile(self, rel):
        sidecar, roots = no_disk()
        with sidecar, roots:
            return server.model_profile(rel)

    def test_stock_builds_serve_exactly_one_lane_each(self):
        self.assertEqual(server.h3_build_lanes(STOCK), {"fl2va"})
        self.assertEqual(server.h3_build_lanes(REF2VA), {"ref2va"})

    def test_a_hybrid_serves_both_lanes(self):
        self.assertEqual(server.h3_build_lanes(HYBRID_B30),
                         {"fl2va", "ref2va"})

    def test_finetunes_follow_their_token(self):
        self.assertEqual(server.h3_build_lanes(FL_FINETUNE), {"fl2va"})
        self.assertEqual(server.h3_build_lanes(REF_FINETUNE), {"ref2va"})

    def test_the_profile_carries_the_lanes(self):
        self.assertEqual(self.profile(HYBRID_B30)["lanes"],
                         ["fl2va", "ref2va"])
        self.assertEqual(self.profile(STOCK)["lanes"], ["fl2va"])
        self.assertEqual(self.profile(REF2VA)["lanes"], ["ref2va"])

    def test_a_hybrid_is_a_candidate_for_all_four_still_recipes(self):
        self.assertEqual(server.compatible_recipes(self.profile(HYBRID_B30)),
                         ["h3_still", "h3_still_2x",
                          "h3_ref_still", "h3_ref_still_2x"])


class ScanDefaultTests(unittest.TestCase):
    """An unset slot resolves by scan: one candidate IS the default; several
    keep the standing preference, so no machine changes silently on upgrade."""

    def choice(self, lane, entries, cfg=None):
        sidecar, roots = no_disk()
        with sidecar, roots, \
             patch.object(server, "load_config",
                          return_value=cfg or cfg_with()), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)):
            return server.h3_slot_choice(lane)

    def test_one_ref_build_is_the_default(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(REF2VA,))
            self.assertEqual(self.choice("ref", entries)["rel"], REF2VA)

    def test_one_fl_build_is_the_default(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK,))
            self.assertEqual(self.choice("fl", entries)["rel"], STOCK)

    def test_a_lone_hybrid_is_both_lanes_default(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(HYBRID_B30,))
            self.assertEqual(self.choice("ref", entries)["rel"], HYBRID_B30)
            self.assertEqual(self.choice("fl", entries)["rel"], HYBRID_B30)

    def test_several_ref_builds_keep_the_b30_preference(self):
        """Accept 2: b15/b20/b25/b30 + stock ref2va, slot "" -> b30-49."""
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(
                REF2VA, HYBRID_B15, HYBRID_B20, HYBRID_B25, HYBRID_B30))
            self.assertEqual(self.choice("ref", entries)["rel"], HYBRID_B30)

    def test_without_b30_the_highest_block_start_wins(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(
                REF2VA, HYBRID_B15, HYBRID_B20, HYBRID_B25))
            self.assertEqual(self.choice("ref", entries)["rel"], HYBRID_B25)

    def test_no_hybrid_keeps_stock_ref2va(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(REF2VA, REF_FINETUNE))
            self.assertEqual(self.choice("ref", entries)["rel"], REF2VA)

    def test_several_fl_builds_keep_stock_fl2va(self):
        """The fl lane's standing default is stock - hybrids do not displace
        it by scan, only by the user's pick."""
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(
                STOCK, FL_FINETUNE, HYBRID_B30))
            self.assertEqual(self.choice("fl", entries)["rel"], STOCK)

    def test_nothing_installed_resolves_none(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK,))
            self.assertIsNone(self.choice("ref", entries))


class SetSlotTests(unittest.TestCase):
    """Accept 3: a set slot beats scan and preference, on BOTH sides."""

    def test_the_ref_slot_wins_everywhere(self):
        cfg = cfg_with({"ref_model": REF2VA, "fl_model": ""})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(REF2VA, HYBRID_B30))
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "load_config", return_value=cfg), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                self.assertEqual(server.h3_slot_choice("ref")["rel"], REF2VA)
            rows = recipe_rows(entries, cfg)
            self.assertEqual(rows["h3_ref_still"]["default_model"], REF2VA)
            self.assertEqual(rows["h3_ref_still_2x"]["default_model"], REF2VA)
            g, _cap, _info = build_ref_still(entries, cfg)
            self.assertEqual(unet_name(g), REF2VA)

    def test_the_fl_slot_wins_everywhere(self):
        cfg = cfg_with({"ref_model": "", "fl_model": FL_FINETUNE})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, FL_FINETUNE))
            rows = recipe_rows(entries, cfg)
            self.assertEqual(rows["h3_still"]["default_model"], FL_FINETUNE)
            self.assertEqual(rows["h3_still_2x"]["default_model"], FL_FINETUNE)
            g, _cap, _info = build_still(entries, cfg)
            self.assertEqual(unet_name(g), FL_FINETUNE)


class HybridTests(unittest.TestCase):
    """Accept 4: offered in both slots, settable in both, and it renders."""

    def test_the_hybrid_is_offered_in_both_lanes(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA, HYBRID_B30))
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                ref_ids = [o["rel"] for o in server.h3_lane_options("ref")]
                fl_ids = [o["rel"] for o in server.h3_lane_options("fl")]
        self.assertIn(HYBRID_B30, ref_ids)
        self.assertIn(HYBRID_B30, fl_ids)
        self.assertNotIn(STOCK, ref_ids)       # a pure fl2va build is not
        self.assertNotIn(REF2VA, fl_ids)       # offered across lanes

    def test_the_same_hybrid_in_both_slots_renders_both_still_lanes(self):
        cfg = cfg_with({"ref_model": HYBRID_B30, "fl_model": HYBRID_B30})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA, HYBRID_B30))
            g, _cap, _info = build_ref_still(entries, cfg)
            self.assertEqual(unet_name(g), HYBRID_B30)
            g, _cap, _info = build_still(entries, cfg)
            self.assertEqual(unet_name(g), HYBRID_B30)

    def test_the_animate_lane_guards_are_not_reopened(self):
        """The chip is the lane switch (9.12): a ref2va-carrying chip is
        refused by i2v whether it arrives explicitly or as the fl slot's
        answer. The slot governs which build a lane defaults to; it does not
        retest the upstream keyframe/first-frame fences."""
        cfg = cfg_with({"ref_model": "", "fl_model": HYBRID_B30})
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            entries = h3_stack(root, builds=(STOCK, REF2VA, HYBRID_B30))
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config", return_value=cfg), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)), \
                 patch.object(server, "_video_asset",
                              side_effect=lambda kind, rel: rel):
                chip = next(o["id"] for o in server.h3_model_options()
                            if o["rel"] == HYBRID_B30)
                with self.assertRaisesRegex(ValueError, "ref2va build"):
                    server.build_h3_i2v("She turns.", 1, "prepared.png",
                                        seconds=5, width=1344, height=768,
                                        model=chip)
                with self.assertRaisesRegex(ValueError, "ref2va build"):
                    server.build_h3_i2v("She turns.", 1, "prepared.png",
                                        seconds=5, width=1344, height=768)


class StaleSlotTests(unittest.TestCase):
    """Accept 5: a pick whose file left the catalog degrades to the scan
    answer - nothing raises, and the condition is reported."""

    def test_a_stale_ref_slot_degrades_to_the_scan_answer(self):
        cfg = cfg_with({"ref_model": GONE, "fl_model": ""})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(REF2VA, HYBRID_B30))
            sidecar, roots = no_disk()
            with sidecar, roots, \
                 patch.object(server, "load_config", return_value=cfg), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)):
                self.assertEqual(server.h3_slot_choice("ref")["rel"], HYBRID_B30)
            rows = recipe_rows(entries, cfg)
            self.assertEqual(rows["h3_ref_still"]["default_model"], HYBRID_B30)
            g, _cap, _info = build_ref_still(entries, cfg)
            self.assertEqual(unet_name(g), HYBRID_B30)

    def test_the_settings_payload_reports_the_stale_pick(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(REF2VA, HYBRID_B30))
            with patch.object(server, "load_config",
                              return_value=full_cfg(
                                  {"ref_model": GONE, "fl_model": ""})), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)), \
                 patch.object(server, "_video_asset",
                              side_effect=lambda kind, rel: rel), \
                 patch.object(server, "refresh_comfy_nodes", AsyncMock()):
                response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        h3 = json.loads(response.text)["h3"]
        self.assertEqual(h3["ref_model"], GONE)     # the stored pick survives
        self.assertTrue(h3["ref"]["stale"])
        self.assertEqual(h3["ref"]["resolved"]["rel"], HYBRID_B30)
        self.assertFalse(h3["fl"]["stale"])


class ExplicitWinsTests(unittest.TestCase):
    """Accept 6: build_*(..., model=X) loads X. Always. A slot only ever
    answers "nothing was asked for"."""

    def test_an_explicit_ref_model_beats_the_slot(self):
        cfg = cfg_with({"ref_model": HYBRID_B30, "fl_model": ""})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(REF2VA, HYBRID_B30))
            g, _cap, _info = build_ref_still(entries, cfg, model=REF2VA)
            self.assertEqual(unet_name(g), REF2VA)

    def test_an_explicit_fl_model_beats_the_slot(self):
        cfg = cfg_with({"ref_model": "", "fl_model": HYBRID_B30})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, HYBRID_B30))
            g, _cap, _info = build_still(entries, cfg, model=STOCK)
            self.assertEqual(unet_name(g), STOCK)


class VideoSlotTests(unittest.TestCase):
    """The video builders' model=None default comes from the slot's chip."""

    def build_video(self, entries, cfg, lane="i2v", **kwargs):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "prepared.png").write_bytes(b"prepared")
            (root / "input" / "ref0.png").write_bytes(b"ref")
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config", return_value=cfg), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)), \
                 patch.object(server, "_video_asset",
                              side_effect=lambda kind, rel: rel):
                if lane == "i2v":
                    return server.build_h3_i2v(
                        "She turns.", 1, "prepared.png", seconds=5,
                        width=1344, height=768, **kwargs)
                if lane == "multishot":
                    return server.build_h3_multishot(
                        "One.\n---\nTwo.", 1, "prepared.png", seconds=5,
                        width=1344, height=768, **kwargs)
                return server.build_h3_ref2v(
                    "She browses the shelf.", 1, ["ref0.png"], seconds=5,
                    width=1344, height=768, **kwargs)

    def test_i2v_defaults_to_the_fl_slot(self):
        cfg = cfg_with({"ref_model": "", "fl_model": FL_FINETUNE})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, FL_FINETUNE))
            g, _brief, _info = self.build_video(entries, cfg)
            self.assertEqual(unet_name(g), FL_FINETUNE)

    def test_multishot_defaults_to_the_fl_slot(self):
        cfg = cfg_with({"ref_model": "", "fl_model": FL_FINETUNE})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, FL_FINETUNE))
            g, _brief, _info = self.build_video(entries, cfg, lane="multishot")
            self.assertEqual(unet_name(g), FL_FINETUNE)

    def test_ref2v_defaults_to_the_ref_slot(self):
        cfg = cfg_with({"ref_model": HYBRID_B30, "fl_model": ""})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA, HYBRID_B30))
            g, _brief, _info = self.build_video(entries, cfg, lane="ref2v")
            self.assertEqual(unet_name(g), HYBRID_B30)

    def test_an_explicit_chip_still_wins_in_the_video_lanes(self):
        cfg = cfg_with({"ref_model": "", "fl_model": FL_FINETUNE})
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, FL_FINETUNE))
            g, _brief, _info = self.build_video(entries, cfg, model="fl2va")
            self.assertEqual(unet_name(g), STOCK)


class AgreementTests(unittest.TestCase):
    """Accept 7: the loop that would have caught all three 2026-08-31
    instances. For every recipe with at least one runnable model, the model
    HUB.options reports equals the model the render lane resolves - under
    every slot state, not just the default."""

    STATES = {
        "both slots unset": {"ref_model": "", "fl_model": ""},
        "ref slot set to stock": {"ref_model": REF2VA, "fl_model": ""},
        "ref slot stale": {"ref_model": GONE, "fl_model": ""},
        "fl slot set to a hybrid": {"ref_model": "", "fl_model": HYBRID_B30},
    }

    def test_the_payload_and_the_render_lane_agree_everywhere(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            entries = (every_recipe_default(root)
                       + h3_stack(root, builds=(STOCK, REF2VA, FL_FINETUNE,
                                                REF_FINETUNE, HYBRID_B15,
                                                HYBRID_B20, HYBRID_B25,
                                                HYBRID_B30)))
            # h3_stack re-adds the shared assets; the diffusion entries are
            # what matter and the catalog stub dedupes nothing downstream.
            for name, h3 in self.STATES.items():
                with self.subTest(state=name):
                    cfg = cfg_with(h3)
                    rows = recipe_rows(entries, cfg)
                    sidecar, roots = no_disk()
                    with sidecar, roots, \
                         patch.object(server, "load_config", return_value=cfg), \
                         patch.object(server, "model_catalog",
                                      side_effect=stub_catalog(entries)):
                        for rid in server.RECIPE_SPECS:
                            runnable = [e["rel"] for e in
                                        server.recipe_model_candidates(rid)]
                            if not runnable:
                                continue
                            rendered = server.pick_recipe_model(
                                server.recipe_render_default(rid), rid)["rel"]
                            self.assertEqual(
                                rows[rid]["default_model"], rendered,
                                f"{rid} under '{name}': the payload names "
                                f"{rows[rid]['default_model']} while the "
                                f"render lane resolves {rendered}")


class SettingsEndpointTests(unittest.TestCase):
    """The payload carries both slots with candidates, the Automatic
    resolution and the stale flag; POST validates edit.model's contract."""

    def get_h3(self, entries, cfg):
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)), \
             patch.object(server, "_video_asset",
                          side_effect=lambda kind, rel: rel), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()):
            response = asyncio.run(server.settings_get(FakeRequest({})))
        self.assertEqual(response.status, 200)
        return json.loads(response.text)["h3"]

    def post_h3(self, entries, cfg, body, saved):
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)), \
             patch.object(server, "save_config",
                          side_effect=lambda c: saved.append(c)):
            return asyncio.run(server.settings_post(FakeRequest(body)))

    def test_the_payload_carries_both_slots(self):
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA, HYBRID_B30))
            h3 = self.get_h3(entries, full_cfg())
        self.assertEqual(h3["ref_model"], "")
        self.assertEqual(h3["fl_model"], "")
        self.assertEqual([o["rel"] for o in h3["ref"]["options"]],
                         [REF2VA, HYBRID_B30])
        self.assertEqual([o["rel"] for o in h3["fl"]["options"]],
                         [STOCK, HYBRID_B30])
        # Automatic never hides the actual answer
        self.assertEqual(h3["ref"]["resolved"]["rel"], HYBRID_B30)
        self.assertEqual(h3["fl"]["resolved"]["rel"], STOCK)
        self.assertFalse(h3["ref"]["stale"])
        self.assertFalse(h3["fl"]["stale"])

    def test_a_pick_round_trips(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA, HYBRID_B30))
            cfg = full_cfg()
            response = self.post_h3(entries, cfg,
                                    {"h3": {"ref_model": HYBRID_B30}}, saved)
            self.assertEqual(response.status, 200)
            self.assertEqual(saved[0]["h3"]["ref_model"], HYBRID_B30)

    def test_the_same_hybrid_is_legal_in_both_slots(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA, HYBRID_B30))
            cfg = full_cfg()
            response = self.post_h3(entries, cfg,
                                    {"h3": {"ref_model": HYBRID_B30,
                                            "fl_model": HYBRID_B30}}, saved)
            self.assertEqual(response.status, 200)
            self.assertEqual(saved[0]["h3"]["fl_model"], HYBRID_B30)
            self.assertEqual(saved[0]["h3"]["ref_model"], HYBRID_B30)

    def test_an_empty_pick_clears_back_to_automatic(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA))
            cfg = full_cfg({"ref_model": REF2VA, "fl_model": STOCK})
            response = self.post_h3(entries, cfg,
                                    {"h3": {"ref_model": ""}}, saved)
            self.assertEqual(response.status, 200)
            self.assertEqual(saved[0]["h3"]["ref_model"], "")
            self.assertEqual(saved[0]["h3"]["fl_model"], STOCK)

    def test_a_pure_fl2va_pick_in_the_ref_slot_is_refused(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA))
            cfg = full_cfg()
            response = self.post_h3(entries, cfg,
                                    {"h3": {"ref_model": STOCK}}, saved)
            self.assertEqual(response.status, 400)
            self.assertIn(STOCK, json.loads(response.text)["error"])
            self.assertEqual(saved, [])     # a rejected write never touches config

    def test_an_uninstalled_pick_is_refused_naming_the_file(self):
        saved = []
        with TemporaryDirectory() as td:
            entries = h3_stack(Path(td), builds=(STOCK, REF2VA))
            cfg = full_cfg()
            response = self.post_h3(entries, cfg,
                                    {"h3": {"ref_model": GONE}}, saved)
            self.assertEqual(response.status, 400)
            self.assertIn(GONE, json.loads(response.text)["error"])
            self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
