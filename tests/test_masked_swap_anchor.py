"""Brief 10.10 — the masked Klein swap can trade its source anchor.

The builder assertions pin the graph itself; the UI assertions are static in
the repository's network-free JSX style.  The request-path check follows the
value through EditDirector -> store -> transport so a control that is silently
dropped before ``/api/edit`` cannot pass.
"""

import asyncio
import base64
import hashlib
import io
import json
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_masked_swap_anchor", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

DIRECTOR = (ROOT / "web" / "src" / "components" / "EditDirector.jsx").read_text(
    encoding="utf-8")
STORE = (ROOT / "web" / "src" / "store.js").read_text(encoding="utf-8")
TRANSPORT = (ROOT / "web" / "src" / "transport.js").read_text(encoding="utf-8")

# Captured from the pre-brief builder with the fixed one-reference fixture
# below.  The default arm must remain the graph existing renders already use.
PRE_CHANGE_GRAPH_SHA256 = (
    "433495960816f02572bbfbb45d9f483eb0ba994789e671576ab6e5b7b44d1f67")


def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


def graph_digest(graph):
    raw = json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class KleinInpaintAnchorGraphTests(unittest.TestCase):
    def build(self, refs=("reference.png",), **kwargs):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGBA", (64, 64), (9, 9, 9, 255)).save(
                root / "input" / "source.png")
            Image.new("RGB", (32, 48), (7, 7, 7)).save(
                root / "input" / "reference.png")
            Image.new("RGB", (40, 24), (8, 8, 8)).save(
                root / "input" / "reference-2.png")
            reference = (None if not refs else refs[0] if len(refs) == 1
                         else list(refs))
            with patch.object(server, "CDIR", root), \
                 patch.object(
                     server, "pick_recipe_model",
                     return_value=model(server.KLEIN_MODEL, "klein", "edit")), \
                 patch.object(
                     server, "_pick_catalog_asset",
                     side_effect=lambda kind, names, *a: names[0]):
                graph, _scene, _info = server.build_klein_inpaint(
                    "replace the face", 424242, "source.png",
                    reference=reference, **kwargs)
        return graph

    def test_full_default_keeps_the_pre_change_graph_byte_identical(self):
        omitted = self.build()
        self.assertEqual(graph_digest(omitted), PRE_CHANGE_GRAPH_SHA256)

        explicit = self.build(anchor="full")
        self.assertEqual(explicit, omitted)
        self.assertEqual(graph_digest(explicit), PRE_CHANGE_GRAPH_SHA256)

    def test_drop_removes_the_full_frame_anchor_and_starts_after_inpaint(self):
        graph = self.build(anchor="drop")

        self.assertNotIn("ki:ref", graph)
        self.assertNotIn("ki:reffull", graph)
        self.assertEqual(
            graph["ki:refcond1_pos"]["inputs"]["conditioning"],
            ["ki:refinpaint", 0])
        self.assertEqual(
            graph["ki:sampler"]["inputs"]["positive"],
            ["ki:refcond1_pos", 0])
        self.assertEqual(
            graph["ki:sampler"]["inputs"]["latent_image"], ["ki:latent", 0])
        self.assertEqual(
            graph["ki:composite"]["inputs"]["original_image"], ["ki:img", 0])

    def test_last_puts_the_existing_anchor_after_every_reference(self):
        graph = self.build(
            refs=("reference.png", "reference-2.png"), anchor="last")

        self.assertIn("ki:ref", graph)
        self.assertIn("ki:reffull", graph)
        self.assertEqual(
            graph["ki:refcond1_pos"]["inputs"]["conditioning"],
            ["ki:refinpaint", 0])
        self.assertEqual(
            graph["ki:refcond2_pos"]["inputs"]["conditioning"],
            ["ki:refcond1_pos", 0])
        self.assertEqual(
            graph["ki:ref"]["inputs"]["conditioning"],
            ["ki:refcond2_pos", 0])
        self.assertEqual(
            graph["ki:ref"]["inputs"]["latent"], ["ki:reffull", 0])
        self.assertEqual(
            graph["ki:sampler"]["inputs"]["positive"], ["ki:ref", 0])

    def test_every_anchor_value_is_inert_without_a_reference(self):
        omitted = self.build(refs=())
        for anchor in ("full", "drop", "last"):
            with self.subTest(anchor=anchor):
                self.assertEqual(self.build(refs=(), anchor=anchor), omitted)

    def test_unknown_anchor_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "anchor"):
            self.build(refs=(), anchor="somewhere")


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class EditAnchorRouteTests(unittest.TestCase):
    def test_masked_edit_accepts_and_forwards_anchor(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", (64, 64), (9, 9, 9)).save(
                root / "input" / "source.png")
            Image.new("RGB", (32, 48), (7, 7, 7)).save(
                root / "input" / "reference.png")
            mask_bytes = io.BytesIO()
            Image.new("L", (64, 64), 255).save(mask_bytes, format="PNG")
            mask = ("data:image/png;base64," +
                    base64.b64encode(mask_bytes.getvalue()).decode())
            hub = MagicMock()
            hub.submit = AsyncMock(return_value=None)

            async def send():
                with patch.object(server, "CDIR", root), \
                     patch.object(server, "HUB", hub):
                    response = await server.edit(FakeRequest({
                        "input": "source.png",
                        "instruction": "replace the face",
                        "mask": mask,
                        "reference": "reference.png",
                        "anchor": "drop",
                    }))
                    await asyncio.sleep(0)
                    return response

            response = asyncio.run(send())

        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(json.loads(response.text)["recipe"], "klein_inpaint")
        args = hub.submit.call_args.args[4]
        self.assertEqual(args["reference"], "reference.png")
        self.assertEqual(args["anchor"], "drop")
        self.assertIn("anchor", server.SIGS["klein_inpaint"])


class MaskedSwapAnchorUiTests(unittest.TestCase):
    def test_the_shared_small_segmented_control_and_infotip_are_present(self):
        self.assertIn(
            'import { SegmentedControl } from "../lib/SegmentedControl.jsx";',
            DIRECTOR)
        self.assertIn('import { InfoTip } from "./InfoTip.jsx";', DIRECTOR)
        self.assertEqual(DIRECTOR.count("<SegmentedControl"), 1)
        start = DIRECTOR.index("<SegmentedControl")
        control = DIRECTOR[start:DIRECTOR.index("/>", start) + 2]
        self.assertIn('size="sm"', control)
        self.assertIn("value={anchor}", control)
        self.assertIn("onChange={setAnchor}", control)
        for value, label in (("full", "Anchored"),
                             ("drop", "Reference leads"),
                             ("last", "Anchor last")):
            with self.subTest(value=value):
                self.assertRegex(
                    control,
                    rf'\{{\s*v:\s*"{value}",\s*label:\s*"{label}"\s*\}}')
        self.assertIn("<InfoTip", DIRECTOR)
        for fact in (
                "keeps identity outside the mask from drifting",
                "Dropping it lets the attached reference drive the masked area",
                "composite still returns untouched pixels bit-identical"):
            with self.subTest(fact=fact):
                self.assertIn(fact, DIRECTOR)

    def test_the_control_uses_the_existing_lane_and_only_the_masked_swap(self):
        definition = re.search(r"const maskedSwap\s*=\s*([^;]+);", DIRECTOR)
        self.assertIsNotNone(definition, "the masked swap needs one render gate")
        for token in ("masked", "refImg", "lane"):
            with self.subTest(token=token):
                self.assertIn(token, definition.group(1))
        self.assertIn('lane.id === "klein_inpaint"', definition.group(1))
        gate = DIRECTOR.index("{maskedSwap && (")
        self.assertLess(gate, DIRECTOR.index("<SegmentedControl"))

    def test_the_choice_resets_and_reaches_the_real_edit_request_body(self):
        self.assertIn('const [anchor, setAnchor] = useState("full")', DIRECTOR)
        self.assertIn("if (maskedSwap) extra.anchor = anchor;", DIRECTOR)

        remove_title = DIRECTOR.index('title="remove reference image"')
        remove_button = DIRECTOR[DIRECTOR.rfind("<button", 0, remove_title):
                                 DIRECTOR.index("</button>", remove_title)]
        self.assertIn("setRefImg(null)", remove_button)
        self.assertIn('setAnchor("full")', remove_button)

        edit = STORE[STORE.index("async edit("):STORE.index("async editInput(")]
        edit_input = STORE[STORE.index("async editInput("):
                           STORE.index("async deleteEntry(")]
        self.assertIn("extra.anchor", edit)
        self.assertIn("extra.anchor", edit_input)

        transport_start = TRANSPORT.index("export const edit =")
        transport_edit = TRANSPORT[transport_start:
                                   TRANSPORT.index("export const stageInput", transport_start)]
        self.assertRegex(
            transport_edit,
            r"export const edit = \(id, cid, instruction, input, mask, reference, anchor\)")
        self.assertIn("...(anchor ? { anchor } : {})", transport_edit)


if __name__ == "__main__":
    unittest.main()
