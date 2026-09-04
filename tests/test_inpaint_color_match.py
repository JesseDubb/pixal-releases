"""Brief 10.12 — default-off ColorMatchV2 wiring for Klein inpaint."""

import asyncio
import base64
import hashlib
import io
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_inpaint_color_match", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

SETTINGS = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(
    encoding="utf-8")
EDIT_SETTINGS = SETTINGS.split("<Section title={<>Edit model", 1)[1].split(
    "<Section title={<>MiniMax H3", 1)[0]

# Same pre-10.10 one-reference graph pinned by test_masked_swap_anchor.py.
PRE_CHANGE_GRAPH_SHA256 = (
    "433495960816f02572bbfbb45d9f483eb0ba994789e671576ab6e5b7b44d1f67")


def model(rel, family="klein", variant="edit"):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True}


def graph_digest(graph):
    raw = json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class KleinInpaintColorMatchGraphTests(unittest.TestCase):
    def build(self, *, measurable=True, **kwargs):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            if measurable:
                Image.new("RGBA", (64, 64), (9, 9, 9, 255)).save(
                    root / "input" / "source.png")
            else:
                (root / "input" / "source.png").write_bytes(b"unreadable")
            Image.new("RGB", (32, 48), (7, 7, 7)).save(
                root / "input" / "reference.png")
            with patch.object(server, "CDIR", root), \
                 patch.object(
                     server, "pick_recipe_model",
                     return_value=model(server.KLEIN_MODEL)), \
                 patch.object(
                     server, "_pick_catalog_asset",
                     side_effect=lambda kind, names, *a: names[0]):
                graph, _scene, _info = server.build_klein_inpaint(
                    "replace the face", 424242, "source.png",
                    reference="reference.png", **kwargs)
        return graph

    def test_default_and_explicit_off_keep_the_graph_byte_identical(self):
        omitted = self.build()
        explicit = self.build(color_match=False)

        self.assertEqual(graph_digest(omitted), PRE_CHANGE_GRAPH_SHA256)
        self.assertEqual(explicit, omitted)
        self.assertEqual(graph_digest(explicit), PRE_CHANGE_GRAPH_SHA256)
        self.assertNotIn("ki:cmatch", explicit)

    def test_on_inserts_the_exact_node_around_the_current_composite_input(self):
        before = self.build()
        prior_target = before["ki:composite"]["inputs"]["generated_image"]
        graph = self.build(color_match=True)

        self.assertEqual(prior_target, ["ki:back", 0])
        self.assertEqual(
            graph["ki:cmatch"],
            {"class_type": "ColorMatchV2",
             "inputs": {"image_target": prior_target,
                        "image_ref": ["ki:img", 0],
                        "method": "mkl",
                        "strength": 0.95,
                        "multithread": True}})
        self.assertEqual(
            graph["ki:composite"]["inputs"]["generated_image"],
            ["ki:cmatch", 0])
        # Builder validation deliberately follows bool(), even for non-bools.
        self.assertIn("ki:cmatch", self.build(color_match="enabled"))
        self.assertEqual(self.build(color_match=0), before)
        overridden_target = ["custom:decode", 0]
        overridden = self.build(
            color_match=True,
            overrides=({"node": "ki:composite", "input": "generated_image",
                        "value": overridden_target},))
        self.assertEqual(
            overridden["ki:cmatch"]["inputs"]["image_target"],
            overridden_target)
        self.assertEqual(
            overridden["ki:composite"]["inputs"]["generated_image"],
            ["ki:cmatch", 0])

    def test_on_wraps_decode_in_the_unmeasurable_source_bypass(self):
        graph = self.build(measurable=False, color_match=True)

        self.assertEqual(
            graph["ki:cmatch"]["inputs"]["image_target"], ["ki:decode", 0])
        self.assertNotEqual(
            graph["ki:cmatch"]["inputs"]["image_target"], ["ki:back", 0])
        self.assertEqual(
            graph["ki:composite"]["inputs"]["generated_image"],
            ["ki:cmatch", 0])


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class InpaintColorMatchSettingsTests(unittest.TestCase):
    @staticmethod
    def full_cfg(edit):
        return {"llm": {"base_url": "", "model": ""},
                "critic": {"model": ""}, "upscale": {}, "edit": edit,
                "vae": {}, "pid": {},
                "video": {"default_engine": "", "default_model": ""},
                "extra_model_roots": [], "comfy_editor": False,
                "comfy_console": "tui", "explicit": "auto",
                "vram_profile": "auto"}

    @staticmethod
    def settings_edit(cfg):
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=lambda k, r: r), \
             patch.object(server, "refresh_comfy_nodes", AsyncMock()):
            response = asyncio.run(server.settings_get(FakeRequest({})))
        if response.status != 200:
            raise AssertionError(response.text)
        return json.loads(response.text)["edit"]

    def test_bool_round_trips_through_post_and_get(self):
        cfg = self.full_cfg(
            {"model": "", "inpaint_model": "", "speed": "turbo",
             "inpaint_color_match": False})
        save = MagicMock()
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "save_config", save):
            response = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"inpaint_color_match": True}})))

        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(json.loads(response.text), {"ok": True})
        save.assert_called_once_with(cfg)
        self.assertIs(cfg["edit"]["inpaint_color_match"], True)
        self.assertIs(self.settings_edit(cfg)["inpaint_color_match"], True)

        save.reset_mock()
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "save_config", save):
            response = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"inpaint_color_match": False}})))
        self.assertEqual(response.status, 200, response.text)
        save.assert_called_once_with(cfg)
        self.assertIs(cfg["edit"]["inpaint_color_match"], False)
        self.assertIs(self.settings_edit(cfg)["inpaint_color_match"], False)

    def test_non_bool_does_not_crash_or_replace_the_default(self):
        # This fixture models a config written before the key existed. GET must
        # still publish the default after POST ignores a value of the wrong type.
        cfg = self.full_cfg({"model": "", "inpaint_model": "", "speed": "turbo"})
        with patch.object(server, "load_config", return_value=cfg), \
             patch.object(server, "save_config", MagicMock()):
            response = asyncio.run(server.settings_post(FakeRequest(
                {"edit": {"inpaint_color_match": "yes"}})))

        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(json.loads(response.text), {"ok": True})
        self.assertIs(self.settings_edit(cfg)["inpaint_color_match"], False)


class InpaintColorMatchEditRouteTests(unittest.TestCase):
    def test_masked_edit_passes_the_config_value_not_a_per_shot_value(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            Image.new("RGB", (64, 64), (9, 9, 9)).save(
                root / "input" / "source.png")
            mask_bytes = io.BytesIO()
            Image.new("L", (64, 64), 255).save(mask_bytes, format="PNG")
            mask = ("data:image/png;base64," +
                    base64.b64encode(mask_bytes.getvalue()).decode())
            hub = MagicMock()
            hub.submit = AsyncMock(return_value=None)

            async def send(edit_config, per_shot):
                with patch.object(server, "CDIR", root), \
                     patch.object(server, "HUB", hub), \
                     patch.object(
                         server, "load_config",
                         return_value={"edit": edit_config}):
                    response = await server.edit(FakeRequest({
                        "input": "source.png",
                        "instruction": "replace the face",
                        "mask": mask,
                        "color_match": per_shot,
                    }))
                    await asyncio.sleep(0)
                    return response

            response = asyncio.run(send({"inpaint_color_match": True}, False))
            configured_args = dict(hub.submit.call_args.args[4])
            hub.submit.reset_mock()
            default_response = asyncio.run(send({}, True))
            default_args = dict(hub.submit.call_args.args[4])

        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(json.loads(response.text)["recipe"], "klein_inpaint")
        self.assertIs(configured_args["color_match"], True)
        self.assertEqual(default_response.status, 200, default_response.text)
        self.assertIs(default_args["color_match"], False)
        self.assertIn("color_match", server.SIGS["klein_inpaint"])


class InpaintColorMatchSettingsUiTests(unittest.TestCase):
    def test_edit_settings_uses_the_shared_switch_and_apply(self):
        self.assertIn('import { Switch } from "../lib/Switch.jsx";', SETTINGS)
        self.assertIn("Inpaint color match", EDIT_SETTINGS)
        self.assertNotIn(
            'hint="Matches the redrawn area\'s color to the frame"',
            EDIT_SETTINGS)
        self.assertIn(
            'text="The inpainted region can come back desaturated; this matches '
            'it to the source before compositing (mkl 0.95)."',
            EDIT_SETTINGS)
        self.assertIn('label="Inpaint color match"', EDIT_SETTINGS)
        self.assertIn("on={!!editCfg.inpaint_color_match}", EDIT_SETTINGS)
        self.assertIn(
            "setEditCfg({ ...editCfg, inpaint_color_match: on })",
            EDIT_SETTINGS)
        self.assertIn(
            "apply({ edit: { inpaint_color_match: on } },",
            EDIT_SETTINGS)
        self.assertNotIn('role="switch"', EDIT_SETTINGS)


if __name__ == "__main__":
    unittest.main()
