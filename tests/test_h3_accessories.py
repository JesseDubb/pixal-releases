"""Brief 9.83 - accessory reference slots.

A character gains an ordered `accessories` list ({image, description,
enabled}); its ENABLED accessories wire into the H3 reference lanes beside
the identity photo - identity at slot 0, accessories after it, eight at most
(the node has nine slots). The description is load-bearing: it becomes the
wired picture's <Subject N> definition, so an enabled accessory without one
is refused, and a disabled one is skipped unvalidated - it never reaches the
graph, so its state cannot break a render. Two toggles: per accessory on the
anchor (enabled), per render from the composer (the `accessories` builder
parameter, applied through _apply_opts and stripped/re-derived on reroll).

What these tests pin:

  RefData      - character_h3_refs returns the ordered wired list AS DATA
                 (lane-agnostic dicts): identity first, then enabled
                 accessories in order; disabled skipped unvalidated;
                 accessories=False is slot 0 alone; the ninth enabled is a
                 refusal, and traversal / missing file / missing description
                 in an ENABLED entry are ValueErrors.
  GraphShape   - build_h3_ref_still with 0, 1 and 8 enabled accessories: the
                 dotted keys and LoadImage nodes for exactly the wired refs;
                 a disabled accessory is absent from graph AND prompt; the
                 2x lane passes the parameter through; a zero-accessory
                 anchor still builds the 9.82 graph (references 1).
  Prompt       - each enabled accessory gets its <Subject N> definition in
                 its own description and a fully_preserved retention line;
                 the identity line is unchanged; the assembler prefers a
                 carried description over kind.
  SaveGate     - characters_post normalizes the list (whitespace collapsed,
                 enabled coerced), drops an empty one, and 400s the ninth
                 entry, an empty description, a traversal name and a missing
                 file - the identity_ref standard, entry index in the error.
  PerRender    - _apply_opts maps opts.accessories false ->
                 args["accessories"] = False; absent/true maps nothing; the
                 key is composer-owned on reroll; SIGS carries the parameter
                 on both ref-still builders only.
  Options      - /api/options carries the ENABLED count per character.
  ClientPins   - static, in the test_character_form.py style: the group sits
                 between "always true" and "for the writer" with the N / 8
                 count, rows use the shared lib Switch (the one control -
                 Composer's LoraToggle and MotionDirector's Switch are
                 migrated, no third copy), the save posts accessories, and
                 the composer popover gates its toggle on the count.

Same sanctioned simulation as every sibling file: stubbed catalog, stubbed
character, no generation, no ComfyUI, no GPU.
"""

import asyncio
import json
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location(
    "pixal_server_h3_accessories", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

WEB = ROOT / "web" / "src"
FORM = (WEB / "components" / "CharacterForm.jsx").read_text(encoding="utf-8")
COMPOSER = (WEB / "components" / "Composer.jsx").read_text(encoding="utf-8")
MOTION = (WEB / "components" / "MotionDirector.jsx").read_text(encoding="utf-8")
STORE = (WEB / "store.js").read_text(encoding="utf-8")
SWITCH = (WEB / "lib" / "Switch.jsx").read_text(encoding="utf-8")

REF2VA = server.H3_REF2V_MODEL

CHARACTER = {"id": "mia", "name": "Mia", "age": 24, "race": "Korean",
             "sex": "female", "style": "silver pixie cut, lean runner's build",
             "identity_ref": "mia.png"}

CASE = {"image": "case_green.png",
        "description": "green pebbled leather phone case with a gold frame",
        "enabled": True}
SNAKE = {"image": "case_snake.png",
         "description": "snakeskin phone case with a wordmark",
         "enabled": False}
CHARM = {"image": "charm.png", "description": "silver cherry bag charm",
         "enabled": True}
ACCESSORY_FILES = ("case_green.png", "case_snake.png", "charm.png")


def h3_entries(root):
    """This box's H3 stack as catalog entries (the test_h3_ref_still stub)."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    return [add("diffusion_models", server.H3_MODEL),
            add("diffusion_models", REF2VA),
            add("vae", server.H3_VIDEO_VAE),
            add("vae", server.H3_AUDIO_VAE),
            add("text_encoders", server.H3_CLIP)]


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def anchored(root, character):
    """A temp ComfyUI dir whose input/ holds the anchor's reference photo and
    every accessory image the tests name."""
    (root / "input").mkdir(exist_ok=True)
    (root / "input" / character["identity_ref"]).write_bytes(b"reference")
    for name in ACCESSORY_FILES:
        (root / "input" / name).write_bytes(b"accessory")
    return (patch.object(server, "CDIR", root),
            patch.object(server, "CHARACTERS", {character["id"]: character}))


def build_still(character, scene="A red barn at dusk", seed=424242, **kwargs):
    with TemporaryDirectory() as td:
        root = Path(td)
        cdir, chars = anchored(root, character)
        sidecar, roots = no_disk()
        with cdir, chars, sidecar, roots, \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(h3_entries(root))):
            return server.build_h3_ref_still(scene, seed,
                                             character=character["id"],
                                             **kwargs)


def wired_keys(g):
    return sorted(k for k in g["6"]["inputs"] if k.startswith("ref_images."))


class RefDataTests(unittest.TestCase):
    """character_h3_refs: the ordered wired list as lane-agnostic data."""

    def refs(self, character, **kwargs):
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, character)
            with cdir, chars:
                return server.character_h3_refs(character, **kwargs)

    def test_identity_holds_slot_zero_and_accessories_follow_in_order(self):
        ch = {**CHARACTER, "accessories": [CASE, SNAKE, CHARM]}
        refs = self.refs(ch)
        self.assertEqual([r["name"] for r in refs],
                         ["mia.png", "case_green.png", "charm.png"])
        self.assertEqual(refs[0], {"name": "mia.png", "kind": "identity"})
        # The enabled accessories carry the assembler's whole contract.
        self.assertEqual(refs[1], {"name": "case_green.png", "kind": "object",
                                   "description": CASE["description"]})

    def test_a_disabled_accessory_is_skipped_unvalidated(self):
        # Its state can be anything - it never reaches the graph, so it must
        # not break a render. A traversal name would be a ValueError enabled.
        bad = {"image": "../evil.png", "description": "x", "enabled": False}
        refs = self.refs({**CHARACTER, "accessories": [bad]})
        self.assertEqual([r["name"] for r in refs], ["mia.png"])

    def test_accessories_false_is_slot_zero_alone(self):
        ch = {**CHARACTER, "accessories": [CASE, CHARM]}
        refs = self.refs(ch, accessories=False)
        self.assertEqual(refs, [{"name": "mia.png", "kind": "identity"}])

    def test_the_ninth_enabled_accessory_is_a_refusal_not_a_drop(self):
        nine = [{"image": f"acc_{i}.png", "description": f"thing {i}",
                 "enabled": True} for i in range(9)]
        ch = {**CHARACTER, "accessories": nine}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, ch)
            for i in range(9):
                (root / "input" / f"acc_{i}.png").write_bytes(b"x")
            with cdir, chars:
                with self.assertRaisesRegex(ValueError,
                                            "at most|9 enabled accessories"):
                    server.character_h3_refs(ch)
        self.assertEqual(server.H3_REF_ACCESSORY_MAX,
                         server.H3_REF2V_MAX_IMAGES - 1)

    def test_eight_enabled_is_the_ceiling_not_an_error(self):
        eight = [{"image": f"acc_{i}.png", "description": f"thing {i}",
                  "enabled": True} for i in range(8)]
        ch = {**CHARACTER, "accessories": eight}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, ch)
            for i in range(8):
                (root / "input" / f"acc_{i}.png").write_bytes(b"x")
            with cdir, chars:
                refs = server.character_h3_refs(ch)
        self.assertEqual(len(refs), 9)      # identity + eight = the full node

    def test_an_enabled_accessory_rejects_traversal_like_identity_ref(self):
        bad = {"image": "..\\secret.png", "description": "x", "enabled": True}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, {**CHARACTER, "accessories": [bad]})
            with cdir, chars:
                with self.assertRaisesRegex(ValueError, "bad image"):
                    server.character_h3_refs(
                        {**CHARACTER, "accessories": [bad]})

    def test_an_enabled_accessory_needs_its_description(self):
        bad = {"image": "case_green.png", "description": "  ", "enabled": True}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, {**CHARACTER, "accessories": [bad]})
            with cdir, chars:
                with self.assertRaisesRegex(ValueError, "description"):
                    server.character_h3_refs(
                        {**CHARACTER, "accessories": [bad]})

    def test_an_enabled_accessory_needs_its_file(self):
        gone = {"image": "gone.png", "description": "lost case",
                "enabled": True}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, {**CHARACTER, "accessories": [gone]})
            with cdir, chars:
                with self.assertRaisesRegex(ValueError, "missing from"):
                    server.character_h3_refs(
                        {**CHARACTER, "accessories": [gone]})


class GraphShapeTests(unittest.TestCase):
    """build_h3_ref_still: the graph carries exactly the wired refs."""

    def test_zero_accessories_is_the_982_graph(self):
        g, _cap, info = build_still(CHARACTER)
        self.assertEqual(wired_keys(g), ["ref_images.ref_image_0"])
        self.assertEqual(g["5"]["inputs"], {"image": "mia.png"})
        self.assertNotIn("5b", g)
        self.assertEqual(info["references"], 1)
        self.assertEqual(info["accessories"], 0)

    def test_one_enabled_accessory_wires_ref_image_1(self):
        g, _cap, info = build_still({**CHARACTER, "accessories": [CASE]})
        self.assertEqual(wired_keys(g),
                         ["ref_images.ref_image_0", "ref_images.ref_image_1"])
        self.assertEqual(g["5"]["inputs"], {"image": "mia.png"})
        self.assertEqual(g["5b"]["class_type"], "LoadImage")
        self.assertEqual(g["5b"]["inputs"], {"image": "case_green.png"})
        self.assertEqual(g["6"]["inputs"]["ref_images.ref_image_1"], ["5b", 0])
        self.assertEqual(info["references"], 2)
        self.assertEqual(info["accessories"], 1)

    def test_a_disabled_accessory_is_absent_from_graph_and_prompt(self):
        g, _cap, info = build_still({**CHARACTER, "accessories": [SNAKE]})
        self.assertEqual(wired_keys(g), ["ref_images.ref_image_0"])
        self.assertNotIn("5b", g)
        self.assertEqual(info["accessories"], 0)
        prompt = g["6"]["inputs"]["prompt"]
        self.assertNotIn("<Subject 2>", prompt)
        self.assertNotIn("snakeskin", prompt)

    def test_disabled_and_enabled_keep_their_order_without_gaps(self):
        g, _cap, info = build_still(
            {**CHARACTER, "accessories": [SNAKE, CASE, CHARM]})
        self.assertEqual(wired_keys(g),
                         ["ref_images.ref_image_0", "ref_images.ref_image_1",
                          "ref_images.ref_image_2"])
        # The disabled snake leaves no hole: green takes slot 1, charm 2.
        self.assertEqual(g["5b"]["inputs"], {"image": "case_green.png"})
        self.assertEqual(g["5c"]["inputs"], {"image": "charm.png"})
        self.assertEqual(info["accessories"], 2)

    def test_eight_enabled_fill_the_node(self):
        eight = [{"image": f"acc_{i}.png", "description": f"thing {i}",
                  "enabled": True} for i in range(8)]
        ch = {**CHARACTER, "accessories": eight}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, ch)
            for i in range(8):
                (root / "input" / f"acc_{i}.png").write_bytes(b"x")
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                g, _cap, info = server.build_h3_ref_still("a barn", 1,
                                                          character="mia")
        self.assertEqual(wired_keys(g),
                         [f"ref_images.ref_image_{i}" for i in range(9)])
        for i, nid in enumerate(server._H3_REF2V_REF_NODES):
            self.assertEqual(g[nid]["class_type"], "LoadImage")
        self.assertEqual(info["accessories"], 8)

    def test_the_ninth_is_refused_at_build(self):
        nine = [{"image": f"acc_{i}.png", "description": f"thing {i}",
                 "enabled": True} for i in range(9)]
        ch = {**CHARACTER, "accessories": nine}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, ch)
            for i in range(9):
                (root / "input" / f"acc_{i}.png").write_bytes(b"x")
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                with self.assertRaisesRegex(ValueError, "at most"):
                    server.build_h3_ref_still("a barn", 1, character="mia")

    def test_the_per_render_parameter_suppresses_without_editing(self):
        g, _cap, info = build_still({**CHARACTER, "accessories": [CASE]},
                                    accessories=False)
        self.assertEqual(wired_keys(g), ["ref_images.ref_image_0"])
        self.assertEqual(info["accessories"], 0)
        self.assertNotIn("<Subject 2>", g["6"]["inputs"]["prompt"])

    def test_the_2x_lane_passes_the_parameter_through(self):
        ch = {**CHARACTER, "accessories": [CASE]}
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, ch)
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))), \
                 patch.object(server, "h3_upscale_available",
                              return_value=True):
                g_on, _c, _i = server.build_h3_ref_still_2x(
                    "a barn", 1, character="mia")
                g_off, _c2, _i2 = server.build_h3_ref_still_2x(
                    "a barn", 1, character="mia", accessories=False)
        self.assertIn("ref_images.ref_image_1", g_on["6"]["inputs"])
        self.assertNotIn("ref_images.ref_image_1", g_off["6"]["inputs"])


class PromptTests(unittest.TestCase):
    """Each enabled reference gets its own <Subject N> definition - in its
    own description - and its fully_preserved retention line."""

    def test_the_accessory_subject_line_carries_the_description(self):
        g, _cap, _info = build_still({**CHARACTER, "accessories": [CASE]})
        prompt = g["6"]["inputs"]["prompt"]
        self.assertIn("subject_definitions:\n"
                      "<Subject 1> is the person in <Picture 1>.\n"
                      "<Subject 2> is the green pebbled leather phone case "
                      "with a gold frame shown in <Picture 2>.", prompt)
        self.assertIn("<Subject 2>: fully_preserved - the features named in "
                      "subject_definitions are retained.", prompt)

    def test_every_enabled_reference_has_its_pair(self):
        g, _cap, _info = build_still(
            {**CHARACTER, "accessories": [SNAKE, CASE, CHARM]})
        prompt = g["6"]["inputs"]["prompt"]
        self.assertIn("<Subject 2> is the green pebbled leather phone case "
                      "with a gold frame shown in <Picture 2>.", prompt)
        self.assertIn("<Subject 3> is the silver cherry bag charm "
                      "shown in <Picture 3>.", prompt)
        self.assertEqual(prompt.count("fully_preserved"), 3)

    def test_the_assembler_prefers_a_carried_description_over_kind(self):
        prompt, _w = server.assemble_h3_ref2v_prompt(
            "detailed_description:\n[Shot 1] she waits.",
            [{"kind": "identity"},
             {"kind": "object", "description": "red enamel lighter"},
             {"kind": "style"}])
        self.assertIn("<Subject 1> is the person in <Picture 1>.", prompt)
        self.assertIn("<Subject 2> is the red enamel lighter "
                      "shown in <Picture 2>.", prompt)
        # Kind still serves the description-less ref.
        self.assertIn("<Subject 3> is the visual style of <Picture 3>.",
                      prompt)

    def test_the_subject_line_collapses_description_whitespace(self):
        line = server._h3_ref2v_subject_line(
            2, "object", "green  pebbled\n leather case")
        self.assertEqual(line, "<Subject 2> is the green pebbled leather "
                               "case shown in <Picture 2>.")


class SaveGateTests(unittest.TestCase):
    """characters_post: the accessory list is validated like identity_ref."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "input").mkdir()
        for name in ("mia.png",) + ACCESSORY_FILES:
            (root / "input" / name).write_bytes(b"png")
        self.chars = root / "characters"
        patches = [patch.object(server, "CDIR", root),
                   patch.object(server, "CHAR_DIR", self.chars),
                   patch.object(server, "CHARACTERS", {})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def post(self, character):
        request = SimpleNamespace(
            json=AsyncMock(return_value={"character": character}))
        return asyncio.run(server.characters_post(request))

    def stored(self):
        return json.loads((self.chars / "mia.json").read_text(encoding="utf-8"))

    def base(self, **extra):
        return {"id": "mia", "name": "Mia", "identity_ref": "mia.png",
                **extra}

    def test_the_list_round_trips_normalized(self):
        response = self.post(self.base(accessories=[
            {"image": "case_green.png",
             "description": "  green   pebbled\nleather case  ",
             "enabled": 1},
            {"image": "charm.png", "description": "silver cherry charm",
             "enabled": 0}]))
        self.assertEqual(response.status, 200)
        self.assertEqual(self.stored()["accessories"], [
            {"image": "case_green.png",
             "description": "green pebbled leather case", "enabled": True},
            {"image": "charm.png", "description": "silver cherry charm",
             "enabled": False}])

    def test_an_empty_list_is_dropped_not_stored(self):
        response = self.post(self.base(accessories=[]))
        self.assertEqual(response.status, 200)
        self.assertNotIn("accessories", self.stored())

    def test_a_card_without_the_field_saves_as_before(self):
        response = self.post(self.base())
        self.assertEqual(response.status, 200)
        self.assertNotIn("accessories", self.stored())

    def test_the_ninth_entry_is_a_400_naming_the_cap(self):
        nine = [{"image": "charm.png", "description": f"thing {i}"}
                for i in range(9)]
        response = self.post(self.base(accessories=nine))
        self.assertEqual(response.status, 400)
        self.assertIn("at most 8 accessories",
                      json.loads(response.text)["error"])

    def test_an_empty_description_is_a_400_naming_the_entry(self):
        response = self.post(self.base(accessories=[
            {"image": "case_green.png", "description": "ok case"},
            {"image": "charm.png", "description": "  "}]))
        self.assertEqual(response.status, 400)
        self.assertIn("accessory 2", json.loads(response.text)["error"])

    def test_traversal_is_rejected_exactly_as_for_identity_ref(self):
        response = self.post(self.base(accessories=[
            {"image": "../secret.png", "description": "x"}]))
        self.assertEqual(response.status, 400)
        self.assertIn("bad image name", json.loads(response.text)["error"])

    def test_a_missing_file_is_a_400(self):
        response = self.post(self.base(accessories=[
            {"image": "gone.png", "description": "lost case"}]))
        self.assertEqual(response.status, 400)
        self.assertIn("not in ComfyUI/input",
                      json.loads(response.text)["error"])

    def test_a_non_list_is_a_400(self):
        response = self.post(self.base(accessories={"image": "charm.png"}))
        self.assertEqual(response.status, 400)


class PerRenderTests(unittest.TestCase):
    """The composer suppression: opts key -> builder arg -> reroll-owned."""

    def apply(self, opts):
        with TemporaryDirectory() as td:
            root = Path(td)
            cdir, chars = anchored(root, CHARACTER)
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))):
                args = {}
                server._apply_opts(args, opts)
                return args

    def test_accessories_false_becomes_the_builder_argument(self):
        args = self.apply({"character": "mia", "accessories": False})
        self.assertIs(args["accessories"], False)
        self.assertEqual(args["character"], "mia")

    def test_absent_or_true_maps_nothing(self):
        self.assertNotIn("accessories", self.apply({"character": "mia"}))
        self.assertNotIn("accessories",
                         self.apply({"character": "mia",
                                     "accessories": True}))

    def test_the_key_is_composer_owned_on_reroll(self):
        self.assertIn("accessories", server._REROLL_COMPOSER_OWNED)

    def test_only_the_ref_still_builders_take_the_parameter(self):
        self.assertIn("accessories", server.SIGS["h3_ref_still"])
        self.assertIn("accessories", server.SIGS["h3_ref_still_2x"])
        self.assertNotIn("accessories", server.SIGS["realism"])
        self.assertNotIn("accessories", server.SIGS["identity_edit"])


class OptionsTests(unittest.TestCase):
    """/api/options: the enabled count rides the character summary."""

    def test_the_enabled_count_not_the_list_length(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            ch = {**CHARACTER, "accessories": [CASE, SNAKE, CHARM]}
            cdir, chars = anchored(root, ch)
            sidecar, roots = no_disk()
            with cdir, chars, sidecar, roots, \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(h3_entries(root))), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE",
                              root / "titles.json"):
                options = server.Hub().options()
        mia = next(c for c in options["characters"] if c["id"] == "mia")
        self.assertEqual(mia["accessories"], 2)     # snake is off


class ClientPinTests(unittest.TestCase):
    """Static source pins, test_character_form.py style: the JSX is the
    contract, and a regex that stops matching IS the regression report."""

    def test_the_group_sits_where_982_left_room(self):
        # Re-labelled "references" in 1.1.4b: the slots always took any
        # photograph, and calling them accessories hid the single biggest
        # fix of the reference-realism session - wiring a SECOND PERSON.
        self.assertLess(FORM.index('<Group label={<>Always true'),
                        FORM.index('<Group label={<>Wired references'))
        self.assertLess(FORM.index('<Group label={<>Wired references'),
                        FORM.index('<Group label={<>For the writer'))
        self.assertNotIn('label="accessories"', FORM)

    def test_the_eyebrow_and_button_face_state_the_capacity(self):
        start = FORM.index('<Group label={<>Wired references')
        group = FORM[start:FORM.index("</Group>", start)]
        self.assertIn("fontFamily: MONO", group)
        self.assertIn(
            "{accessories.filter((a) => a.enabled).length} / {ACCESSORY_MAX}",
            group)
        self.assertNotIn("of ${ACCESSORY_MAX} on", FORM)
        self.assertIn("a bag, a jacket, or a second person", group)
        self.assertNotIn("{accessories.length}/{ACCESSORY_MAX}", group,
                         "the count is stated once, in the eyebrow")
        self.assertRegex(FORM, r"const ACCESSORY_MAX = 8;")

    def test_rows_use_the_shared_switch_and_carry_the_load_bearing_field(self):
        self.assertIn('import { Switch } from "../lib/Switch.jsx";', FORM)
        self.assertIn('placeholder="green pebbled leather phone case"', FORM)
        self.assertIn("ch.accessories = accOut", FORM)
        self.assertIn("every accessory needs a description", FORM)

    def test_the_picker_uploads_as_object_references(self):
        self.assertIn("const AccessoryPicker = ", FORM)
        self.assertIn('upload(f, "object")', FORM)
        self.assertIn("addAccessory", FORM)

    def test_the_switch_is_one_control_with_one_home(self):
        self.assertIn('role="switch"', SWITCH)
        self.assertIn('import { Switch } from "../lib/Switch.jsx";', COMPOSER)
        self.assertIn('import { Switch } from "../lib/Switch.jsx";', MOTION)
        self.assertNotIn("const LoraToggle", COMPOSER)
        self.assertNotIn("const Switch = (", MOTION)
        self.assertNotIn("const Switch = (", COMPOSER)

    def test_the_composer_popover_gates_on_the_anchor_having_accessories(self):
        self.assertIn("sel.accessories || 0) > 0", COMPOSER)
        self.assertIn("setOpts({ accessories: next })", COMPOSER)

    def test_the_store_heals_on_and_sends_only_the_off(self):
        self.assertIn("accessories: true", STORE)
        self.assertIn("o.accessories = o.accessories !== false;", STORE)
        self.assertIn("body.accessories = false;", STORE)
        self.assertIn('"accessories off"', STORE)


if __name__ == "__main__":
    unittest.main()
