"""Brief 9.60 - official prompting: the model maker's own expansion prompt
as the writer.

Six same-seed A/B pairs (2026-08-27, Desktop\\Zara Promo\\26-prompt-ab): the
local brain running Krea's official expansion.txt verbatim as its system
prompt beat Pixal's writer on all four Zara shots and tied on two
plain-realism shots. llm.official_prompting (default True since 2026-08-27's product A/B; Off is byte-identical to the pre-9.60 prompts - an untouched
install writes exactly as today) makes that a switch, not a replacement:

  - prompts/official/<family>.txt is the data (Krea's expansion.txt for
    krea2); official_prompt(family) loads it, stripping #-header lines, and
    caches. A family with no file has no official prompt and the toggle is a
    no-op for it.
  - With the toggle ON and the turn's effective recipe in a family that has a
    file, the writer's craft block for that family is REPLACED by the official
    text in BOTH writers (the big-brain SYSTEM's "Photo craft for realism and
    realism_ii:" block, the local SYSTEM_LOCAL's "Write the scene the way the
    render models were measured to like:" block), with Pixal's short contract
    paragraph appended (nsfw=true overrides rule 8). Everything else - the
    identity_edit EDIT register, the composer blocks, the RENDER MECHANICS
    end-contract - stays, and the end-contract still comes last.
  - The job info gains "writer": "official" | "pixal" | "verbatim" so a card
    and the A/B driver can tell which wrote the scene.
  - The Brain tab carries the toggle row directly under the brain picker.

Same sanctioned simulation as the other settings/writer suites: fixed
strings and stubbed handlers - no generation, no ComfyUI, no GPU, no brain.
"""

import asyncio
import hashlib
import json
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

_SPEC = spec_from_file_location(
    "pixal_server_official_prompting",
    Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = ROOT / "prompts" / "official" / "krea2.txt"
JSX = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")

# Krea rule 1 and the Pixal craft line the swap must remove (local lane).
KREA_RULE_1 = "Faithfulness First"
PIXAL_CRAFT = "ONE named light source"

# The Off position, hashed BEFORE this branch touched anything (2026-08-27):
# base + TURN_POLICY + enhance policy, per lane and policy. Byte-identical or
# the toggle is not a no-op when off.
OFF_SNAPSHOT = {
    (False, False): "6e1e350fa6c55e90b4555098ff87daa6ab69e2b9b345922c6a582ef0e46e914f",
    (False, True): "aa1e3fd0bc80a7c3c91231fb4e17b8c397d54d76a14ae39878c5ac6548d42ae0",
    (True, False): "55afa2464c0231db771e30a9da0fd610ecba4ad8aa80bf5a02058dc217eaffb6",
    (True, True): "9aef9f2a8fbea0b3104919995409fcbda03404c6d9c91f0444727b6565ce23cb",
}


def _cfg(official):
    return {"llm": {"official_prompting": official}}


class FakeRequest:
    """The aiohttp stand-in every settings_post test file keeps local."""
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class OfficialPromptFileTests(unittest.TestCase):

    def test_the_file_loads_and_the_header_strips(self):
        raw = PROMPT_FILE.read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("#"), "the 2-line source header is gone")
        text = server.official_prompt("krea2")
        self.assertIsNotNone(text)
        self.assertFalse(any(line.startswith("#") for line in text.splitlines()),
                         "header lines reached the prompt body")
        self.assertIn(KREA_RULE_1, text)

    def test_official_prompt_equals_the_file_body(self):
        raw = PROMPT_FILE.read_text(encoding="utf-8")
        body = "\n".join(line for line in raw.splitlines()
                         if not line.startswith("#")).strip()
        self.assertEqual(server.official_prompt("krea2"), body)

    def test_a_family_with_no_file_has_no_official_prompt(self):
        self.assertIsNone(server.official_prompt("zimage"))

    def test_the_family_list_comes_from_the_data_dir(self):
        self.assertEqual(server.official_prompt_families(), ["krea2"])


class OffPositionSnapshotTests(unittest.TestCase):
    """Accept: toggle off, every system prompt byte-identical to today."""

    def test_toggle_off_is_byte_identical(self):
        with patch.object(server, "load_config", return_value=_cfg(False)):
            for (local, enhance), want in sorted(OFF_SNAPSHOT.items()):
                with self.subTest(local=local, enhance=enhance):
                    p = server.writer_system_prompt(local, enhance, "realism")
                    got = hashlib.sha256(p.encode("utf-8")).hexdigest()
                    self.assertEqual(got, want)


class WriterSwapTests(unittest.TestCase):

    def test_local_realism_turn_swaps_the_craft_block_when_on(self):
        with patch.object(server, "load_config", return_value=_cfg(True)):
            p = server.writer_system_prompt(True, True, "realism")
        self.assertIn(KREA_RULE_1, p)
        self.assertNotIn(PIXAL_CRAFT, p)

    def test_local_realism_turn_keeps_pixal_when_off(self):
        with patch.object(server, "load_config", return_value=_cfg(False)):
            p = server.writer_system_prompt(True, True, "realism")
        self.assertIn(PIXAL_CRAFT, p)
        self.assertNotIn(KREA_RULE_1, p)

    def test_cloud_realism_turn_swaps_too(self):
        with patch.object(server, "load_config", return_value=_cfg(True)):
            p = server.writer_system_prompt(False, True, "realism")
        self.assertIn(KREA_RULE_1, p)
        self.assertNotIn("Photo craft for realism and realism_ii", p)
        self.assertNotIn("Name ONE light source", p)

    def test_a_family_with_no_file_is_untouched_when_on(self):
        # zimage/anima/qwen turns write exactly as today, toggle or not.
        for recipe in ("zimage", "anima", "qwen_image"):
            with self.subTest(recipe=recipe), \
                    patch.object(server, "load_config", return_value=_cfg(True)):
                p = server.writer_system_prompt(True, True, recipe)
            self.assertIn(PIXAL_CRAFT, p)
            self.assertNotIn(KREA_RULE_1, p)

    def test_identity_edit_keeps_its_edit_instructions_line_in_both_positions(self):
        for official in (False, True):
            with self.subTest(official=official), \
                    patch.object(server, "load_config", return_value=_cfg(official)):
                local = server.writer_system_prompt(True, True, "identity_edit")
                cloud = server.writer_system_prompt(False, True, "identity_edit")
            self.assertIn("Write EDIT instructions", local)
            self.assertIn("Write EDIT INSTRUCTIONS relative to the source", cloud)

    def test_the_contract_paragraph_rides_after_the_official_text(self):
        # The one Pixal addition in the On position: nsfw=true overrides rule
        # 8. It is not craft - it is the contract with the renderer, so it
        # sits after the official text, before TURN POLICY.
        with patch.object(server, "load_config", return_value=_cfg(True)):
            p = server.writer_system_prompt(True, True, "realism")
        self.assertIn("Preserve User Medium", p)   # Krea rule 9, the last rule
        self.assertLess(p.index("Preserve User Medium"),
                        p.index("nsfw=true"))
        self.assertLess(p.index("nsfw=true"), p.index("TURN POLICY"))
        self.assertIn("rule 8", p)

    def test_the_end_contract_is_still_the_last_thing_in_the_prompt(self):
        # _inline_tools appends RENDER MECHANICS inside llm_call; the official
        # splice lands before it, never after.
        with patch.object(server, "load_config", return_value=_cfg(True)):
            p = server.writer_system_prompt(True, True, "realism")
        out = server._inline_tools([{"role": "system", "content": p}],
                                   server.TOOLS_LOCAL)
        content = out[0]["content"]
        self.assertGreater(content.index("RENDER MECHANICS"),
                           content.index(KREA_RULE_1))
        self.assertTrue(content.endswith("never a second question."))


class SettingsRoundTripTests(unittest.TestCase):
    """llm.official_prompting rides /api/settings like local_keep."""

    def _full_cfg(self, llm=None):
        return {"llm": {"base_url": "", "model": "", **(llm or {})},
                "critic": {"model": ""}, "upscale": {}, "edit": {}, "vae": {},
                "pid": {}, "video": {"default_engine": "", "default_model": ""},
                "extra_model_roots": [],
                "comfy_editor": False, "comfy_console": "tui",
                "explicit": "auto", "vram_profile": "auto"}

    def _patched(self, cfg, saved):
        return patch.object(server, "load_config", return_value=cfg), \
            patch.object(server, "model_catalog", return_value=[]), \
            patch.object(server, "_video_asset", side_effect=lambda _k, r: r), \
            patch.object(server, "h3_upscale_available", return_value=True), \
            patch.object(server, "refresh_comfy_nodes", AsyncMock()), \
            patch.object(server, "save_config",
                         side_effect=lambda c: saved.append(c))

    def test_the_key_round_trips(self):
        cfg, saved = self._full_cfg(), []
        patches = self._patched(cfg, saved)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            post = asyncio.run(server.settings_post(
                FakeRequest({"llm": {"official_prompting": True}})))
            self.assertEqual(post.status, 200)
            self.assertTrue(cfg["llm"]["official_prompting"])
            self.assertTrue(saved, "settings_post never saved")
            response = asyncio.run(server.settings_get(FakeRequest({})))
        llm = json.loads(response.text)["llm"]
        self.assertTrue(llm["official_prompting"])
        self.assertEqual(llm["official_families"], ["krea2"])

    def test_settings_get_defaults_on(self):
        cfg, saved = self._full_cfg(), []
        patches = self._patched(cfg, saved)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = asyncio.run(server.settings_get(FakeRequest({})))
        llm = json.loads(response.text)["llm"]
        self.assertTrue(llm["official_prompting"])

    def test_load_config_carries_the_default(self):
        # a fresh install: no config.json at all
        with TemporaryDirectory() as td, \
                patch.object(server, "CONFIG", Path(td) / "config.json"):
            self.assertTrue(server.load_config()["llm"]["official_prompting"])


class BrainTabRowTests(unittest.TestCase):
    """The row under the brain picker, by static source analysis."""

    def _brain_tab(self):
        block = JSX.split('{tab === "brain" &&', 1)[1]
        return block.split('{tab === "about" &&', 1)[0]

    def test_the_row_sits_directly_under_the_brain_picker(self):
        brain = self._brain_tab()
        self.assertIn("Official prompting", brain)
        self.assertLess(brain.index("Official prompting"),
                        brain.index("<GroupLabel>vision</GroupLabel>"),
                        "the row drifted below the vision cluster")

    def test_the_row_has_its_tip(self):
        brain = self._brain_tab()
        tip = re.search(r'Official prompting <InfoTip text="([^"]+)"', brain)
        self.assertIsNotNone(tip, "the Official prompting row lost its InfoTip")
        self.assertIn("model's makers recommend", tip.group(1))
        self.assertIn("Pixal's photo-craft rules", tip.group(1))

    def test_the_row_posts_the_config_key(self):
        brain = self._brain_tab()
        self.assertRegex(brain, r"apply\(\{ llm: \{ official_prompting")

    def test_the_subline_is_the_server_published_family_list(self):
        brain = self._brain_tab()
        self.assertIn("gloss={officialGloss}", brain)
        self.assertIn("officialFamilies.map(familyName)", JSX)
        self.assertIn("d.llm.official_families", JSX)


class _FakeComfyResp:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return {"prompt_id": "deadbeefcafe1234"}


class _FakeComfySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, *args, **kwargs):
        return _FakeComfyResp()


def _submit_with(spec_args):
    """HUB.submit with every side effect stubbed: scene gate, graph build,
    VRAM butler, the ComfyUI POST and the completion watcher."""
    hub = server.Hub()
    hub.broadcast = lambda **_kw: None

    async def _no_vram(*a, **k):
        return None

    async def _no_watch(*a, **k):
        return None

    hub.ensure_vram = _no_vram
    hub.watch = _no_watch

    def fake_builder(scene, seed, **kw):
        return ({"1": {"class_type": "Stub", "inputs": {}}}, "full",
                {"model": "stub.safetensors"})

    with patch.object(server, "scene_gate",
                      lambda template, scene, verbatim=False, **_kw: (scene, None)), \
         patch.dict(server.BUILDERS, {"realism": fake_builder}), \
         patch.object(server, "validate_job_model_info", lambda *a, **k: None), \
         patch.object(server, "_lora_warning_text", lambda _w: ""), \
         patch.object(server, "_h3_warning_text", lambda _w: ""), \
         patch.object(server.aiohttp, "ClientSession",
                      lambda *a, **k: _FakeComfySession()):
        return asyncio.run(hub.submit("cid00000", "chat", "realism",
                                      "a scene the brain wrote", spec_args))


class WriterStampTests(unittest.TestCase):

    def test_a_brain_written_job_carries_the_writer_stamp(self):
        job = _submit_with({"_writer": "official"})
        self.assertEqual(job["info"]["writer"], "official")
        self.assertNotIn("_writer", job["spec"],
                         "the tag leaked into the stored spec")

    def test_a_verbatim_turn_stamp(self):
        job = _submit_with({"_writer": "verbatim"})
        self.assertEqual(job["info"]["writer"], "verbatim")

    def test_a_job_without_the_tag_carries_no_stamp(self):
        job = _submit_with({})
        self.assertNotIn("writer", job["info"])


if __name__ == "__main__":
    unittest.main()
