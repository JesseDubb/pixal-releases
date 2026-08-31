"""Brief 9.86 - the Klein edit lane takes LoRAs.

~30 Klein LoRAs sit in models/loras/Flux/ and the whole-frame edit lane
could reach none of them: build_klein_edit's signature had no loras/
lora_plan, and SIGS is computed from the signature, so submit filtered the
stack out before it could ever arrive. The recipe row already declared the
lane (`lora_stack_revision: 1, lora_boundary: "sampler", lora_stages: []`)
and lora_profile already classified the klein family - one signature was
the whole block.

The change copies the sibling, it does not invent a second mechanism:
build_klein_edit takes loras=()/lora_plan=None and resolves them through
resolve_recipe_lora_stack exactly like build_qwen_edit, chaining
LoraLoaderModelOnly between ke:unet and ke:guider - the ONLY model consumer
in this graph. ke:sched (Flux2Scheduler) takes steps/width/height and NO
model; handing it the tail is a TypeError at execution, and that is the
trap these tests pin shut. The recipe row gains ONE editable, removable,
off-by-default detail stage pinning the measured Enhanced-Details LoRA at
0.8, and lora_stack_revision goes 1 -> 2 (the 9.74 contract: revision-1
plans are refused, not replayed against a different stage list).

What these tests pin:

  RecipeRow  - revision 2, ONE editable detail stage at 0.8, off by
               default; a revision-1 plan is refused by name.
  Stack      - the empty stack is empty; a legacy name and a plan slot
               resolve; a non-klein LoRA and a hallucinated name are
               refused BY NAME, the qwen lane's way; activating the slot
               without the file raises "requires LoRA: <name>".
  Graph      - a stacked LoRA chains ke:unet -> ke:loraN -> ke:guider and
               ke:sched keeps NO model input; two LoRAs chain in plan
               order; a disabled stage adds nothing; SIGS names loras and
               lora_plan; the untouched plan renders the byte-identical
               pre-9.86 graph (snapshot captured from the pre-change
               builder) and equals an explicit empty plan.
  Options    - /api/options ships the stage annotated installed, the flag
               the popup's gate reads.
  Popup gate - static, in the style of test_lora_card_controls.py (this
               repo has no JS runner): the add-popup's recipe-stage rows
               are filtered on `installed`, so a row naming a file the
               user does not have is never offered.

Same sanctioned simulation as every sibling file: stubbed catalog, no
generation, no ComfyUI, no GPU.
"""

import json
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location(
    "pixal_server_klein_edit_loras", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

COMPOSER = (ROOT / "web" / "src" / "components" /
            "Composer.jsx").read_text(encoding="utf-8")

DETAIL = server.KLEIN_DETAIL_LORA                 # the pinned detail stage
STYLE2 = "Flux\\Realism_Engine_Klein_V1.safetensors"
FOREIGN = "Krea 2\\lenovo_krea2.safetensors"      # a krea2 LoRA, by folder


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


def plan(recipe, entries):
    return {"version": 1, "mode": "replace_editable", "recipe": recipe,
            "recipe_revision": server.RECIPE_SPECS[recipe]["lora_stack_revision"],
            "entries": entries}


def klein_entries(root, *, loras=True):
    """The Klein lane as catalog entries: the build, its encoder and VAE,
    and the Flux LoRA folder when the test wants it."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    entries = [add("diffusion_models", server.KLEIN_MODEL),
               add("text_encoders", server.KLEIN_CLIP),
               add("vae", server.KLEIN_VAE)]
    if loras:
        entries += [add("loras", rel) for rel in (DETAIL, STYLE2, FOREIGN)]
    return entries


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def build(entries=None, size=(1232, 1648), **kwargs):
    """Run build_klein_edit on the stub catalog with a real source PNG, the
    same harness KleinEditTests uses, plus the LoRA catalog the stack
    resolution reads."""
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        from PIL import Image
        Image.new("RGB", size, (9, 9, 9)).save(root / "input" / "s.png")
        entries = klein_entries(root) if entries is None else entries
        sidecar, roots = no_disk()
        with patch.object(server, "CDIR", root), sidecar, roots, \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(entries)), \
             patch.object(server, "pick_recipe_model",
                          return_value=model(server.KLEIN_MODEL, "klein", "edit")), \
             patch.object(server, "_pick_catalog_asset",
                          side_effect=lambda kind, names, *a: names[0]):
            return server.build_klein_edit("remove her earrings", 5, "s.png",
                                           **kwargs)


class RecipeRowTests(unittest.TestCase):
    """The klein_edit row: revision 2, ONE editable, off-by-default stage."""

    def test_the_row_carries_the_lane(self):
        spec = server.RECIPE_SPECS["klein_edit"]
        self.assertEqual(spec["lora_stack_revision"], 2)
        self.assertEqual(spec["lora_boundary"], "sampler")
        self.assertEqual(len(spec["lora_stages"]), 1)
        stage = spec["lora_stages"][0]
        # h3_still's editable-row shape: a detail role in the editable zone,
        # order unlocked, strength open, removable - and OFF by default, so
        # an untouched plan renders the pre-9.86 graph.
        self.assertEqual((stage["slot"], stage["name"], stage["strength"]),
                         ("detail", DETAIL, 0.8))
        self.assertEqual(stage["role"], "detail")
        self.assertEqual(stage["zone"], "editable")
        self.assertFalse(stage["order_locked"])
        self.assertTrue(stage["strength_editable"])
        self.assertTrue(stage["removable"])
        self.assertFalse(stage["active_by_default"])
        # No core entries: the editable lane is the whole stack.
        self.assertEqual(
            [s for s in spec["lora_stages"] if s["zone"] == "core"], [])

    def test_a_plan_against_revision_1_is_refused(self):
        stale = plan("klein_edit", [])
        stale["recipe_revision"] = 1
        with self.assertRaisesRegex(ValueError, "LoRA stack changed"):
            server.validate_lora_plan("klein_edit", stale)


class StackTests(unittest.TestCase):
    """resolve_recipe_lora_stack on the klein family gate."""

    def resolve(self, loras=(), lora_plan=None, entries=None):
        with TemporaryDirectory() as td:
            sidecar, roots = no_disk()
            entries = klein_entries(Path(td)) if entries is None else entries
            with sidecar, roots, patch.object(
                    server, "model_catalog",
                    side_effect=stub_catalog(entries)):
                return server.resolve_recipe_lora_stack(
                    "klein_edit", loras, lora_plan, family="klein")

    def test_no_plan_and_no_loras_is_empty(self):
        entries, dropped = self.resolve()
        self.assertEqual(entries, [])
        self.assertEqual(dropped, [])

    def test_an_empty_plan_resolves_to_an_empty_chain(self):
        entries, dropped = self.resolve(lora_plan=plan("klein_edit", []))
        self.assertEqual(entries, [])
        self.assertEqual(dropped, [])

    def test_the_detail_lora_classifies_klein(self):
        sidecar, roots = no_disk()
        with sidecar, roots:
            profile = server.lora_profile(DETAIL)
        self.assertEqual((profile["family"], profile["variant"]),
                         ("klein", "any"))
        self.assertTrue(profile["supported"])

    def test_the_recipe_slot_resolves_the_pinned_detail_stage(self):
        entries, dropped = self.resolve(lora_plan=plan("klein_edit", [
            {"slot": "detail", "strength": 0.8}]))
        self.assertEqual(dropped, [])
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual((entry["slot"], entry["name"], entry["strength"]),
                         ("detail", DETAIL, 0.8))
        self.assertEqual((entry["role"], entry["zone"], entry["source"]),
                         ("detail", "editable", "recipe"))

    def test_a_klein_lora_by_name_is_kept_in_order(self):
        entries, dropped = self.resolve(lora_plan=plan("klein_edit", [
            {"name": STYLE2, "strength": 0.9},
            {"slot": "detail", "strength": 0.6}]))
        self.assertEqual(dropped, [])
        self.assertEqual([(e["name"], e["strength"]) for e in entries],
                         [(STYLE2, 0.9), (DETAIL, 0.6)])

    def test_a_foreign_lora_is_refused_by_name(self):
        """The qwen lane's refusal, not a silent drop: the warning names the
        LoRA so the lane line can say what never reached the graph."""
        entries, dropped = self.resolve(lora_plan=plan("klein_edit", [
            {"name": FOREIGN, "strength": 1.0}]))
        self.assertEqual(entries, [])
        self.assertEqual(dropped, ["incompatible " + server.base(FOREIGN)])

    def test_a_hallucinated_name_is_refused_by_name(self):
        entries, dropped = self.resolve(lora_plan=plan("klein_edit", [
            {"name": "Flux\\ghost.safetensors", "strength": 1.0}]))
        self.assertEqual(entries, [])
        self.assertEqual(dropped, ["ghost"])

    def test_the_legacy_loras_list_rides_the_same_gate(self):
        entries, dropped = self.resolve(loras=[STYLE2 + ":0.7",
                                               FOREIGN + ":1.0"])
        self.assertEqual([(e["name"], e["strength"]) for e in entries],
                         [(STYLE2, 0.7)])
        self.assertEqual(dropped, ["incompatible " + server.base(FOREIGN)])

    def test_activating_the_slot_without_the_file_raises_its_name(self):
        """The gate keeps the row off the popup, but a hand-written plan can
        still name the stage - that fails honestly, by file name, the way
        _pick_catalog_asset reports any other missing asset."""
        with TemporaryDirectory() as td:
            root = Path(td)
            sidecar, roots = no_disk()
            with sidecar, roots, patch.object(
                    server, "model_catalog",
                    side_effect=stub_catalog(klein_entries(root, loras=False))):
                with self.assertRaisesRegex(
                        ValueError,
                        re.escape(f"Klein Edit requires LoRA: {DETAIL}")):
                    server.resolve_recipe_lora_stack(
                        "klein_edit", (),
                        plan("klein_edit", [{"slot": "detail"}]),
                        family="klein")


class GraphTests(unittest.TestCase):
    """The chain: LoraLoaderModelOnly off ke:unet, ke:guider on the tail."""

    def assert_chain(self, g, expected):
        ids = sorted(nid for nid in g if nid.startswith("ke:lora"))
        self.assertEqual(ids, [f"ke:lora{i}" for i in range(len(expected))])
        tail = "ke:unet"
        for nid, (rel, strength) in zip(ids, expected):
            node = g[nid]
            self.assertEqual(node["class_type"], "LoraLoaderModelOnly")
            self.assertEqual(node["inputs"], {"lora_name": rel,
                                              "strength_model": strength,
                                              "model": [tail, 0]})
            tail = nid
        # The guider is the ONLY consumer of the model in this graph.
        self.assertEqual(g["ke:guider"]["inputs"]["model"], [tail, 0])
        # The trap: Flux2Scheduler takes steps/width/height and NO model.
        # Handing it the tail is a TypeError at execution, not a bad render.
        self.assertNotIn("model", g["ke:sched"]["inputs"])
        return tail

    def test_the_sigs_gate_now_passes_the_stack(self):
        self.assertIn("loras", server.SIGS["klein_edit"])
        self.assertIn("lora_plan", server.SIGS["klein_edit"])

    def test_a_stacked_lora_chains_and_is_reported(self):
        g, _instruction, info = build(
            lora_plan=plan("klein_edit", [{"slot": "detail"}]))
        self.assert_chain(g, [(DETAIL, 0.8)])
        self.assertEqual(info["loras"], ["Flux2-Klein-9B-Enhanced-Details@0.8"])
        self.assertEqual(info["lora_warnings"], [])
        self.assertEqual([(e["slot"], e["name"], e["strength"], e["zone"])
                          for e in info["lora_stack"]],
                         [("detail", DETAIL, 0.8, "editable")])
        server.validate_job_model_info("klein_edit", info, g)

    def test_two_loras_chain_in_plan_order(self):
        g, _instruction, info = build(
            lora_plan=plan("klein_edit", [{"name": STYLE2, "strength": 0.9},
                                          {"slot": "detail", "strength": 0.6}]))
        self.assert_chain(g, [(STYLE2, 0.9), (DETAIL, 0.6)])

    def test_a_foreign_lora_never_reaches_the_graph(self):
        g, _instruction, info = build(
            lora_plan=plan("klein_edit", [{"name": FOREIGN, "strength": 1.0}]))
        self.assert_chain(g, [])
        self.assertEqual(info["loras"], [])
        self.assertEqual(info["lora_warnings"],
                         ["incompatible " + server.base(FOREIGN)])

    def test_a_disabled_stage_adds_nothing(self):
        """The stage appears only when the user turns it ON: a plan carrying
        the row disabled renders the untouched graph."""
        g, _instruction, info = build(
            lora_plan=plan("klein_edit",
                           [{"slot": "detail", "enabled": False}]))
        self.assert_chain(g, [])
        self.assertEqual(info["loras"], [])

    def test_the_untouched_plan_is_the_pre_9_86_snapshot(self):
        """The regression that matters most: no loras, no plan -> the
        byte-identical graph the pre-change builder rendered."""
        snap = json.loads((ROOT / "tests" / "snapshots" /
                           "klein_edit_graph.json").read_text(encoding="utf-8"))
        g, instruction, _info = build()
        self.assertEqual(instruction, snap["instruction"])
        self.assertEqual(g, snap["graph"])

    def test_an_empty_plan_is_byte_identical_to_no_plan(self):
        plain = build()
        empty = build(lora_plan=plan("klein_edit", []))
        self.assertEqual(empty, plain)


class OptionsTests(unittest.TestCase):
    """/api/options ships the stage annotated installed - the gate's input."""

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

    def test_the_recipe_row_ships_the_stage_at_revision_2(self):
        with TemporaryDirectory() as td:
            options = self.options(klein_entries(Path(td)))
        recipe = {r["id"]: r for r in options["recipes"]}["klein_edit"]
        self.assertEqual(recipe["lora_stack_revision"], 2)
        self.assertEqual(recipe["lora_boundary"], "sampler")
        self.assertEqual(len(recipe["lora_stages"]), 1)
        stage = recipe["lora_stages"][0]
        self.assertEqual((stage["slot"], stage["name"], stage["zone"]),
                         ("detail", DETAIL, "editable"))
        self.assertTrue(stage["installed"])

    def test_the_stage_reports_not_installed_when_the_file_is_gone(self):
        """What the gate reads: with the Flux folder absent the SAME row
        ships installed false, and the popup offers no row at all."""
        with TemporaryDirectory() as td:
            options = self.options(klein_entries(Path(td), loras=False))
        recipe = {r["id"]: r for r in options["recipes"]}["klein_edit"]
        stage = recipe["lora_stages"][0]
        self.assertFalse(stage["installed"])


class PopupGateTests(unittest.TestCase):
    """Static, in the style of test_lora_card_controls.py (no JS runner):
    the add-popup never offers a recipe stage whose file is not installed."""

    def test_inactive_stage_rows_are_gated_on_installed(self):
        """"if they have that lora" is a filter on the row, not a hope: the
        server annotates every stage with `installed` and the popup's
        inactive-stage list honours it, so a click can never name a file the
        build would then refuse."""
        match = re.search(
            r"const inactiveStages = editableStages\.filter\(\(stage\) =>([\s\S]*?)\);",
            COMPOSER)
        self.assertIsNotNone(match, "the inactiveStages filter moved")
        body = match.group(1)
        self.assertIn("stage.installed", body,
                      "inactive recipe stages render regardless of installed")


if __name__ == "__main__":
    unittest.main()
