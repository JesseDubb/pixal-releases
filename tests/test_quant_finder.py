"""Quant finder: the lighter-build ladder, its two routes, and the quant_hint
flag that makes a vram_note actionable. Zero network (the HF answer is mocked
at the _hf_repo_files boundary), zero filesystem outside TemporaryDirectory."""
import asyncio
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp

_SPEC = spec_from_file_location(
    "pixal_server_quant", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

GB = 1_000_000_000   # the ladder works in the same 1e9 GB that file sizes are quoted in


def candidate(filename, size_gb, fmt, repo="curated/repo", kind="diffusion_models"):
    return {"repo": repo, "filename": filename, "size": int(size_gb * GB),
            "format": fmt, "kind": kind}


def get_request(engine):
    return SimpleNamespace(rel_url=SimpleNamespace(query={"engine": engine}))


class PostRequest:
    def __init__(self, body):
        self.body = body
        self.can_read_body = True

    async def json(self):
        return self.body


def payload(response):
    return json.loads(response.text)


class LadderTests(unittest.TestCase):
    def test_int8_is_preferred_when_it_fits(self):
        ladder = server.pick_quant_rung(
            [candidate("ltx-q8_0.gguf", 12.0, "gguf"),
             candidate("transformer-int8-convrot.safetensors", 15.0, "int8_convrot")],
            24.0)
        picked = [entry for entry in ladder if entry["picked"]]
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["format"], "int8_convrot")

    def test_a_too_big_int8_falls_to_the_largest_fitting_gguf(self):
        ladder = server.pick_quant_rung(
            [candidate("transformer-int8-convrot.safetensors", 21.5, "int8_convrot"),
             candidate("ltx-q4_0.gguf", 11.8, "gguf"),
             candidate("ltx-q4_k_m.gguf", 12.2, "gguf"),
             candidate("ltx-q8_0.gguf", 13.1, "gguf")],
            16.0)
        picked = next(entry for entry in ladder if entry["picked"])
        self.assertEqual(picked["filename"], "ltx-q4_k_m.gguf")
        int8 = next(entry for entry in ladder if entry["format"] == "int8_convrot")
        self.assertFalse(int8["fits"])

    def test_the_fit_line_is_eighty_percent_of_the_budget(self):
        # 0.8 x 16 GB = 12.8 GB: clearly-under fits, clearly-over does not. A
        # weakened or tightened factor flips one of these two.
        ladder = server.pick_quant_rung(
            [candidate("ltx-q4_k_m.gguf", 12.7, "gguf"),
             candidate("ltx-q8_0.gguf", 12.9, "gguf")],
            16.0)
        fits = {entry["filename"]: entry["fits"] for entry in ladder}
        self.assertEqual(fits, {"ltx-q4_k_m.gguf": True, "ltx-q8_0.gguf": False})

    def test_nothing_fits_picks_nothing_but_still_lists_the_smallest(self):
        ladder = server.pick_quant_rung(
            [candidate("transformer-int8-convrot.safetensors", 21.5, "int8_convrot"),
             candidate("ltx-q8_0.gguf", 18.0, "gguf")],
            16.0)
        self.assertFalse(any(entry["picked"] for entry in ladder))
        self.assertFalse(any(entry["fits"] for entry in ladder))
        smallest = min(ladder, key=lambda entry: entry["size"])
        self.assertEqual(smallest["filename"], "ltx-q8_0.gguf")

    def test_nvfp4_is_listed_but_never_auto_picked(self):
        ladder = server.pick_quant_rung(
            [candidate("ltx-q4_k_m.gguf", 12.2, "gguf"),
             candidate("transformer-nvfp4.safetensors", 9.0, "nvfp4")],
            24.0)
        nvfp4 = next(entry for entry in ladder if entry["format"] == "nvfp4")
        self.assertTrue(nvfp4["blackwell_only"])
        self.assertTrue(nvfp4["fits"])       # listed honestly...
        self.assertFalse(nvfp4["picked"])    # ...but never the automatic choice
        picked = next(entry for entry in ladder if entry["picked"])
        self.assertEqual(picked["format"], "gguf")

    def test_the_input_ladder_is_not_mutated(self):
        files = [candidate("ltx-q4_k_m.gguf", 12.2, "gguf")]
        server.pick_quant_rung(files, 24.0)
        self.assertEqual(files[0],
                         {"repo": "curated/repo", "filename": "ltx-q4_k_m.gguf",
                          "size": int(12.2 * GB), "format": "gguf",
                          "kind": "diffusion_models"})


class AlternativesRouteTests(unittest.TestCase):
    HF = {
        "Lightricks/LTX-2.5": [
            {"rfilename": "diffusion_models/ltx-2.5-22b-distilled-transformer-"
                          "comfy-int8-convrot.safetensors", "size": int(21.5 * GB)},
            # the 45GB bf16 source shares the prefix root - it must never list
            {"rfilename": "diffusion_models/ltx-2.5-22b-distilled-transformer-"
                          "bf16.safetensors", "size": int(45.0 * GB)},
            {"rfilename": "README.md", "size": 4200},
        ],
        "Abiray/LTX-2.5-Distilled-GGUF": [
            {"rfilename": "ltx-2.5-distilled-Q8_0.gguf", "size": int(23.0 * GB)},
            {"rfilename": "ltx-2.5-distilled-Q6_K.gguf", "size": int(17.5 * GB)},
            {"rfilename": "ltx-2.5-distilled-Q4_K_M.gguf", "size": int(12.2 * GB)},
        ],
        "DmitryDB/LTX-2.5-ComfyUI-Quants": [
            {"rfilename": "diffusion_models/ltx-2.5-transformer-nvfp4.safetensors",
             "size": int(11.0 * GB)},
        ],
    }

    def _ladder(self, engine, gpu_total):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", {"total": gpu_total}), \
             patch.object(server, "_hf_repo_files",
                          AsyncMock(side_effect=lambda repo: self.HF[repo])):
            return asyncio.run(server.quant_alternatives(get_request(engine)))

    def test_a_16gb_card_gets_the_largest_gguf_that_fits(self):
        response = self._ladder("ltx25", 15.9)
        body = payload(response)
        self.assertEqual(response.status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["budget_gb"], 16.0)
        names = [entry["filename"] for entry in body["files"]]
        self.assertNotIn("README.md", names)                    # not a model file
        self.assertFalse(any("bf16" in name for name in names))  # the 45GB source
        picked = [entry for entry in body["files"] if entry["picked"]]
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["filename"], "ltx-2.5-distilled-Q4_K_M.gguf")
        self.assertEqual(picked[0]["repo"], "Abiray/LTX-2.5-Distilled-GGUF")
        nvfp4 = next(entry for entry in body["files"] if entry["format"] == "nvfp4")
        self.assertTrue(nvfp4["blackwell_only"])
        self.assertFalse(nvfp4["picked"])
        for entry in body["files"]:
            self.assertEqual(set(entry) >= {"repo", "filename", "size", "format",
                                            "kind", "fits", "picked"}, True)

    def test_a_32gb_card_is_offered_the_convrot_int8(self):
        body = payload(self._ladder("ltx25", 31.8))
        picked = next(entry for entry in body["files"] if entry["picked"])
        self.assertEqual(picked["format"], "int8_convrot")
        self.assertIn("int8-convrot", picked["filename"])

    def test_an_unknown_engine_gets_no_ladder(self):
        response = self._ladder("h3", 15.9)
        self.assertEqual(response.status, 404)
        self.assertFalse(payload(response)["ok"])

    def test_huggingface_being_down_is_graceful(self):
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", {"total": 15.9}), \
             patch.object(server, "_hf_repo_files",
                          AsyncMock(side_effect=aiohttp.ClientError("offline"))):
            response = asyncio.run(server.quant_alternatives(get_request("ltx25")))
        self.assertEqual(response.status, 502)
        body = payload(response)
        self.assertFalse(body["ok"])
        self.assertIn("offline", body["error"])


class FetchValidationTests(unittest.TestCase):
    VALID = {"repo": "Abiray/LTX-2.5-Distilled-GGUF",
             "filename": "ltx-2.5-distilled-Q4_K_M.gguf", "kind": "diffusion_models"}

    def test_an_uncurated_repo_is_rejected(self):
        with patch.object(server, "QUANT_FETCH", {"task": None}):
            response = asyncio.run(server.quant_fetch(PostRequest(
                {**self.VALID, "repo": "random/not-curated"})))
        self.assertEqual(response.status, 400)
        self.assertFalse(payload(response)["ok"])

    def test_traversal_and_non_model_names_are_rejected(self):
        for bad in ("../escape.gguf", "sub/../../escape.gguf", "C:\\escape.gguf",
                    "/abs/escape.gguf", "trailing/.gitignore", "notes.txt", ""):
            with self.subTest(bad=bad), \
                 patch.object(server, "QUANT_FETCH", {"task": None}):
                response = asyncio.run(server.quant_fetch(PostRequest(
                    {**self.VALID, "filename": bad})))
            self.assertEqual(response.status, 400, bad)
            self.assertFalse(payload(response)["ok"])

    def test_an_unknown_model_kind_is_rejected(self):
        with patch.object(server, "QUANT_FETCH", {"task": None}):
            response = asyncio.run(server.quant_fetch(PostRequest(
                {**self.VALID, "kind": "../../etc"})))
        self.assertEqual(response.status, 400)
        self.assertFalse(payload(response)["ok"])

    def test_a_second_fetch_is_refused_while_one_runs(self):
        async def run():
            gate = asyncio.Event()

            async def fake_run(*_args, **_kwargs):
                await gate.wait()

            with patch.object(server, "QUANT_FETCH", {"task": None}), \
                 patch.object(server, "_quant_fetch_run", fake_run):
                first = await server.quant_fetch(PostRequest(self.VALID))
                second = await server.quant_fetch(PostRequest(self.VALID))
                task = server.QUANT_FETCH["task"]
                gate.set()
                await task
            return first, second

        first, second = asyncio.run(run())
        self.assertTrue(payload(first)["ok"])
        self.assertFalse(payload(second)["ok"])
        self.assertEqual(payload(second)["error"], "a download is already running")


class QuantHintTests(unittest.TestCase):
    def _engines(self, gpu_total):
        # model_catalog is stubbed for the same reason _video_asset is: the
        # engine dicts must not depend on what this box has on disk (and the
        # stubbed load_config carries no extra_model_roots for the scan).
        with patch.object(server, "load_config",
                          return_value={"vram_profile": "auto"}), \
             patch.object(server.HUB, "gpu", {"total": gpu_total}), \
             patch.object(server, "model_catalog", return_value=[]), \
             patch.object(server, "_video_asset", side_effect=lambda _k, rel: rel):
            return server.video_engine_options()

    def test_a_starved_ltx25_note_is_actionable(self):
        ltx25 = next(engine for engine in self._engines(15.9)
                     if engine["id"] == "ltx25")
        self.assertIn("vram_note", ltx25)
        self.assertTrue(ltx25["quant_hint"])

    def test_h3_has_no_ladder_so_its_note_stays_plain(self):
        h3 = next(engine for engine in self._engines(15.9) if engine["id"] == "h3")
        self.assertIn("vram_note", h3)
        self.assertNotIn("quant_hint", h3)

    def test_the_hint_travels_with_the_family_not_the_note(self):
        # A 32GB card fits ltx25 - no note - but the family still has a ladder,
        # so the hint is attached either way. The UI gates on vram_note.
        ltx25 = next(engine for engine in self._engines(31.8)
                     if engine["id"] == "ltx25")
        self.assertNotIn("vram_note", ltx25)
        self.assertTrue(ltx25["quant_hint"])


if __name__ == "__main__":
    unittest.main()
