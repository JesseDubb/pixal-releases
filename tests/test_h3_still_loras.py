"""Brief 9.74 - MiniMax H3 LoRAs on the H3 still lanes.

Known since 9.58: the three still rows declared `lora_stages: []` and their
builders accepted loras/lora_plan only to drop them, while `lora_profile`
could never classify minimax_h3 at all (the family is deliberately not a
families.json row - its transformers are media "video", which a row cannot
say - so the table walk had no row to reach). Every H3 LoRA filed unknown,
the add-LoRA popup greyed the whole shelf, and Jesse's style LoRAs in
models/loras/Minimax H3/ were unpickable on h3 image gen.

The change, in four pieces: lora_profile classifies the family by the same
elif pattern model_profile uses (a declared base naming MiniMax H3, else the
Minimax H3 folder), with variant "speed" for the turbo/lightx2v/step-count
distills and "any" for everything else; lora_compatible refuses "variant"
when a still profile (fl2va/ref2va) meets a non-"any" LoRA, so the speed
distills stay the Animate lanes' speed-mode property; the three still rows
declare lora_variants ["any"] and four editable style stages at revision 3;
and the builders resolve the plan and chain LoraLoaderModelOnly nodes off
the loader, BOTH consumers (BasicScheduler "8" and BasicGuider "9", plus the
2x refine's up:sigmas/up:sample) seeing the identical literal tail.

What these tests pin:

  Classification - every file in the on-disk Minimax H3 folder files as
                   family minimax_h3, supported, with the right variant; a
                   sidecar/by-hash base naming MiniMax H3 classifies from
                   ANY folder; an unrelated LoRA is untouched.
  Gate         - style LoRAs are compatible on the fl2va/ref2va profiles,
                   speed distills are refused "variant" on them and stay
                   supported for the video lane (the speed ladder still
                   names them); compatible_recipes names the three still
                   rows for a style LoRA and none for a distill.
  RecipeRows   - lora_variants ["any"], revision 3, and FOUR editable,
                   removable, off-by-default style stages on each still
                   row - the 1.1.4b reference-realism trio joined the
                   pinned one.
  Stack        - resolve_recipe_lora_stack keeps a style LoRA, drops a
                   distill with the "incompatible" warning, and an empty
                   plan resolves to an empty chain.
  Graph        - all three builders chain LoraLoaderModelOnly off "1" and
                   point BOTH consumers at the tail (the 2x refine's
                   up:sigmas/up:sample included); info reports the stack
                   for the gallery; an empty plan renders the byte-identical
                   pre-9.74 graph.
  Options      - /api/options ships the LoRAs classified, the still rows in
                   each style LoRA's compatible_recipes, the distill's
                   refusal in its incompatible map, and the recipe rows'
                   new stages at revision 3, each with whether it is
                   installed.

Same sanctioned simulation as every sibling file: stubbed catalog, no
generation, no ComfyUI, no GPU.
"""

import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location(
    "pixal_server_h3_still_loras", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

STOCK = server.H3_MODEL
REF2VA = server.H3_REF2V_MODEL
UPSCALER = server.H3_LATENT_UPSCALER

STYLE = server.H3_HMNSFW_LORA                       # the pinned style stage
STYLE2 = "Minimax H3\\NaughtyTimes_pruned_r256_v2.safetensors"
DISTILL = server.H3_TURBO_LORA                      # the legacy turbo_v4 row
# The folder as it sits on this box (brief 9.74): six style/motion LoRAs and
# the four speed distills.
STYLE_LORAS = (
    "Minimax H3\\HMNSFW_AIO_V2.safetensors",
    "Minimax H3\\NSGIRL-MiniMax-H3-LoRA-By-MM744.safetensors",
    "Minimax H3\\NaughtyTimes_pruned_r256_v2.safetensors",
    "Minimax H3\\SexGod-NaughtyTimes-v2-rank256.safetensors",
    "Minimax H3\\mvmt_h3_lora_v1_500.safetensors",
    # motion-only, offered on the stills for the user to decide (variant any)
    "Minimax H3\\Motion_Repair.safetensors",
)
SPEED_LORAS = (
    "Minimax H3\\minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors",
    "Minimax H3\\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
    "Minimax H3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
    "Minimax H3\\minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors",
)

CHARACTER = {"id": "mia", "name": "Mia", "age": 24, "race": "Korean",
             "sex": "female", "style": "silver pixie cut, lean runner's build",
             "identity_ref": "mia.png"}


def h3_entries(root, *, loras=True, upscale=False):
    """The H3 stack as catalog entries: both stock builds, the shared
    encoder, both VAEs, and the LoRA folder when the test wants it."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    entries = [add("diffusion_models", STOCK),
               add("diffusion_models", REF2VA),
               add("text_encoders", server.H3_CLIP),
               add("vae", server.H3_VIDEO_VAE),
               add("vae", server.H3_AUDIO_VAE)]
    if loras:
        entries += [add("loras", rel) for rel in STYLE_LORAS + SPEED_LORAS]
    if upscale:
        entries.append(add("latent_upscale_models", UPSCALER, 659))
    return entries


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def anchored(root, character=CHARACTER):
    """A temp ComfyUI dir whose input/ holds the anchor's reference photo."""
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / character["identity_ref"]).write_bytes(b"reference")
    return (patch.object(server, "CDIR", root),
            patch.object(server, "CHARACTERS", {character["id"]: character}))


def plan(recipe, entries):
    return {"version": 1, "mode": "replace_editable", "recipe": recipe,
            "recipe_revision": server.RECIPE_SPECS[recipe]["lora_stack_revision"],
            "entries": entries}


def build(builder, entries=None, character=None, **kwargs):
    """Run one still builder on the stub catalog. h3_ref_still additionally
    gets the anchored temp CDIR; every builder gets the no-disk metadata
    stubs the sibling files use."""
    with TemporaryDirectory() as td:
        root = Path(td)
        entries = h3_entries(root, upscale=(builder is server.build_h3_still_2x)) \
            if entries is None else entries
        patches = list(no_disk()) + [
            patch.object(server, "model_catalog",
                         side_effect=stub_catalog(entries))]
        if builder is server.build_h3_ref_still:
            cdir, chars = anchored(root)
            patches += [cdir, chars]
            kwargs.setdefault("character", character or "mia")
        else:
            (root / "input").mkdir(exist_ok=True)
        for p in patches:
            p.start()
        try:
            return builder("A red barn at dusk", 424242, **kwargs)
        finally:
            for p in patches:
                p.stop()


class ClassificationTests(unittest.TestCase):
    """lora_profile files the whole Minimax H3 folder; nothing else moves."""

    def profile(self, rel, sidecar_md=None):
        sidecar, roots = no_disk()
        md = patch.object(server, "adjacent_metadata",
                          return_value=sidecar_md or {})
        with md, roots:
            return server.lora_profile(rel)

    def test_every_style_lora_is_a_supported_minimax_h3_any(self):
        for rel in STYLE_LORAS:
            with self.subTest(lora=rel):
                profile = self.profile(rel)
                self.assertEqual((profile["family"], profile["variant"]),
                                 ("minimax_h3", "any"))
                self.assertTrue(profile["supported"])

    def test_every_speed_distill_is_a_supported_minimax_h3_speed(self):
        for rel in SPEED_LORAS:
            with self.subTest(lora=rel):
                profile = self.profile(rel)
                self.assertEqual((profile["family"], profile["variant"]),
                                 ("minimax_h3", "speed"))
                self.assertTrue(profile["supported"])

    def test_a_sidecar_declared_base_classifies_from_any_folder(self):
        # The folder hint is rank 4 of 4: a CivitAI download landing anywhere
        # else still files by what it declares. CivitAI's baseModel for every
        # H3 file in this box's by-hash cache is exactly "MiniMax H3".
        profile = self.profile("Downloads\\nsgirl.safetensors",
                               {"base_model": "MiniMax H3"})
        self.assertEqual((profile["family"], profile["variant"]),
                         ("minimax_h3", "any"))
        self.assertTrue(profile["supported"])
        self.assertEqual(profile["base_model"], "MiniMax H3")

    def test_a_by_hash_declared_base_classifies_from_any_folder(self):
        sidecar, roots = no_disk()
        with sidecar, roots, patch.dict(
                server.BY_HASH_BASE_MODEL,
                {"downloads\\nsgirl.safetensors": "MiniMax H3"}):
            profile = server.lora_profile("Downloads\\nsgirl.safetensors")
        self.assertEqual((profile["family"], profile["variant"]),
                         ("minimax_h3", "any"))
        self.assertTrue(profile["supported"])

    def test_the_declared_base_wins_over_the_folder(self):
        # A krea2 LoRA misfiled into the Minimax H3 folder keeps its declared
        # family - the folder is the least trustworthy hint (9.19a's order).
        profile = self.profile("Minimax H3\\stray.safetensors",
                               {"base_model": "krea2"})
        self.assertEqual(profile["family"], "krea2")

    def test_an_unrelated_lora_stays_unknown(self):
        profile = self.profile("random\\whatever.safetensors")
        self.assertEqual((profile["family"], profile["supported"]),
                         ("unknown", False))

    def test_a_krea2_lora_still_files_krea2(self):
        profile = self.profile("Krea 2\\whatever.safetensors")
        self.assertEqual(profile["family"], "krea2")


class GateTests(unittest.TestCase):
    """The still profiles take style LoRAs and refuse the speed distills."""

    def test_a_style_lora_is_compatible_on_the_still_profiles(self):
        sidecar, roots = no_disk()
        with sidecar, roots:
            self.assertIsNone(server.lora_compatible(STYLE, "minimax_h3",
                                                     "fl2va"))
            self.assertIsNone(server.lora_compatible(STYLE, "minimax_h3",
                                                     "ref2va"))

    def test_every_distill_is_refused_on_the_still_profiles(self):
        sidecar, roots = no_disk()
        with sidecar, roots:
            for rel in SPEED_LORAS:
                with self.subTest(lora=rel):
                    self.assertEqual(
                        server.lora_compatible(rel, "minimax_h3", "fl2va"),
                        "variant")
                    self.assertEqual(
                        server.lora_compatible(rel, "minimax_h3", "ref2va"),
                        "variant")

    def test_the_distills_stay_accepted_for_the_video_lane(self):
        # The Animate lanes never read lora_compatible - their distills ride
        # H3_SPEED_MODES by explicit filename, and the classification keeps
        # them supported minimax_h3 LoRAs. No asked variant, no gate.
        sidecar, roots = no_disk()
        with sidecar, roots:
            for rel in SPEED_LORAS:
                with self.subTest(lora=rel):
                    self.assertIsNone(
                        server.lora_compatible(rel, "minimax_h3", None))
        ladder = {m["id"]: m["lora"] for m in server.H3_SPEED_MODES
                  if m["lora"]}
        self.assertIn(SPEED_LORAS[1], ladder.values())    # turbo4
        self.assertIn(SPEED_LORAS[2], ladder.values())    # turbo8
        self.assertIn(SPEED_LORAS[3], ladder.values())    # turbo_v4

    def test_other_families_and_unknowns_are_still_refused(self):
        sidecar, roots = no_disk()
        with sidecar, roots:
            self.assertEqual(
                server.lora_compatible("Krea 2\\whatever.safetensors",
                                       "minimax_h3", "fl2va"),
                "family")
            self.assertEqual(
                server.lora_compatible("random\\whatever.safetensors",
                                       "minimax_h3", "fl2va"),
                "unknown")

    def test_compatible_recipes_splits_the_shelf_by_lora_variant(self):
        sidecar, roots = no_disk()
        with sidecar, roots:
            self.assertEqual(
                server.compatible_recipes(server.lora_profile(STYLE)),
                ["h3_still", "h3_still_2x", "h3_ref_still",
                 "h3_ref_still_2x"])
            self.assertEqual(
                server.compatible_recipes(server.lora_profile(DISTILL)), [])

    def test_the_popup_key_space_still_covers_minimax_h3(self):
        self.assertIn("minimax_h3:any", server._LORA_PROFILE_KEYS)
        self.assertIn("minimax_h3:fl2va", server._LORA_PROFILE_KEYS)
        self.assertIn("minimax_h3:ref2va", server._LORA_PROFILE_KEYS)


class RecipeRowTests(unittest.TestCase):
    """Each still row: lora_variants ["any"], revision 2, one editable stage."""

    def test_the_still_rows_carry_the_lane(self):
        # 1.1.4b: the lane went from one row to four at revision 3. The three
        # new ones are the LoRAs the 2026-08-30 reference session settled on,
        # pinned at 0.2 - the stack strength, not any one of their solo picks.
        wanted = [("style", STYLE, 1.0),
                  ("digicam", server.H3_DIGICAM_LORA, 0.2),
                  ("galaxyace", server.H3_GALAXYACE_LORA, 0.2),
                  ("relim", server.H3_RELIM_LORA, 0.2)]
        for rid in ("h3_still", "h3_still_2x", "h3_ref_still",
                    "h3_ref_still_2x"):
            with self.subTest(recipe=rid):
                spec = server.RECIPE_SPECS[rid]
                self.assertEqual(spec["lora_variants"], ["any"])
                self.assertEqual(spec["lora_stack_revision"], 3)
                self.assertEqual(spec["lora_boundary"], "sampler")
                self.assertEqual(
                    [(s["slot"], s["name"], s["strength"])
                     for s in spec["lora_stages"]], wanted)
                for stage in spec["lora_stages"]:
                    # realism's editable-row shape: a style role in the
                    # editable zone, order unlocked, strength open, removable
                    # - and every one OFF by default, so an untouched plan
                    # still renders the pre-9.74 graph.
                    self.assertEqual(stage["role"], "style")
                    self.assertEqual(stage["zone"], "editable")
                    self.assertFalse(stage["order_locked"])
                    self.assertTrue(stage["strength_editable"])
                    self.assertTrue(stage["removable"])
                    self.assertFalse(stage["active_by_default"])
                # No core entries: the lane is the whole stack.
                self.assertEqual(
                    [s for s in spec["lora_stages"] if s["zone"] == "core"],
                    [])

    def test_a_plan_against_revision_1_is_refused(self):
        stale = plan("h3_still", [])
        stale["recipe_revision"] = 1
        with self.assertRaisesRegex(ValueError, "LoRA stack changed"):
            server.validate_lora_plan("h3_still", stale)


class StackTests(unittest.TestCase):
    """resolve_recipe_lora_stack: style kept, distill dropped, empty is empty."""

    def resolve(self, recipe="h3_still", loras=(), lora_plan=None):
        sidecar, roots = no_disk()
        with TemporaryDirectory() as td:
            with sidecar, roots, patch.object(
                    server, "model_catalog",
                    side_effect=stub_catalog(h3_entries(Path(td)))):
                return server.resolve_recipe_lora_stack(
                    recipe, loras, lora_plan,
                    family="minimax_h3", variant="fl2va")

    def test_an_empty_plan_resolves_to_an_empty_chain(self):
        entries, dropped = self.resolve(lora_plan=plan("h3_still", []))
        self.assertEqual(entries, [])
        self.assertEqual(dropped, [])

    def test_no_plan_and_no_loras_is_also_empty(self):
        entries, dropped = self.resolve()
        self.assertEqual(entries, [])
        self.assertEqual(dropped, [])

    def test_a_style_lora_by_name_is_kept_in_order(self):
        entries, dropped = self.resolve(lora_plan=plan("h3_still", [
            {"name": STYLE2, "strength": 0.9},
            {"name": STYLE, "strength": 0.6}]))
        self.assertEqual(dropped, [])
        self.assertEqual([(e["name"], e["strength"]) for e in entries],
                         [(STYLE2, 0.9), (STYLE, 0.6)])
        for entry in entries:
            self.assertEqual((entry["role"], entry["zone"], entry["source"]),
                             ("style", "editable", "user"))

    def test_a_distill_is_dropped_with_the_incompatible_warning(self):
        entries, dropped = self.resolve(lora_plan=plan("h3_still", [
            {"name": DISTILL, "strength": 1.0}]))
        self.assertEqual(entries, [])
        self.assertEqual(dropped, ["incompatible " + server.base(DISTILL)])

    def test_the_recipe_slot_resolves_the_pinned_style_stage(self):
        entries, dropped = self.resolve(lora_plan=plan("h3_still", [
            {"slot": "style", "strength": 0.7}]))
        self.assertEqual(dropped, [])
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual((entry["slot"], entry["name"], entry["strength"]),
                         ("style", STYLE, 0.7))
        self.assertEqual(entry["source"], "recipe")

    def test_the_legacy_loras_list_rides_the_same_gate(self):
        entries, dropped = self.resolve(loras=[STYLE2 + ":0.8",
                                               DISTILL + ":1.0"])
        self.assertEqual([(e["name"], e["strength"]) for e in entries],
                         [(STYLE2, 0.8)])
        self.assertEqual(dropped, ["incompatible " + server.base(DISTILL)])


class GraphTests(unittest.TestCase):
    """The chain: LoraLoaderModelOnly off "1", both consumers on the tail."""

    def assert_chain(self, g, info, expected):
        ids = sorted(nid for nid in g if nid.startswith("h3:lora"))
        self.assertEqual(ids, [f"h3:lora{i}" for i in range(len(expected))])
        tail = "1"
        for nid, (rel, strength) in zip(ids, expected):
            node = g[nid]
            self.assertEqual(node["class_type"], "LoraLoaderModelOnly")
            self.assertEqual(node["inputs"], {"lora_name": rel,
                                              "strength_model": strength,
                                              "model": [tail, 0]})
            tail = nid
        # Both consumers must see the identical literal chain.
        self.assertEqual(g["8"]["inputs"]["model"], [tail, 0])
        self.assertEqual(g["9"]["inputs"]["model"], [tail, 0])
        return tail

    def test_h3_still_chains_the_plan_and_reports_it(self):
        g, _cap, info = build(
            server.build_h3_still,
            lora_plan=plan("h3_still", [{"name": STYLE, "strength": 0.9}]))
        self.assert_chain(g, info, [(STYLE, 0.9)])
        self.assertEqual(info["loras"], ["HMNSFW_AIO_V2@0.9"])
        self.assertEqual(info["lora_warnings"], [])
        self.assertEqual([(e["name"], e["strength"], e["zone"])
                          for e in info["lora_stack"]],
                         [(STYLE, 0.9, "editable")])
        server.validate_job_model_info("h3_still", info, g)

    def test_h3_still_two_loras_chain_in_literal_order(self):
        g, _cap, info = build(
            server.build_h3_still,
            lora_plan=plan("h3_still", [{"name": STYLE2, "strength": 0.9},
                                        {"name": STYLE, "strength": 0.6}]))
        self.assert_chain(g, info, [(STYLE2, 0.9), (STYLE, 0.6)])

    def test_h3_still_drops_a_distill_and_says_so(self):
        g, _cap, info = build(
            server.build_h3_still,
            lora_plan=plan("h3_still", [{"name": DISTILL, "strength": 1.0}]))
        self.assertNotIn("h3:lora0", g)
        self.assertEqual(g["8"]["inputs"]["model"], ["1", 0])
        self.assertEqual(g["9"]["inputs"]["model"], ["1", 0])
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_warnings"],
                         ["incompatible " + server.base(DISTILL)])

    def test_h3_still_2x_refine_follows_the_same_tail(self):
        g, _cap, info = build(
            server.build_h3_still_2x,
            lora_plan=plan("h3_still_2x", [{"name": STYLE, "strength": 0.9}]))
        tail = self.assert_chain(g, info, [(STYLE, 0.9)])
        self.assertEqual(g["up:sigmas"]["inputs"]["model"], [tail, 0])
        self.assertEqual(g["up:sample"]["inputs"]["model"], [tail, 0])
        self.assertEqual(info["loras"], ["HMNSFW_AIO_V2@0.9"])
        server.validate_job_model_info("h3_still_2x", info, g)

    def test_h3_ref_still_chains_the_plan_and_reports_it(self):
        g, _cap, info = build(
            server.build_h3_ref_still,
            lora_plan=plan("h3_ref_still", [{"name": STYLE, "strength": 0.9}]))
        self.assert_chain(g, info, [(STYLE, 0.9)])
        self.assertEqual(info["loras"], ["HMNSFW_AIO_V2@0.9"])
        self.assertEqual(info["lora_warnings"], [])
        server.validate_job_model_info("h3_ref_still", info, g)

    def test_h3_ref_still_refuses_a_distill(self):
        g, _cap, info = build(
            server.build_h3_ref_still,
            lora_plan=plan("h3_ref_still", [{"name": DISTILL, "strength": 1.0}]))
        self.assertNotIn("h3:lora0", g)
        self.assertEqual(info["lora_warnings"],
                         ["incompatible " + server.base(DISTILL)])

    def test_an_empty_plan_is_byte_identical_to_no_plan(self):
        for builder, rid in ((server.build_h3_still, "h3_still"),
                             (server.build_h3_still_2x, "h3_still_2x"),
                             (server.build_h3_ref_still, "h3_ref_still")):
            with self.subTest(recipe=rid):
                plain = build(builder)
                empty = build(builder, lora_plan=plan(rid, []))
                self.assertEqual(empty, plain)

    def test_the_empty_graph_is_the_pre_9_74_snapshot(self):
        # The snapshot captured by 9.59's suite: no lora nodes, raw "1".
        snap = json.loads((ROOT / "tests" / "snapshots" /
                           "h3_still_graph.json").read_text(encoding="utf-8"))
        g, cap, _info = build(server.build_h3_still,
                              lora_plan=plan("h3_still", []))
        self.assertEqual(cap, snap["caption"])
        self.assertEqual(g, snap["graph"])


class OptionsTests(unittest.TestCase):
    """/api/options: the shelf classifies, the rows ship the lane."""

    def options(self, entries):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(entries)), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE",
                              root / "titles.json"):
                return server.Hub().options()

    def test_the_shelf_classifies_the_folder(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        loras = {l["name"]: l for l in options["loras"]}
        for rel in STYLE_LORAS:
            entry = loras[rel]
            self.assertEqual((entry["family"], entry["variant"]),
                             ("minimax_h3", "any"), rel)
            self.assertTrue(entry["supported"], rel)
        for rel in SPEED_LORAS:
            entry = loras[rel]
            self.assertEqual((entry["family"], entry["variant"]),
                             ("minimax_h3", "speed"), rel)

    def test_the_still_rows_appear_in_a_style_loras_compatible_recipes(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        loras = {l["name"]: l for l in options["loras"]}
        self.assertEqual(loras[STYLE]["compatible_recipes"],
                         ["h3_still", "h3_still_2x", "h3_ref_still",
                          "h3_ref_still_2x"])
        for rel in SPEED_LORAS:
            self.assertEqual(loras[rel]["compatible_recipes"], [], rel)

    def test_the_incompatible_map_carries_the_pickers_verdicts(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        loras = {l["name"]: l for l in options["loras"]}
        # Style: no refusal under any minimax_h3 key - the popup renders it
        # pickable on all three still profiles.
        style_verdicts = {k: v for k, v in loras[STYLE]["incompatible"].items()
                          if k.startswith("minimax_h3:")}
        self.assertEqual(style_verdicts, {})
        # Distill: greyed on both still profiles with the variant reason.
        for rel in SPEED_LORAS:
            inc = loras[rel]["incompatible"]
            self.assertEqual(inc.get("minimax_h3:fl2va"), "variant", rel)
            self.assertEqual(inc.get("minimax_h3:ref2va"), "variant", rel)

    def test_the_recipe_rows_ship_the_lane_at_revision_3(self):
        with TemporaryDirectory() as td:
            options = self.options(h3_entries(Path(td)))
        recipes = {r["id"]: r for r in options["recipes"]}
        for rid in ("h3_still", "h3_still_2x", "h3_ref_still",
                    "h3_ref_still_2x"):
            recipe = recipes[rid]
            self.assertEqual(recipe["lora_stack_revision"], 3, rid)
            self.assertEqual(recipe["lora_boundary"], "sampler", rid)
            self.assertEqual(
                [(s["slot"], s["name"], s["zone"])
                 for s in recipe["lora_stages"]],
                [("style", STYLE, "editable"),
                 ("digicam", server.H3_DIGICAM_LORA, "editable"),
                 ("galaxyace", server.H3_GALAXYACE_LORA, "editable"),
                 ("relim", server.H3_RELIM_LORA, "editable")], rid)
            # The stub catalog holds the pinned style file and none of the
            # three new ones, which is the point of publishing `installed`:
            # a row for a LoRA that is not on this box shows as unavailable
            # rather than failing at render time.
            self.assertTrue(recipe["lora_stages"][0]["installed"], rid)
            for stage in recipe["lora_stages"][1:]:
                self.assertFalse(stage["installed"], rid)


if __name__ == "__main__":
    unittest.main()
