"""One family table, read by both classifiers (brief 9.19a).

`model_profile` and `lora_profile` used to be two hand-written string ladders
that knew different numbers of families - the model ladder recognised six, the
LoRA ladder two, so an Anima, Klein or Qwen-Image LoRA was `unknown` *by
construction* and `lora_stack` dropped every one of them before the sampler
(172 of 415 LoRAs on the box this was written against). Both classifiers now
resolve through `install/families.json`: a family is a ROW, and adding one is
data, not a new `elif`.

What these tests pin:

  BothClassifiersAgree   - the drift-stopper. Iterates the TABLE'S ROWS (never
                           a hand-listed pair) and proves model_profile and
                           lora_profile file every family the same way, by
                           folder hint and by baseModel string.
  FictionalFamily        - a family added as a row classifies with NO code
                           change. If this needs an edit to pass, the design
                           is still hardcoded.
  RealFamiliesReachLoras - an Anima, a Klein and a Qwen-Image LoRA classify to
                           their real family instead of `unknown`.
  MetadataBeatsFolder    - resolution order: sidecar > by-hash (9.19b hook) >
                           safetensors header > folder hint.
  ZImageVariantRule      - the base/turbo split survives the refactor.
  ModelProfileNoRegress  - every family model_profile knew before is still
                           recognised, unsupported markers included.
"""

import json
import os
import struct
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

NEUTRAL = "probe.safetensors"          # matches no shipped row's path hints


def _no_disk(self):
    """No sidecar, no model roots, no by-hash record: the classifier sees only
    the rel path and whatever one patch adds back."""
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def _path_probe(row):
    """A rel path this row's own folder hints claim, and no earlier row's."""
    if row.get("path_prefix"):
        return row["path_prefix"][0] + "probe.safetensors"
    if row.get("path_contains"):
        return "_probe\\" + row["path_contains"][0] + "_x.safetensors"
    group = row["path_contains_all"][0]
    return "_probe\\" + "_".join(group) + "_x.safetensors"


def _write_safetensors(path, metadata):
    header = json.dumps({"__metadata__": metadata}).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header)


class BothClassifiersAgree(unittest.TestCase):
    """The test that stops the ladders drifting again: driven by the table's
    rows, so a row added tomorrow is covered the moment it lands."""

    def test_every_row_is_well_formed(self):
        self.assertGreaterEqual(len(server.FAMILY_TABLE), 6)
        ids = set()
        for row in server.FAMILY_TABLE:
            with self.subTest(family=row.get("id")):
                self.assertTrue(row["id"] and row["id"] not in ids)
                ids.add(row["id"])
                self.assertTrue(row.get("base_model") or row.get("path_prefix")
                                or row.get("path_contains") or row.get("path_contains_all"),
                                "a family row needs at least one way to recognise its files")

    def test_folder_hint_agrees(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            for row in server.FAMILY_TABLE:
                probe = _path_probe(row)
                with self.subTest(family=row["id"], probe=probe):
                    self.assertEqual(server.model_profile(probe)["family"], row["id"])
                    self.assertEqual(server.lora_profile(probe)["family"], row["id"])

    def test_base_model_string_agrees(self):
        sidecar, roots = _no_disk(self)
        for row in server.FAMILY_TABLE:
            token = (row.get("base_model") or [None])[0]
            if token is None:
                continue
            with self.subTest(family=row["id"], token=token):
                with sidecar, roots, \
                        patch.object(server, "adjacent_metadata",
                                     return_value={"base_model": token}):
                    self.assertEqual(server.model_profile(NEUTRAL)["family"], row["id"])
                    self.assertEqual(server.lora_profile(NEUTRAL)["family"], row["id"])


class FictionalFamily(unittest.TestCase):
    """A family added as a row classifies with no code change - folder hint,
    baseModel string, and the lora_stack compatibility gate all included."""

    ROW = {"id": "testvale", "base_model": ["testvale"],
           "path_prefix": ["testvale\\"], "variant": "any"}

    def test_row_only_addition(self):
        sidecar, roots = _no_disk(self)
        server.FAMILY_TABLE.append(self.ROW)
        try:
            with sidecar, roots:
                self.assertEqual(server.model_profile("testvale\\probe.safetensors")["family"],
                                 "testvale")
                self.assertEqual(server.lora_profile("testvale\\probe.safetensors")["family"],
                                 "testvale")
            with roots, patch.object(server, "adjacent_metadata",
                                     return_value={"base_model": "TestVale Turbo"}):
                self.assertEqual(server.lora_profile(NEUTRAL)["family"], "testvale")
            with sidecar, roots, \
                    patch.object(server, "resolve_lora", side_effect=lambda name: name):
                kept, dropped = server.lora_stack(["testvale\\probe.safetensors:0.7"],
                                                  family="testvale")
                self.assertEqual([rel for rel, _st in kept], ["testvale\\probe.safetensors"])
                self.assertEqual(dropped, [])
                kept, dropped = server.lora_stack(["testvale\\probe.safetensors:0.7"],
                                                  family="krea2")
                self.assertEqual(kept, [])
                self.assertEqual(dropped, ["incompatible probe"])
        finally:
            server.FAMILY_TABLE.remove(self.ROW)


class RealFamiliesReachLoras(unittest.TestCase):
    """An Anima, a Klein and a Qwen-Image LoRA classify to their real family
    rather than `unknown` - the reach the old two-family ladder never had."""

    def test_anima_by_folder(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            self.assertEqual(server.lora_profile("Anima\\anima-style.safetensors")["family"],
                             "anima")

    def test_klein_by_sidecar_in_flux_folder(self):
        # The shape that motivated this brief: 26 LoRAs sat in Flux\ declaring
        # "Flux.2 Klein 9B" in their sidecars, unknown to the old ladder.
        _, roots = _no_disk(self)
        with roots, patch.object(server, "adjacent_metadata",
                                 return_value={"base_model": "Flux.2 Klein 9B"}):
            profile = server.lora_profile("Flux\\some-style.safetensors")
        self.assertEqual(profile["family"], "klein")
        self.assertTrue(profile["supported"])

    def test_qwen_image_by_folder(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            self.assertEqual(server.lora_profile(
                "Qwen\\Qwen-Image-Lightning-4steps-V2.0.safetensors")["family"], "qwen_image")

    def test_qwen_edit_by_folder(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            self.assertEqual(server.lora_profile(
                "Qwen\\FireRed-Image-Edit-1.1-Lightning-8steps.safetensors")["family"],
                "qwen_edit")


class MetadataBeatsFolder(unittest.TestCase):
    """Resolution order, most trustworthy first: sidecar, the by-hash record
    (9.19b's hook - a mapping, not a fetch), the safetensors header, and only
    then the folder hint."""

    def test_sidecar_beats_folder(self):
        # Krea 2\ultra_real_v4.safetensors on the real box: filed under Krea 2,
        # its own metadata says FLUX.2 Klein - the file, not the folder, is
        # telling the truth.
        _, roots = _no_disk(self)
        with roots, patch.object(server, "adjacent_metadata",
                                 return_value={"base_model": "Flux.2 Klein 9B"}):
            self.assertEqual(server.lora_profile("Krea 2\\ultra_real_v4.safetensors")["family"],
                             "klein")

    def test_sidecar_beats_by_hash_and_header(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "models"
            _write_safetensors(root / "loras" / "misc" / "probe.safetensors",
                               {"ss_base_model_version": "flux2_klein_9b"})
            with patch.object(server, "model_roots", return_value=[root]), \
                    patch.object(server, "adjacent_metadata",
                                 return_value={"base_model": "ZImageBase"}), \
                    patch.dict(server.BY_HASH_BASE_MODEL,
                               {"misc\\probe.safetensors": "Krea 2"}):
                profile = server.lora_profile("misc\\probe.safetensors")
            self.assertEqual((profile["family"], profile["variant"]), ("zimage", "base"))

    def test_by_hash_beats_header_and_folder(self):
        # 9.19b hook: the record is a plain mapping keyed by lowercased rel.
        # No fetch, no hashing here - only the resolution slot it will fill.
        with TemporaryDirectory() as td:
            root = Path(td) / "models"
            _write_safetensors(root / "loras" / "misc" / "probe.safetensors",
                               {"ss_base_model_version": "flux2_klein_9b"})
            with patch.object(server, "model_roots", return_value=[root]), \
                    patch.object(server, "adjacent_metadata", return_value={}), \
                    patch.dict(server.BY_HASH_BASE_MODEL,
                               {"misc\\probe.safetensors": "ZImageTurbo"}):
                profile = server.lora_profile("misc\\probe.safetensors")
            self.assertEqual((profile["family"], profile["variant"]), ("zimage", "turbo"))
            self.assertEqual(profile["base_model"], "ZImageTurbo")

    def test_header_beats_folder(self):
        # No sidecar, no by-hash record, a folder that says nothing - the
        # safetensors header's own training metadata is the honest answer.
        with TemporaryDirectory() as td:
            root = Path(td) / "models"
            _write_safetensors(root / "loras" / "Krea 2" / "probe.safetensors",
                               {"ss_base_model_version": "flux2_klein_9b"})
            with patch.object(server, "model_roots", return_value=[root]), \
                    patch.object(server, "adjacent_metadata", return_value={}):
                profile = server.lora_profile(os.path.join("Krea 2", "probe.safetensors"))
            self.assertEqual(profile["family"], "klein")


class ZImageVariantRule(unittest.TestCase):
    """The base/turbo split still holds - for the classifier and for the
    lora_stack gate, which now reads the gated variants off the table row
    instead of a hardcoded `family == "zimage"`. GUARD: pinned existing
    behaviour, expected to pass before and after the refactor."""

    def test_lora_variants(self):
        _, roots = _no_disk(self)
        with roots, patch.object(server, "adjacent_metadata",
                                 return_value={"base_model": "ZImageTurbo"}):
            self.assertEqual(server.lora_profile("misc\\speed.safetensors")["variant"], "turbo")
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            self.assertEqual(server.lora_profile("ZImage\\Base\\painter.safetensors")["variant"],
                             "base")
            self.assertEqual(server.lora_profile("ZImage\\painter.safetensors")["variant"], "any")

    def test_model_variants_and_execution_profile(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            turbo = server.model_profile("zit\\z-image-turbo.safetensors")
            base = server.model_profile("zib\\z-image-base.safetensors")
        self.assertEqual((turbo["family"], turbo["variant"]), ("zimage", "turbo"))
        # Turbo moved off the Amazing v4 sigma chain on 2026-09-03: that graph
        # has no KSampler, so it had no scheduler, no shift and no sampler pair
        # to set, which left the preset shelf and every saved style's tuning
        # inert on nine of thirteen Z-Image checkpoints. v4 is still in the
        # table for a model_meta row to point at; nothing reaches it by path.
        self.assertEqual(turbo["execution_profile"], "zimage_turbo")
        self.assertEqual((base["family"], base["variant"]), ("zimage", "base"))
        self.assertEqual(base["execution_profile"], "zimage_base")

    def test_stack_gates_variant_from_the_table(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots, \
                patch.object(server, "resolve_lora", side_effect=lambda name: name):
            kept, dropped = server.lora_stack(
                ["ZImage\\Turbo\\a.safetensors:1.0",
                 "ZImage\\Base\\b.safetensors:1.0",
                 "ZImage\\c.safetensors:1.0"],
                family="zimage", variant="base")
        self.assertEqual([rel for rel, _st in kept],
                         ["ZImage\\Base\\b.safetensors", "ZImage\\c.safetensors"])
        self.assertEqual(dropped, ["incompatible a"])


class ModelProfileNoRegress(unittest.TestCase):
    """Every family model_profile knew before is still recognised - including
    the unsupported markers that keep video/audio/auxiliary weights out of the
    still-image picker. GUARD: pinned existing behaviour."""

    PROBES = [
        ("zit\\z-image-turbo.safetensors", "zimage", True),
        ("Anima\\anima-base-v1.0.safetensors", "anima", True),
        ("Qwen\\qwen-image-edit.safetensors", "qwen_edit", True),
        ("Qwen\\qwen-image.safetensors", "qwen_image", True),
        ("Krea 2\\krea2_turbo_int8_convrot.safetensors", "krea2", True),
        ("Klein\\flux2-klein-9b.safetensors", "klein", True),
        ("Flux\\flux1-dev.safetensors", "flux", False),
        # 9.58: H3 builds file under their own family now - fl2va runs the
        # h3_still recipe; 9.67 gave ref2va its own still (h3_ref_still), so
        # both are supported. LTX keeps the plain "video" classification.
        ("Minimax H3\\minimax_h3_fl2va.safetensors", "minimax_h3", True),
        ("Minimax H3\\minimax_h3_ref2va.safetensors", "minimax_h3", True),
        ("LTX2\\ltx-2.5-22b.safetensors", "video", False),
        ("audio\\melband_roformer.safetensors", "audio", False),
        ("nvidia_pid\\decoder.safetensors", "auxiliary", False),
        ("misc\\whatever.safetensors", "unknown", False),
    ]

    def test_families(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            for probe, family, supported in self.PROBES:
                with self.subTest(probe=probe):
                    profile = server.model_profile(probe)
                    self.assertEqual(profile["family"], family)
                    self.assertEqual(profile["supported"], supported)

    def test_source_only_marks(self):
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            self.assertTrue(server.model_profile("Qwen\\qwen-image-edit.safetensors")
                            .get("source_only"))
            self.assertIsNone(server.model_profile("Krea 2\\krea2_turbo.safetensors")
                              .get("source_only"))

    def test_klein_is_not_source_only(self):
        """FLUX.2 Klein is one unified model: text-to-image AND editing.

        It carried source_only until 2026-09-03 for a harness reason (no t2i
        graph existed), not a model one. The mark going back would hide
        klein_t2i from the composer's model picker while the recipe still
        listed the build as compatible - a disagreement the picker cannot
        show, so it is asserted here rather than left to be noticed."""
        sidecar, roots = _no_disk(self)
        with sidecar, roots:
            profile = server.model_profile("Klein\\flux2-klein-9b.safetensors")
            self.assertIsNone(profile.get("source_only"))
            recipes = server.compatible_recipes(profile)
            self.assertIn("klein_t2i", recipes)
            self.assertIn("klein_edit", recipes)
            self.assertIn("klein_inpaint", recipes)


if __name__ == "__main__":
    unittest.main()
