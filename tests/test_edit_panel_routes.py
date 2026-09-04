"""Brief 10.11 — the edit panel follows the server-resolved lane.

The server assertions exercise the real Hub.options payload with the same
config/resolver seam used by the existing /api/edit routing tests.  The client
assertions are static because this repository's suite deliberately has no JS
runtime.
"""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_edit_panel_routes", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

CHAT = (ROOT / "web" / "src" / "components" / "Chat.jsx").read_text(
    encoding="utf-8")
DIRECTOR = (ROOT / "web" / "src" / "components" / "EditDirector.jsx").read_text(
    encoding="utf-8")


class OptionsEditRouteTests(unittest.TestCase):
    QWEN = "Qwen\\qwen-image-edit-2511-Q6_K.gguf"
    KLEIN = "Flux\\flux-2-klein-9b_int8_convrot.safetensors"

    def options_for(self, configured):
        config = {
            "edit": {"model": configured},
            "h3": {"ref_model": "", "fl_model": "", "text_encoder": ""},
            "extra_model_roots": [],
        }

        def resolve(name):
            if not configured or str(name).lower() != configured.lower():
                return None
            family = "klein" if "klein" in configured.lower() else "qwen_edit"
            return {"rel": configured, "kind": "diffusion_models",
                    "family": family, "variant": "edit", "supported": True}

        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "load_config", return_value=config), \
                 patch.object(server, "resolve_model_entry", side_effect=resolve), \
                 patch.object(server, "model_catalog", return_value=[]), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "lm_enrich"), \
                 patch.object(server, "_LORA_TITLE_CACHE", root / "titles.json"):
                return server.Hub().options()

    def test_options_reports_klein_for_a_klein_whole_frame_pick(self):
        self.assertEqual(
            self.options_for(self.KLEIN)["edit_routes"],
            {"whole_frame": "klein_edit", "masked": "klein_inpaint"},
        )

    def test_options_reports_qwen_for_qwen_and_legacy_empty_picks(self):
        for configured in (self.QWEN, ""):
            with self.subTest(configured=configured):
                self.assertEqual(
                    self.options_for(configured)["edit_routes"],
                    {"whole_frame": "qwen_edit", "masked": "klein_inpaint"},
                )


class ChatEditRouteTests(unittest.TestCase):
    def test_recipe_rows_follow_edit_routes_with_old_sidecar_fallbacks(self):
        routing = CHAT.split("const [editFor", 1)[1].split("// The lobby", 1)[0]
        self.assertIn("store.options.edit_routes", routing)
        whole_frame = routing.split("const editRecipe =", 1)[1].split(";", 1)[0]
        masked = routing.split("const kleinRecipe =", 1)[1].split(";", 1)[0]
        self.assertIn('editRoutes.whole_frame || "qwen_edit"', whole_frame)
        self.assertNotIn("editRoutes.masked", whole_frame)
        self.assertIn('editRoutes.masked || "klein_inpaint"', masked)
        self.assertNotIn("editRoutes.whole_frame", masked)
        self.assertNotIn('r.id === "qwen_edit"', whole_frame)

        invocation = CHAT.split("<EditDirector onClose", 1)[1].split("/>", 1)[0]
        self.assertIn("wholeFrameRecipe={editRecipe}", invocation)


class EditDirectorRouteTests(unittest.TestCase):
    def test_unavailable_copy_uses_the_resolved_recipe_label(self):
        alert = DIRECTOR.split("{!laneOk ?", 1)[1].split(") : null}", 1)[0]
        self.assertNotIn("Qwen Image Edit is unavailable.", DIRECTOR)
        self.assertIn("wholeFrameRecipe?.label", DIRECTOR)
        self.assertIn("`${wholeFrameLabel} is unavailable.`", alert)
        # The masked lane is outside this brief and keeps its existing copy.
        self.assertIn('"Klein inpaint is unavailable."', alert)

    def test_reference_coaching_follows_the_resolved_whole_frame_route(self):
        qwen = DIRECTOR.split("const EXAMPLES_REF = [", 1)[1].split("];", 1)[0]
        self.assertEqual(
            [line.strip().strip('",') for line in qwen.splitlines() if '"' in line],
            ["put the logo from image 2 on her shirt",
             "paint image 2 on the wall as a mural",
             "print the logo from image 2 on the billboard"],
        )
        self.assertIn("const EXAMPLES_REF_KLEIN = [", DIRECTOR)
        klein = DIRECTOR.split("const EXAMPLES_REF_KLEIN = [", 1)[1].split("];", 1)[0]
        self.assertNotIn("image 2", klein.lower())
        self.assertEqual(
            [line.strip().strip('",') for line in klein.splitlines() if '"' in line],
            ["put the logo from the attached image on her shirt",
             "dress her in the jacket from the attached image",
             "swap her face for the attached photo"],
        )
        self.assertIn('wholeFrameRecipe?.id === "klein_edit"', DIRECTOR)
        chooser = DIRECTOR.split("{/* Examples follow the lane", 1)[1] \
            .split(".map((item)", 1)[0]
        self.assertIn(
            "? (kleinWholeFrame ? EXAMPLES_REF_KLEIN : EXAMPLES_REF)", chooser,
        )
        lane = DIRECTOR.split("const lane = useMemo", 1)[1] \
            .split("const maskedSwap", 1)[0]
        self.assertIn(
            'copy: kleinWholeFrame\n'
            '        ? "your words can describe what the attached image provides · Klein edit"\n'
            '        : "your words can point at the attached image as “image 2”",',
            lane,
        )


if __name__ == "__main__":
    unittest.main()
