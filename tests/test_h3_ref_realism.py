"""1.1.4b - the MiniMax H3 reference-realism port.

One session (2026-08-30, docs/2026-08-30-h3-ref-realism.md) spent finding out
why a reference-conditioned still looked like a render instead of a
photograph. This file pins the parts of that answer that reached the product.

What these tests pin:

  OneFrame      - with the ComfyUI-MM-1Frame node and MiniMax's T1 image VAE
                  present, the reference still builds a true T=1 graph: the
                  one-frame conditioning node, ONE VAE at both ends, no audio
                  VAE loader, no ImageFromBatch, and the save straight off
                  the decode. Absent either, the byte-identical 5-frame graph
                  it always built. The 2x lane opts out explicitly - its
                  latent upscaler is a 3D upscaler proven on the temporal
                  chunk.
  SkinFinish    - the 1x detail model runs between the decode and the save
                  when installed and enabled, on BOTH still lanes; the
                  Settings toggle and the file's absence each turn it off,
                  and off means the graph has no trace of it. The canvas is
                  never resized: 1x is 1x, and the session's CAS+downscale
                  pair is deliberately not here.
  Wardrobe      - THE regression. The wardrobe lock is the last thing in the
                  shot description, asserted on the assembled PROMPT. 1.1.3b
                  made it last in the caption and the builder then wrapped a
                  sentence around it, which put "nothing in the frame moves"
                  in the position that decides whether she stays dressed -
                  reproduced at one seed on both spines, both undressed.
  Signs         - a sign whose words are not in the caption is scrubbed; a
                  sign that spells itself is untouched; a caption that is
                  nothing but a sign refuses the repair rather than gutting
                  itself.
  Checkpoint    - an installed fl2va/ref2va hybrid is preferred over stock
                  ref2va when nothing was asked for, b30-49 by name; an
                  explicit pick always wins; no hybrid changes nothing.
  EndContract   - the three points the shared craft block was quietly
                  winning: the caption budget, the fixture in the shot, and
                  naming shoes in a waist-up frame. Restated last, where a
                  small model actually reads them, for the H3 still recipes
                  only and only when prompt enhance is on.
  Director      - SYSTEM_LOCAL's h3_ref_still line carries the corrected
                  lighting rule (9.80's lamps-in-frame half was retracted
                  the same day), the word budget and the sign rule.

Same sanctioned simulation as every sibling file: stubbed catalog, stubbed
character, no generation, no ComfyUI, no GPU.
"""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_h3_ref_realism", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

STOCK = server.H3_MODEL
REF2VA = server.H3_REF2V_MODEL
HYBRID_B30 = "Minimax H3\\minimax_h3_hybrid_fl2va_ref2va_b30-49-int8.safetensors"
HYBRID_B20 = "Minimax H3\\minimax_h3_hybrid_fl2va_ref2va_b20-49-int8.safetensors"

CHARACTER = {"id": "mia", "name": "Mia", "age": 24, "race": "Korean",
             "sex": "female", "style": "silver pixie cut, lean runner's build",
             "identity_ref": "mia.png"}


def entries(root, *, image_vae=False, skin=False, hybrids=()):
    """This box's H3 stack as catalog entries, with the two optional 1.1.4b
    assets switchable - they are exactly what the capability probes read."""
    def add(kind, rel):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": 1, "mtime": 0.0}
    out = [add("diffusion_models", STOCK),
           add("diffusion_models", REF2VA),
           add("vae", server.H3_VIDEO_VAE),
           add("vae", server.H3_AUDIO_VAE),
           add("text_encoders", server.H3_CLIP)]
    out += [add("diffusion_models", rel) for rel in hybrids]
    if image_vae:
        out.append(add("vae", server.H3_IMAGE_VAE))
    if skin:
        # the retired skin1x weights, still on disk in the wild (10.1):
        # their presence must mean nothing to any builder now
        out.append(add("upscale_models", "1x-ITF-SkinDiffDetail-Lite-v1.pth"))
    return out


def stub_catalog(rows):
    return lambda kind=None: [e for e in rows if kind in (None, e["kind"])]


class _Lane(unittest.TestCase):
    """One builder call against a stubbed box."""

    def build(self, scene="A red barn at dusk", *, image_vae=False, skin=False,
              hybrids=(), node=True, builder=None, **kwargs):
        builder = builder or server.build_h3_ref_still
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / CHARACTER["identity_ref"]).write_bytes(b"ref")
            names = frozenset({server.H3_ONE_FRAME_NODE} if node else set())
            cfg = {"still": {"skin_finish": True}}
            with patch.object(server, "CDIR", root), \
                 patch.object(server, "CHARACTERS", {CHARACTER["id"]: CHARACTER}), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "model_roots", return_value=[]), \
                 patch.object(server, "load_config", return_value=cfg), \
                 patch.dict(server._COMFY_NODES, {"names": names}), \
                 patch.object(server, "model_catalog",
                              side_effect=stub_catalog(
                                  entries(root, image_vae=image_vae, skin=skin,
                                          hybrids=hybrids))):
                kwargs.setdefault("character", "mia")
                return builder(scene, 424242, **kwargs)


class OneFrameTests(_Lane):
    """The T=1 spine, and the 5-frame one it never replaces by force."""

    def test_the_one_frame_graph_drops_four_frames_and_a_vae(self):
        g, _cap, info = self.build(image_vae=True)
        self.assertEqual(g["6"]["class_type"], server.H3_ONE_FRAME_NODE)
        # No audio VAE: unlike MiniMaxH3ReferenceToVideo, the one-frame node
        # does not take one, so the loader that only existed to satisfy that
        # input is gone from the graph entirely.
        self.assertNotIn("4", g)
        self.assertNotIn("audio_vae", g["6"]["inputs"])
        self.assertNotIn("length", g["6"]["inputs"])
        # One VAE, both ends. The image VAE's 116 encoder tensors are
        # bit-identical to the video VAE's, so encoding references through
        # it is the same arithmetic and the second VAE is pure VRAM.
        self.assertEqual(g["3"]["inputs"]["vae_name"], server.H3_IMAGE_VAE)
        self.assertEqual(g["6"]["inputs"]["vae"], ["3", 0])
        self.assertEqual(g["12"]["inputs"]["vae"], ["3", 0])
        # Nothing to grab frame 0 out of - the latent IS one frame.
        self.assertNotIn("13", g)
        self.assertTrue(info["one_frame"])
        self.assertEqual(info["vae"], "minimax_h3_t1_image_vae_step1597")

    def test_without_the_vae_it_is_the_five_frame_graph(self):
        g, _cap, info = self.build(image_vae=False)
        self.assertEqual(g["6"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(g["6"]["inputs"]["length"], 5)
        self.assertEqual(g["4"]["inputs"]["vae_name"], server.H3_AUDIO_VAE)
        self.assertEqual(g["3"]["inputs"]["vae_name"], server.H3_VIDEO_VAE)
        self.assertEqual(g["13"]["class_type"], "ImageFromBatch")
        self.assertEqual(g["13"]["inputs"]["batch_index"], 0)
        self.assertFalse(info["one_frame"])

    def test_without_the_node_it_is_the_five_frame_graph(self):
        # The VAE is there; the pack is not. Either absence is enough.
        g, _cap, info = self.build(image_vae=True, node=False)
        self.assertEqual(g["6"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertFalse(info["one_frame"])

    def test_the_two_spines_differ_only_where_they_must(self):
        one, _c1, _i1 = self.build(image_vae=True)
        five, _c2, _i2 = self.build(image_vae=False)
        shared = ("1", "2", "7", "8", "9", "10", "11")
        for nid in shared:
            self.assertEqual(one[nid], five[nid], nid)
        self.assertEqual(one["6"]["inputs"]["prompt"],
                         five["6"]["inputs"]["prompt"])
        self.assertEqual(set(five) - set(one), {"4", "13"})
        self.assertEqual(set(one) - set(five), set())

    def test_the_2x_lane_keeps_the_five_frame_spine(self):
        # MMH3LatentUpscaleWithModelParams is a 3D latent upscaler and the
        # refine was measured on the temporal chunk, so the refine lane opts
        # out by name rather than by luck.
        with patch.object(server, "h3_upscale_available", return_value=True), \
             patch.object(server, "_video_asset",
                          side_effect=lambda kind, rel: rel):
            g, _cap, info = self.build(image_vae=True,
                                       builder=server.build_h3_ref_still_2x)
        self.assertEqual(g["6"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertFalse(info["one_frame"])
        self.assertIn("up:sample", g)

    def test_the_probe_needs_both_halves(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            both = entries(root, image_vae=True)
            with patch.object(server, "model_catalog",
                              side_effect=stub_catalog(both)), \
                 patch.dict(server._COMFY_NODES,
                            {"names": frozenset({server.H3_ONE_FRAME_NODE})}):
                self.assertTrue(server.h3_one_frame_available())
            with patch.object(server, "model_catalog",
                              side_effect=stub_catalog(both)), \
                 patch.dict(server._COMFY_NODES, {"names": frozenset()}):
                self.assertFalse(server.h3_one_frame_available())
            # An unprobed node list is not evidence of absence: the VAE on
            # disk is the whole verdict, the h3_upscale_available shape.
            with patch.object(server, "model_catalog",
                              side_effect=stub_catalog(both)), \
                 patch.dict(server._COMFY_NODES, {"names": None}):
                self.assertTrue(server.h3_one_frame_available())


class FilmGrainTests(_Lane):
    """10.1: skin1x is retired - it read as skin only on close portraits and
    as posterization anywhere wider, rejected twice at 1:1 (Jesse: "that
    skin 1 ... just didnt do a good job"). The judged dewax film grain holds
    the finisher seat, and it runs on the DELIVERED frame - so the builders
    are finish-free by construction, whatever a legacy config still says."""

    def test_no_builder_emits_a_finish_node_even_with_the_legacy_config(self):
        # _Lane.build's cfg still carries skin_finish: True and the skin
        # model file is on disk - the graph must not care.
        g, _cap, info = self.build(image_vae=True, skin=True)
        self.assertNotIn("fin:skin", g)
        self.assertNotIn("fin:model", g)
        self.assertNotIn("skin_finish", info)
        self.assertEqual(g["14"]["inputs"]["images"], ["12", 0])

    def test_the_prompt_only_still_is_finish_free_too(self):
        g, _cap, info = self.build(skin=True, builder=server.build_h3_still,
                                   character=None)
        self.assertNotIn("fin:skin", g)
        self.assertNotIn("skin_finish", info)
        self.assertEqual(g["14"]["inputs"]["images"], ["13", 0])

    def test_grain_is_deterministic_in_the_render_seed(self):
        from PIL import Image
        im = Image.new("RGB", (64, 64), (128, 128, 128))
        a = server.add_film_grain(im, 424242)
        b = server.add_film_grain(im, 424242)
        c = server.add_film_grain(im, 424243)
        self.assertEqual(a.tobytes(), b.tobytes())
        self.assertNotEqual(a.tobytes(), c.tobytes())
        self.assertNotEqual(a.tobytes(), im.tobytes())

    def test_grain_is_monochrome(self):
        # An equal offset on all three channels: on unclipped mid grey the
        # per-channel deltas are identical.
        import numpy as np
        from PIL import Image
        im = Image.new("RGB", (64, 64), (128, 128, 128))
        d = (np.asarray(server.add_film_grain(im, 7), dtype=int)
             - np.asarray(im, dtype=int))
        self.assertTrue((d[..., 0] == d[..., 1]).all())
        self.assertTrue((d[..., 0] == d[..., 2]).all())

    def test_grain_concentrates_in_the_midtones(self):
        import numpy as np
        from PIL import Image
        mid = Image.new("RGB", (128, 128), (128, 128, 128))
        dark = Image.new("RGB", (128, 128), (20, 20, 20))
        dm = (np.asarray(server.add_film_grain(mid, 9), dtype=float)
              - np.asarray(mid, dtype=float)).std()
        dd = (np.asarray(server.add_film_grain(dark, 9), dtype=float)
              - np.asarray(dark, dtype=float)).std()
        self.assertGreater(dm, dd * 1.5)

    def test_the_setting_defaults_off_and_the_dial_defaults_judged(self):
        with patch.object(server, "CONFIG", Path("does-not-exist.json")):
            cfg = server.load_config()["still"]
            self.assertFalse(cfg["film_grain"])
            self.assertEqual(cfg["film_grain_amount"], 1.6)
            self.assertNotIn("skin_finish", cfg)

    def test_a_legacy_skin_finish_config_reads_as_grain_off(self):
        # A 1.1.7b config still carrying the dead key: never a crash,
        # never grain the user did not choose.
        with patch.object(server, "load_config",
                          return_value={"still": {"skin_finish": True}}):
            self.assertFalse(server.still_film_grain_active())
            self.assertEqual(server.still_film_grain_amount(), 1.6)

    def test_the_amount_resolver_clamps_corruption(self):
        for stored, want in ((1.6, 1.6), (0.0, 0.1), (99.0, 8.0),
                             ("nan", 1.6)):
            with patch.object(server, "load_config", return_value={
                    "still": {"film_grain": True,
                              "film_grain_amount": stored}}):
                self.assertEqual(server.still_film_grain_amount(), want)

    def test_the_delivered_wrapper_keeps_the_png_text_chunks(self):
        # The embedded workflow is what the filename convention reads back -
        # de-shine's rule, inherited.
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
        with TemporaryDirectory() as td:
            p = Path(td) / "frame.png"
            meta = PngInfo()
            meta.add_text("prompt", "{}")
            meta.add_text("workflow", "{\"graph\": true}")
            Image.new("RGB", (32, 32), (100, 110, 120)).save(p, pnginfo=meta)
            before = p.read_bytes()
            self.assertTrue(server._film_grain_delivered(p, 424242, 1.6))
            self.assertNotEqual(p.read_bytes(), before)
            with Image.open(p) as out:
                self.assertEqual(out.info.get("workflow"), "{\"graph\": true}")
                self.assertEqual(out.info.get("prompt"), "{}")

class WardrobeLockTests(_Lane):
    """THE regression, on both still lanes.

    1.1.3b moved the lock to the end of the CAPTION and shipped a test that
    asserted exactly that. The builder then wrapped the caption in a sentence
    of its own, so the model's last instruction was still not the lock - and
    on 2026-08-30 the same seed rendered the subject in underwear on both
    spines. These assert on the assembled prompt, which is the only string
    that exists at render time.
    """

    def _shot(self, prompt):
        body = prompt.split("detailed_description:\n", 1)[1]
        return body.split("\n\n")[0].rstrip()

    def test_nothing_follows_the_lock_in_the_shot(self):
        for image_vae in (True, False):
            with self.subTest(one_frame=image_vae):
                g, cap, _info = self.build(image_vae=image_vae)
                shot = self._shot(g["6"]["inputs"]["prompt"])
                self.assertTrue(cap.endswith(
                    "is fully dressed in the clothing described above."))
                self.assertTrue(shot.endswith(cap))

    def test_the_freeze_instruction_leads(self):
        g, _cap, _info = self.build(image_vae=True)
        shot = self._shot(g["6"]["inputs"]["prompt"])
        self.assertIn("the subject holds the pose and nothing in the frame "
                      "moves.", shot)
        self.assertLess(shot.index("nothing in the frame moves"),
                        shot.index("fully dressed"))

    def test_the_prompt_only_still_closes_on_the_lock_too(self):
        g, cap, _info = self.build(builder=server.build_h3_still,
                                   character=None)
        shot = g["6"]["inputs"]["prompt"].split("\n\n")[0].rstrip()
        self.assertTrue(cap.endswith(
            "is fully dressed in the clothing described above."))
        self.assertTrue(shot.endswith(cap))

    def test_the_lock_is_its_own_sentence(self):
        # A scene with no terminal stop used to glue straight onto the lock
        # ("A red barn at dusk She is fully dressed..."), which reads as one
        # clause. Anything that must land gets a stop of its own.
        cap, _ch = server._character_caption("A red barn at dusk", None,
                                             True, False)
        self.assertIn("dusk. She is fully dressed", cap)


class SignTests(unittest.TestCase):
    """Naming a sign without its words is the fastest AI tell there is."""

    def repair(self, cap):
        return server._h3_still_caption_contract(cap)

    def test_an_unspelled_sign_is_scrubbed(self):
        out, repairs = self.repair(
            "She is twenty at a market stall in a grey hoody. "
            "A chalkboard price sign hangs above the fruit.")
        self.assertNotIn("chalkboard", out)
        self.assertNotIn("sign", out)
        self.assertIn("market stall", out)
        self.assertIn("sign: chalkboard", repairs)

    def test_a_spelled_sign_is_untouched(self):
        for cap in ("She is outside a pizza place at night. The red awning "
                    "behind her reads JOE'S PIZZA.",
                    "Two of them on a train. A strip map sign on the wall "
                    "reads 14 ST UNION SQ."):
            with self.subTest(cap=cap[:32]):
                out, repairs = self.repair(cap)
                self.assertNotIn("sign:", " ".join(repairs))
                self.assertIn(cap.rstrip("."), out)

    def test_a_lead_in_dies_with_the_noun(self):
        # reach_back cuts at a clause edge or a determiner, and "a wall
        # covered in graffiti" has neither - the noun alone would leave a
        # dangling "covered in".
        out, _repairs = self.repair("She leans on a wall covered in graffiti.")
        self.assertIn("She leans on a wall.", out)

    def test_the_whole_phrase_dies_not_just_the_modifier(self):
        """The 2026-08-31 regression. Signs borrowed reach_back, which is a
        fatal-WORD rule: after a determiner the word is treated as an
        adjective and only IT dies. On "a chalkboard price sign" that removed
        the adjective and left a sign standing - the exact thing the killer
        exists to prevent - and on "a price sign" it left "a price,"."""
        out, repairs = self.repair(
            "She is twenty, standing at a corner shop counter past a "
            "chalkboard price sign, holding a paper cup in both hands. "
            "She wears a grey hoody.")
        self.assertNotIn("sign", out.lower())
        self.assertNotIn("chalkboard", out.lower())
        self.assertIn("at a corner shop counter, holding a paper cup", out)
        self.assertIn("sign: chalkboard", repairs)

    def test_the_preposition_dies_with_the_phrase(self):
        # Cutting the noun phrase alone leaves "eating chips out of the
        # paper beside, the window..." - the preposition has to go too.
        out, _repairs = self.repair(
            "She is twenty, on a plastic chair in a chip shop at two in the "
            "morning, eating chips out of the paper beside a price sign, the "
            "window behind her black. She wears a cream hoody.")
        self.assertNotIn("sign", out.lower())
        self.assertIn("out of the paper, the window behind her black", out)

    def test_modifiers_die_with_the_noun(self):
        # "a big illuminated billboard advertising something" used to leave
        # "a big illuminated." behind.
        out, _repairs = self.repair(
            "She is twenty, waiting in a laundrette under a big illuminated "
            "billboard advertising something, a bag on the machine beside "
            "her. She wears a black jacket.")
        self.assertNotIn("billboard", out.lower())
        self.assertNotIn("illuminated", out.lower())
        self.assertIn("waiting in a laundrette, a bag on the machine", out)

    def test_a_coordinator_dies_with_the_phrase(self):
        # Found by running the killer over every caption in the ledger: a sign
        # that is one item in a list leaves the conjunction behind, and
        # "printed on a bumper sticker or, with no depth" is not English.
        out, _repairs = self.repair(
            "Letters printed on a bumper sticker or neon sign, with no depth, "
            "filling the frame above her while she waits in a grey hoody.")
        self.assertNotIn("sign", out.lower())
        self.assertIn("on a bumper sticker, with no depth", out)

    def test_a_caption_that_is_only_a_sign_refuses_the_repair(self):
        out, repairs = self.repair("A neon sign glows behind her.")
        self.assertIn("A neon sign glows behind her.", out)
        self.assertIn("kept: sign repair would gut the caption", repairs)

    def test_a_proper_noun_is_not_spelled_text(self):
        # "New York" must not read as lettering and rescue a bare sign.
        out, repairs = self.repair(
            "She is twenty in a laundrette in New York in a crop top, a "
            "banner on the wall behind her.")
        self.assertNotIn("banner", out)
        self.assertIn("New York", out)
        self.assertIn("sign: banner", repairs)

    def test_things_that_are_not_lettering_survive(self):
        # A poster, a label, a screen and an awning can all be real objects
        # with no legible text, so none of them is in the killer's list.
        for noun in ("a poster", "a bottle label", "a phone screen",
                     "a yellow awning"):
            with self.subTest(noun=noun):
                cap = f"She is twenty in a corner shop in a hoody, {noun} behind her."
                out, repairs = self.repair(cap)
                self.assertNotIn("sign:", " ".join(repairs))
                self.assertIn(noun, out)


class CheckpointPreferenceTests(unittest.TestCase):
    """ref2va is the degraded build; a hybrid is preferred, never required."""

    def options(self, rows):
        return patch.object(server, "model_catalog", side_effect=stub_catalog(rows))

    def test_b30_wins_by_name(self):
        with TemporaryDirectory() as td:
            rows = entries(Path(td), hybrids=(HYBRID_B20, HYBRID_B30))
            with self.options(rows), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "model_roots", return_value=[]):
                self.assertEqual(server.h3_ref_preferred_build(), HYBRID_B30)

    def test_the_highest_block_start_wins_without_b30(self):
        with TemporaryDirectory() as td:
            rows = entries(Path(td), hybrids=(HYBRID_B20,))
            with self.options(rows), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "model_roots", return_value=[]):
                self.assertEqual(server.h3_ref_preferred_build(), HYBRID_B20)

    def test_no_hybrid_changes_nothing(self):
        with TemporaryDirectory() as td:
            with self.options(entries(Path(td))), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "model_roots", return_value=[]):
                self.assertIsNone(server.h3_ref_preferred_build())

    def test_the_hybrid_chip_says_what_it_is(self):
        with TemporaryDirectory() as td:
            rows = entries(Path(td), hybrids=(HYBRID_B30,))
            with self.options(rows), \
                 patch.object(server, "adjacent_metadata", return_value={}), \
                 patch.object(server, "model_roots", return_value=[]):
                chip = next(o for o in server.h3_model_options()
                            if "hybrid" in o["id"])
                self.assertIn("FL2VA/REF2VA hybrid", chip["description"])
                self.assertNotIn("Community", chip["description"])
                # It is still a ref2va lane by variant, which is what routes
                # it to the reference still: the name carries both tokens and
                # h3_model_variant resolves that collision to ref2va on
                # purpose (9.0 trap #6).
                self.assertEqual(server.h3_model_variant(chip["id"]),
                                 server.H3_REF2V_MODEL_ID)


class PreferenceInTheLaneTests(_Lane):

    def test_the_lane_takes_the_hybrid_when_nothing_was_asked_for(self):
        g, _cap, info = self.build(image_vae=True, hybrids=(HYBRID_B30,))
        self.assertEqual(g["1"]["inputs"]["unet_name"], HYBRID_B30)
        self.assertEqual(info["model_path"], HYBRID_B30)
        self.assertEqual(info["model_variant"], "ref2va")

    def test_an_explicit_pick_always_wins(self):
        g, _cap, _info = self.build(image_vae=True, hybrids=(HYBRID_B30,),
                                    model=REF2VA)
        self.assertEqual(g["1"]["inputs"]["unet_name"], REF2VA)

    def test_stock_still_runs_where_no_hybrid_is_installed(self):
        g, _cap, _info = self.build(image_vae=True)
        self.assertEqual(g["1"]["inputs"]["unet_name"], REF2VA)


class DirectorLineTests(unittest.TestCase):
    """The half of the contract the server cannot enforce."""

    def line(self):
        return next(l for l in server.SYSTEM_LOCAL.splitlines()
                    if l.startswith("- h3_ref_still:"))

    def test_the_lighting_rule_is_the_corrected_one(self):
        line = self.line()
        self.assertIn("Light arrives from out of frame", line)
        self.assertIn("the room stays lit", line)
        self.assertIn("never name a lamp, bulb or neon", line)
        # 9.80's retracted half, in every spelling it was written in.
        self.assertNotIn("lamps that are in the frame", line)
        self.assertNotIn("INSIDE a real place", line)

    def test_it_carries_the_measured_writing_rules(self):
        line = self.line()
        self.assertIn("About 45 words", line)
        self.assertIn("ONE thing she is in the middle of", line)
        self.assertIn("Write the moment, not the expression", line)
        self.assertIn("spell its words in capitals", line)
        self.assertIn("the label is turned away", line)
        # 9.80's hands rule survived the rewrite.
        self.assertIn("clear of her face", line)


class EndContractTests(unittest.TestCase):
    """The three points the craft block was quietly winning.

    Brief 9.65 measured that a small model obeys the LAST rule it read, so a
    rule that exists only in the middle of the prompt is not really a rule.
    The h3_ref_still template line sits in the middle and disagrees with the
    craft block above it three ways; the contract restates those three at the
    end, where the finding says they land.
    """

    CRAFT = "Write the scene the way the render models were measured to like:"

    def prompt(self, recipe="h3_ref_still", enhance=True, local=True):
        return server.writer_system_prompt(local, enhance, recipe)

    def test_every_h3_still_recipe_carries_it(self):
        for recipe in ("h3_still", "h3_still_2x",
                       "h3_ref_still", "h3_ref_still_2x"):
            with self.subTest(recipe=recipe):
                self.assertIn("H3 STILL CONTRACT", self.prompt(recipe))

    def test_it_sits_after_the_craft_block_and_before_the_turn_policy(self):
        """Position is the mechanism, and the naive reading of 9.65 got it
        wrong. "Obeys the last rule it read" is not "put it at the very end":
        the end of the prompt holds TURN_POLICY and the enhance policy, which
        are about WHEN to call the tool, and a craft rule stranded past them
        is cut off from every other craft rule. Measured over 12 turns an arm
        at the brain's own temperature, moving it here beat the dead-last
        position on every count - fixtures 2/12 -> 1/12, shoes 3/12 -> 1/12,
        words 72.0 -> 69.5 - and both contract arms called generate 12/12
        against 10/12 with no contract at all."""
        p = self.prompt()
        craft = p.index(self.CRAFT)
        contract = p.index("H3 STILL CONTRACT")
        policy = p.index("TURN POLICY - decide before using a tool:")
        self.assertLess(craft, contract, "the contract precedes what it overrides")
        self.assertLess(contract, policy, "the contract fell past the turn policy")

    def test_a_turn_without_one_is_byte_identical(self):
        # The contract carries its own newline so a recipe that has none adds
        # nothing at all - the pre-contract prompt, to the byte.
        base = server.SYSTEM_LOCAL + server.TURN_POLICY + \
            server.PROMPT_ENHANCE_ON_POLICY
        with patch.object(server, "load_config",
                          return_value={"llm": {"official_prompting": False}}):
            self.assertEqual(server.writer_system_prompt(True, True, "realism"),
                             base)

    def test_no_other_recipe_carries_one(self):
        for recipe in ("realism", "realism_ii", "identity_edit", "anima",
                       "fantasy", "qwen_image"):
            with self.subTest(recipe=recipe):
                self.assertNotIn("H3 STILL CONTRACT", self.prompt(recipe))

    def test_prompt_enhance_off_is_exempt(self):
        # Enhance-off promises the user's own words reach the sampler
        # unrewritten; a word budget cannot hold and be verbatim at once.
        self.assertNotIn("H3 STILL CONTRACT", self.prompt(enhance=False))

    def test_both_writers_get_it(self):
        for local in (True, False):
            with self.subTest(local=local):
                self.assertIn("H3 STILL CONTRACT", self.prompt(local=local))

    def test_three_points_is_the_ceiling(self):
        # 9.65 again: past about three, an end contract stops landing and
        # becomes one more block to skim.
        points = [l for l in server._H3_STILL_END_CONTRACT.splitlines()
                  if l.startswith("- ")]
        self.assertEqual(len(points), 3, points)

    def test_it_outranks_official_prompting_too(self):
        # An official file replaces the craft block; it does not replace this.
        # MiniMax's own guide asks for 350-500 words with the lighting
        # described explicitly - written for video, and it would take the
        # still lane apart.
        with patch.object(server, "_OFFICIAL_PROMPTS",
                          {"minimax_h3": "Official craft goes here."}), \
             patch.object(server, "load_config",
                          return_value={"llm": {"official_prompting": True}}):
            p = self.prompt()
        self.assertIn("Official craft goes here.", p)
        self.assertNotIn(self.CRAFT, p)
        self.assertLess(p.index("Official craft goes here."),
                        p.index("H3 STILL CONTRACT"))

    def test_it_still_names_what_it_overturns(self):
        """The staleness guard: reword the craft block and this fails, rather
        than the contract silently arguing with rules that no longer exist."""
        craft = server.SYSTEM_LOCAL
        self.assertIn("60-130 words", craft)
        self.assertIn("ONE named light source with a direction", craft)
        self.assertIn("top, bottom, shoes", craft)
        contract = server._H3_STILL_END_CONTRACT
        self.assertIn("about forty-five words", contract)
        self.assertIn("light comes from outside the frame", contract)
        self.assertIn("Waist-up or closer", contract)

    def test_every_rule_is_phrased_positively(self):
        """Measured 2026-08-31, six asks at temperature 0. The first wording
        said "About 45 words, not 60-130" and "Name no lamp, bulb, sconce or
        neon"; it cut fixtures not at all (3/6 both arms) and produced a
        caption reading "the taxi interior glows with warm ambient light from
        above, but no lamp or bulb is visible" - the prohibition copied
        straight into the caption as a negation, which this model family has
        no representation of. Rewritten positively, fixtures went 3/6 -> 0/6.
        A rule the writer can copy will be copied, so none is a thing not to
        do."""
        for line in server._H3_STILL_END_CONTRACT.splitlines():
            if not line.startswith("- "):
                continue
            with self.subTest(line=line[:48]):
                for banned in (" not ", " no ", "never ", "Never ", "n't "):
                    self.assertNotIn(banned, line)

    def test_an_unknown_recipe_is_harmless(self):
        self.assertEqual(server.recipe_end_contract("nope", True), "")
        self.assertEqual(server.recipe_end_contract(None, True), "")


if __name__ == "__main__":
    unittest.main()
