"""Brief 10.2 - a re-roll never pays the encoder.

Two identical back-to-back jobs measured live (2026-09-01): cache hit 0/12
both times, ~80-92s each, every loader re-ran - the butler wiped ComfyUI's
node cache to make room for the encoder that the cache made unnecessary.
When a job's encode is provably served by the node cache, the butler now
prices the job WITHOUT the text encoder and takes only non-wiping reclaim
paths.

What these tests pin:

  EncodeSide    - the signature is a stable hash over the encode-side
                  subgraph (the text-encoder loader(s) and every node
                  feeding the encode), exactly as built. LANE-AGNOSTIC:
                  Krea 2 (realism), Z-Image (fantasy), Anima (anime),
                  Klein, H3 still and the H3 i2v video lane all qualify
                  structurally - nothing here keys on a lane's name.
  Equality      - a new seed, an opts-level sampler change, or a DiT-only
                  swap leave the signature alone: ComfyUI's node cache
                  would still serve the encode, so the job must qualify.
  Difference    - one word of the scene, the encoder model, an encoder
                  setting, or an H3 clip-length change flip it: the cache
                  would miss, so the job must NOT qualify.
  FlushEpoch    - every cache-killing event bumps the epoch and drops the
                  anchor: /free with free_memory (either flag route or the
                  butler's), forget_residency (restart / reconnect / OOM /
                  settings). The soft unload and the no-request trim do NOT
                  bump - the node cache survives both.
  Anchor        - only a successfully finalized job with an encode side
                  stores its signature; failures and encoder-less jobs
                  never clobber it.
  WarmButler    - a qualified job prices without the encoder (falls out of
                  `heavy`), never takes the free_memory wipe, and keeps any
                  honest encoder residency claim; one that does not fit
                  even without the encoder falls through to today's
                  full-bill behavior, wipe included.

LIVE-MACHINE RULE: no ComfyUI, no GPU - the card, the clock, the session
and the ledger are all injected, the same sanctioned simulation as every
sibling file.
"""

import io
import time
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_warm_reruns", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

GB = 2**30


# ------------------------------------------------------------ build stubs
# The same sanctioned simulation as the sibling files: stubbed catalog,
# stubbed assets, no generation, no ComfyUI, no GPU.

def model(rel, family, variant="any", **extra):
    return {"rel": rel, "kind": "diffusion_models", "family": family,
            "variant": variant, "supported": True, **extra}


KREA = model("Krea 2\\demo.safetensors", "krea2")
ZBASE = model("ZiB\\demo.safetensors", "zimage", "base")


@contextmanager
def assets(entry):
    """Pretend `entry` is the only installed model, and every LoRA resolves."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(server, "resolve_model_entry",
                                         return_value=entry))
        stack.enter_context(patch.object(server, "_catalog_has",
                                         return_value=True))
        stack.enter_context(patch.object(server, "_catalog_resolve",
                                         side_effect=lambda kind, rel: rel))
        stack.enter_context(patch.object(server, "resolve_lora",
                                         side_effect=lambda name: name))
        yield


def h3_entries(root):
    """This box's H3 stack as catalog entries (the test_h3_still stub)."""
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    return [add("diffusion_models", server.H3_MODEL),
            add("diffusion_models", server.H3_REF2V_MODEL),
            add("vae", server.H3_VIDEO_VAE),
            add("vae", server.H3_AUDIO_VAE),
            add("text_encoders", server.H3_CLIP)]


def klein_entries(root):
    def add(kind, rel, size=1):
        return {"rel": rel, "kind": kind, "root": str(root),
                "size": size, "mtime": 0.0}
    return [add("diffusion_models", server.KLEIN_MODEL),
            add("text_encoders", server.KLEIN_CLIP),
            add("vae", server.KLEIN_VAE)]


def stub_catalog(entries):
    return lambda kind=None: [e for e in entries if kind in (None, e["kind"])]


def no_disk():
    return (patch.object(server, "adjacent_metadata", return_value={}),
            patch.object(server, "model_roots", return_value=[]))


def build_h3(scene, seed, **kwargs):
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        sidecar, roots = no_disk()
        with patch.object(server, "CDIR", root), sidecar, roots, \
                patch.object(server, "model_catalog",
                             side_effect=stub_catalog(h3_entries(root))):
            return server.build_h3_still(scene, seed, **kwargs)


def build_h3_i2v(scene, seed, seconds=5, **kwargs):
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        (root / "input" / "prepared.png").write_bytes(b"prepared")
        with patch.object(server, "CDIR", root), \
             patch.object(server, "_video_asset",
                          side_effect=lambda _kind, _rel: _rel):
            return server.build_h3_i2v(scene, seed, "prepared.png",
                                       seconds=seconds, width=768,
                                       height=1344, model="fl2va",
                                       sparse=False, **kwargs)


def build_klein(instruction, seed):
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "input").mkdir()
        from PIL import Image
        Image.new("RGB", (1232, 1648), (9, 9, 9)).save(root / "input" / "s.png")
        sidecar, roots = no_disk()
        with patch.object(server, "CDIR", root), sidecar, roots, \
             patch.object(server, "model_catalog",
                          side_effect=stub_catalog(klein_entries(root))), \
             patch.object(server, "pick_recipe_model",
                          return_value=model(server.KLEIN_MODEL, "klein",
                                             "edit")), \
             patch.object(server, "_pick_catalog_asset",
                          side_effect=lambda kind, names, *a: names[0]):
            return server.build_klein_edit(instruction, seed, "s.png")


class EncodeSideTests(unittest.TestCase):
    """The encode side is derived from the graph's own structure: the
    text-encoder loaders, what their output reaches short of the sampler
    side, and everything upstream of that. No lane names, no node-name
    tables per lane."""

    def test_the_encoder_loader_is_found_by_its_weight_key_not_a_lane(self):
        g, _cap, _info = build_h3("A red barn at dusk", 424242)
        side, enc = server.encode_side(g)
        self.assertEqual(enc, {server.H3_CLIP})
        self.assertIn("2", side)          # the CLIPLoader
        self.assertIn("6", side)          # the MiniMaxH3 encode node

    def test_the_sampler_side_is_not_encode_side(self):
        g, _cap, _info = build_h3("A red barn at dusk", 424242)
        side, _enc = server.encode_side(g)
        for nid in ("1", "7", "8", "9", "10", "11"):
            # DiT loader, sampler select, scheduler, guider, noise, sampler.
            self.assertNotIn(nid, side)

    def test_a_graph_with_no_text_encoder_has_no_signature(self):
        g = {"u": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": "stub\\heavy.safetensors"}}}
        side, enc = server.encode_side(g)
        self.assertEqual((side, enc), (set(), set()))
        self.assertIsNone(server.encode_signature(g))


class SignatureEqualityTests(unittest.TestCase):
    """Anything ComfyUI's node cache would still serve keeps the signature:
    a new seed, an opts-level sampler change, a DiT-only swap."""

    def test_identical_builds_hash_identically(self):
        g1, _c1, _i1 = build_h3("A red barn at dusk", 424242)
        g2, _c2, _i2 = build_h3("A red barn at dusk", 424242)
        self.assertEqual(server.encode_signature(g1),
                         server.encode_signature(g2))

    def test_a_new_seed_qualifies_lane_agnostic(self):
        """Krea 2, Z-Image, Anima, Klein, H3 still and the H3 i2v video
        lane: two builds differing only in seed share one signature."""
        lanes = {
            "krea2_realism": lambda scene, seed: server.build_realism(
                scene, seed),
            "zimage_fantasy": lambda scene, seed: server.build_fantasy(
                scene, seed),
            "anima_anime": lambda scene, seed: server.build_anime(
                scene, seed),
        }
        for lane, builder in lanes.items():
            with self.subTest(lane=lane):
                entry = KREA if lane == "krea2_realism" else ZBASE
                with assets(entry):
                    g1 = builder("a quiet street at dawn", 1)[0]
                    g2 = builder("a quiet street at dawn", 2)[0]
                self.assertEqual(server.encode_signature(g1),
                                 server.encode_signature(g2))
        with self.subTest(lane="klein_edit"):
            g1 = build_klein("remove her earrings", 5)[0]
            g2 = build_klein("remove her earrings", 6)[0]
            self.assertEqual(server.encode_signature(g1),
                             server.encode_signature(g2))
        with self.subTest(lane="h3_still"):
            g1, _c1, _i1 = build_h3("A red barn at dusk", 1)
            g2, _c2, _i2 = build_h3("A red barn at dusk", 2)
            self.assertEqual(server.encode_signature(g1),
                             server.encode_signature(g2))
        with self.subTest(lane="h3_i2v_video"):
            g1, _b1, _i1 = build_h3_i2v("She turns toward the window.", 987)
            g2, _b2, _i2 = build_h3_i2v("She turns toward the window.", 988)
            self.assertEqual(server.encode_signature(g1),
                             server.encode_signature(g2))

    def test_an_opts_level_sampler_change_qualifies(self):
        """What a sampler pill touches - the seat node's name, the
        scheduler's steps and scheduler - is not encode side."""
        base, _c, _i = build_h3("A red barn at dusk", 424242)
        tuned, _c2, _i2 = build_h3(
            "A red barn at dusk", 424242,
            overrides=[{"node": "7", "input": "sampler_name",
                        "value": "euler"},
                       {"node": "8", "input": "steps", "value": 30},
                       {"node": "8", "input": "scheduler",
                        "value": "karras"}])
        seat = tuned["7"]["inputs"]
        self.assertEqual((seat["sampler_name"], tuned["8"]["inputs"]["steps"],
                          tuned["8"]["inputs"]["scheduler"]),
                         ("euler", 30, "karras"))   # the change really landed
        self.assertEqual(server.encode_signature(base),
                         server.encode_signature(tuned))

    def test_a_dit_only_swap_qualifies(self):
        """The DiT feeds the sampler, never the encode: a same-prompt DiT
        swap leaves the conditioning byte-identical in the node cache, so
        disqualifying it would pay an encoder reload for nothing."""
        g1, _c1, _i1 = build_h3("A red barn at dusk", 424242)
        g2 = deepcopy(g1)
        g2["1"]["inputs"]["unet_name"] = "Minimax H3\\some_finetune.safetensors"
        self.assertEqual(server.encode_signature(g1),
                         server.encode_signature(g2))


class SignatureDifferenceTests(unittest.TestCase):
    """Anything that changes what the encode would compute flips the
    signature - the cache would miss, so warmth must not be claimed."""

    def test_one_word_of_the_scene_flips_it(self):
        g1, _c1, _i1 = build_h3("A red barn at dusk", 424242)
        g2, _c2, _i2 = build_h3("A blue barn at dusk", 424242)
        self.assertNotEqual(server.encode_signature(g1),
                            server.encode_signature(g2))

    def test_the_negative_prompt_is_encode_side(self):
        with assets(KREA):
            plain = server.build_realism("a portrait", 1)[0]
            neg = server.build_realism("a portrait", 1,
                                       negative="waxy skin")[0]
        self.assertNotEqual(server.encode_signature(plain),
                            server.encode_signature(neg))

    def test_the_encoder_model_is_in_the_signature(self):
        g1, _c1, _i1 = build_h3("A red barn at dusk", 424242)
        g2 = deepcopy(g1)
        g2["2"]["inputs"]["clip_name"] = "Qwen\\some_other_encoder.safetensors"
        self.assertNotEqual(server.encode_signature(g1),
                            server.encode_signature(g2))

    def test_an_encoder_setting_is_in_the_signature(self):
        g1, _c1, _i1 = build_h3("A red barn at dusk", 424242)
        g2 = deepcopy(g1)
        g2["2"]["inputs"]["type"] = "fp8"     # CLIP config on the loader
        self.assertNotEqual(server.encode_signature(g1),
                            server.encode_signature(g2))

    def test_an_h3_clip_length_change_flips_it(self):
        """MiniMaxH3ImageToVideo is monolithic - the text encode and the
        latent prep are one node - so a seconds change is a cache miss on
        the encode node itself, and the signature must say so."""
        g1, _b1, _i1 = build_h3_i2v("She turns.", 987)
        g2, _b2, _i2 = build_h3_i2v("She turns.", 987, seconds=10)
        self.assertNotEqual(server.encode_signature(g1),
                            server.encode_signature(g2))


# ------------------------------------------------------------ epoch fakes

class _Session:
    """Just enough aiohttp session: records posts, answers 200 to nothing."""

    def __init__(self):
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, json, timeout):
        self.posts.append((url, json))


class _EpochHub:
    """Epoch state plus the real methods under test, nothing else."""

    def __init__(self):
        self.resident_heavies = {"Krea 2\\m.safetensors": 12 * GB}
        self.critic_hot = True
        self.model_last_used = {}
        self.flush_epoch = 7
        self._warm_encode = ("sig", 7)

    flush_comfy_cache = server.Hub.flush_comfy_cache
    forget_residency = server.Hub.forget_residency
    # getattr so the pre-fix tree fails each TEST (missing feature), not the
    # whole file at collection time.
    note_node_cache_flush = getattr(server.Hub, "note_node_cache_flush", None)


class FlushEpochTests(unittest.IsolatedAsyncioTestCase):
    """Every event that empties (or unknowables) ComfyUI's node-output
    cache bumps the epoch and drops the anchor; the non-wiping paths
    must not."""

    def test_the_bump_increments_and_drops_the_anchor(self):
        hub = _EpochHub()
        hub.note_node_cache_flush("a test flush")
        self.assertEqual(hub.flush_epoch, 8)
        self.assertIsNone(hub._warm_encode)

    def test_the_bump_works_on_a_fresh_process(self):
        """A sidecar start is itself an epoch: no anchor, epoch zero, and
        the first bump needs nothing pre-existing."""
        hub = _EpochHub()
        del hub.flush_epoch
        del hub._warm_encode
        hub.note_node_cache_flush("first contact")
        self.assertEqual(hub.flush_epoch, 1)
        self.assertIsNone(hub._warm_encode)

    async def test_the_free_memory_wipe_bumps(self):
        hub = _EpochHub()
        with patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()):
            await hub.flush_comfy_cache("making room for h3_i2v",
                                        unload=True, free_memory=True)
        self.assertEqual(hub.flush_epoch, 8)
        self.assertIsNone(hub._warm_encode)

    async def test_the_soft_unload_does_not_bump(self):
        """9.48's idle-lane eviction drops weights only - the node-output
        CacheSet survives, so the anchor must too."""
        hub = _EpochHub()
        with patch.object(server.aiohttp, "ClientSession",
                          return_value=_Session()):
            await hub.flush_comfy_cache("idle lane weights",
                                        unload=True, free_memory=False)
        self.assertEqual(hub.flush_epoch, 7)
        self.assertEqual(hub._warm_encode, ("sig", 7))

    async def test_the_no_request_trim_does_not_bump(self):
        hub = _EpochHub()
        with patch.object(server.aiohttp, "ClientSession",
                          Mock(return_value=_Session())) as ctor:
            await hub.flush_comfy_cache("stack already resident",
                                        unload=False)
        ctor.assert_not_called()
        self.assertEqual(hub.flush_epoch, 7)
        self.assertEqual(hub._warm_encode, ("sig", 7))

    def test_forgetting_residency_bumps(self):
        """A (re)boot, a reconnect, an OOM recovery, a settings flush: the
        process or the card is no longer the one the anchor ran on."""
        hub = _EpochHub()
        hub.forget_residency("comfy reconnected")
        self.assertEqual(hub.flush_epoch, 8)
        self.assertIsNone(hub._warm_encode)


# ------------------------------------------------------------ the anchor

class _AnchorHub:
    """Just enough Hub for finalize's bookkeeping (the test_cache_telemetry
    seam), plus the epoch state the anchor rides on."""

    def __init__(self):
        self.critic_hot = False
        self.prev_job_free_min = None
        self.ledgered = []
        self.flush_epoch = 4
        self._warm_encode = None

    def broadcast(self, **kw):
        pass

    def ledger_append(self, entry):
        self.ledgered.append(entry)

    finalize = server.Hub.finalize


def _job(**extra):
    return {"id": "w1", "cid": "c", "template": "h3_ref_still",
            "started": time.time(), "images": [{"filename": "a.png"}],
            "error": None, "scene": "s", "seed": 1, "count": 1,
            "spec": {}, "elapsed": 80.0, **extra}


class AnchorTests(unittest.TestCase):
    """The warm anchor is the signature of the last SUCCESSFULLY finalized
    job on this ComfyUI - nothing else may write it."""

    def test_a_successful_priced_job_stores_its_signature(self):
        hub = _AnchorHub()
        hub.finalize(_job(_encode_sig="sigA"))
        self.assertEqual(hub._warm_encode, ("sigA", 4))

    def test_a_failed_job_never_stores(self):
        hub = _AnchorHub()
        hub._warm_encode = ("older", 4)
        hub.finalize(_job(images=[], error="comfy rejected the graph"))
        self.assertEqual(hub._warm_encode, ("older", 4))

    def test_a_job_without_an_encode_side_never_clobbers(self):
        """A vl look or an encoder-less upscale leaves the anchor standing -
        their run did nothing to the cached conditioning."""
        hub = _AnchorHub()
        hub._warm_encode = ("older", 4)
        hub.finalize(_job())
        self.assertEqual(hub._warm_encode, ("older", 4))

    def test_a_warm_label_with_zero_observed_hits_is_corrected(self):
        """ComfyUI's RAM-pressure cache evicts on its own clock, invisibly
        to the flush epoch: a qualified job can find nothing served (live
        2026-09-01, job c89c9509 - warm-priced, 0/12, encoder paid). The
        ledger may not claim a cache that did not serve."""
        hub = _AnchorHub()
        job = _job(_encode_sig="sigA", info={"warm": "encode-cached"},
                   node_types={"1": "CLIPLoader", "2": "KSampler"},
                   _cached_nodes=[])
        hub.finalize(job)
        self.assertEqual(hub.ledgered[-1]["info"]["warm"], "encode-missed")
        # the encode just RAN, so the cache now holds it: still anchors
        self.assertEqual(hub._warm_encode, ("sigA", 4))

    def test_a_warm_label_with_real_hits_stands(self):
        hub = _AnchorHub()
        job = _job(_encode_sig="sigA", info={"warm": "encode-cached"},
                   node_types={"1": "CLIPLoader", "2": "KSampler"},
                   _cached_nodes=["1"])
        hub.finalize(job)
        self.assertEqual(hub.ledgered[-1]["info"]["warm"], "encode-cached")

    def test_an_unobserved_cache_never_rewrites_the_label(self):
        """No node_types = no observation - an absent websocket read must
        not turn into an accusation."""
        hub = _AnchorHub()
        job = _job(_encode_sig="sigA", info={"warm": "encode-cached"})
        hub.finalize(job)
        self.assertEqual(hub.ledgered[-1]["info"]["warm"], "encode-cached")


# ------------------------------------------------------------ the butler

DIT = "stub\\dit.safetensors"
ENC = "stub\\enc.safetensors"
VAE = "stub\\vae.safetensors"


def warm_graph():
    """A two-heavy lane: DiT loader, encoder loader, VAE loader, an encode
    node, and the sampler tail - the shape every priced lane shares."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": DIT}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ENC}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["2", 0], "text": "a red barn at dusk"}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0],
                         "negative": ["4", 0], "latent_image": ["5", 0],
                         "seed": 1, "steps": 20, "cfg": 4.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
    }


class _WarmHub:
    """Just enough Hub for ensure_vram: state + spies, the real methods,
    an injected card read and an empty ledger."""

    queue_remaining = 0

    def __init__(self, card_total_gb=32.0):
        self.jobs = {}
        self.resident_heavies = {}
        self.model_last_used = {}
        self.job_seq = 0
        self.critic_hot = False
        self.prev_job_free_min = None
        self.gpu = {"total": card_total_gb}
        self.flush_epoch = 1
        self._warm_encode = None
        self.texts = []
        self.flushes = []     # (why, unload, free_memory)
        self.reclaims = []    # (why, target, unload)

    def ledger_read(self):
        return []

    def broadcast(self, **kw):
        if kw.get("type") == "text":
            self.texts.append(kw.get("text"))

    async def flush_comfy_cache(self, why, unload=True, free_memory=True):
        # unload=False is the no-request trim: it sends nothing, so it
        # records nothing - `flushes` is the list of /free POSTS.
        if unload:
            self.flushes.append((why, unload, free_memory))
            self.resident_heavies = {}
            self.model_last_used = {}
            self.critic_hot = False
        return True

    async def reclaim_vram(self, why, target=None, unload=True):
        self.reclaims.append((why, target, unload))
        await self.flush_comfy_cache(why, unload)
        return 1 * GB

    ensure_vram = server.Hub.ensure_vram
    busy_elsewhere = server.Hub.busy_elsewhere
    forget_residency = server.Hub.forget_residency
    note_node_cache_flush = getattr(server.Hub, "note_node_cache_flush", None)
    evict_idle_lane = server.Hub.evict_idle_lane
    rest_brain_for_render = server.Hub.rest_brain_for_render
    note_desktop_weight = server.Hub.note_desktop_weight
    idle_lane_weights = server.Hub.idle_lane_weights
    idle_lane_template = server.Hub.idle_lane_template
    _mark_used = server.Hub._mark_used


def run_butler(hub, sizes, free_gb, template="zimage",
               info=None, ram_gb=64.0):
    """Drive the real ensure_vram with every machine read injected."""
    sizes = {k: int(v * GB) for k, v in sizes.items()}
    with ExitStack() as st:
        st.enter_context(patch.object(
            server, "_weight_file_bytes",
            side_effect=lambda _kinds, rel: sizes.get(rel, 0)))
        st.enter_context(patch.object(
            server, "comfy_vram_free_bytes",
            AsyncMock(return_value=int(free_gb * GB))))
        st.enter_context(patch.object(
            server, "gpu_free_bytes", return_value=int(free_gb * GB)))
        st.enter_context(patch.object(server, "gpu_hogs", return_value=[]))
        st.enter_context(patch.object(
            server, "ram_free_bytes", return_value=int(ram_gb * GB)))
        st.enter_context(patch.object(
            server, "gpu_process_table", return_value=[]))
        st.enter_context(patch.object(
            server, "brain_vram_estimate", return_value=0))
        st.enter_context(patch.object(
            server, "free_brain_vram", AsyncMock(return_value=False)))
        st.enter_context(patch.object(server.asyncio, "sleep", AsyncMock()))
        job = {"id": "w1", "cid": "c"}
        out = io.StringIO()
        with redirect_stdout(out):
            import asyncio as _a
            _a.run(hub.ensure_vram(template, warm_graph(), job,
                                   info or {"canvas_mp": 1.0}))
    return job, out.getvalue()


def anchor(hub, graph, epoch=1):
    """The state a successful prior job on this ComfyUI leaves behind."""
    sig = server.encode_signature(graph)
    hub._warm_encode = (sig, epoch)
    return sig


class WarmButlerTests(unittest.TestCase):
    """The qualifier, the no-encoder pricing and the reclaim governance,
    wired into the real ensure_vram."""

    def test_a_qualified_job_fits_without_the_encoder_and_never_wipes(self):
        """The encoder is the largest heavy here: full pricing needs
        20.5+act+floor, warm pricing 12.5+act+floor. A 20GB-free card only
        fits the warm bill - today's code would wipe to make room."""
        hub = _WarmHub()
        g = warm_graph()
        anchor(hub, g)
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 20)
        self.assertEqual(job.get("_warm"), "encode-cached")
        self.assertEqual(hub.reclaims, [], "a fitting warm job reclaims nothing")
        self.assertEqual(hub.flushes, [], "and never sends /free")
        self.assertIn("warm re-run", out)
        self.assertNotIn("butler skipped", out)
        # The encoder was never claimed and never loaded: the residency
        # books say the DiT alone, not a credit the card cannot back.
        self.assertEqual(hub.resident_heavies, {DIT: 12 * GB})

    def test_a_qualified_job_keeps_an_honest_encoder_claim(self):
        """The encoder was left resident by the previous job: a warm
        re-run neither loads nor evicts it, so the claim survives."""
        hub = _WarmHub()
        hub.resident_heavies = {ENC: 20 * GB}
        g = warm_graph()
        anchor(hub, g)
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 20)
        self.assertEqual(job.get("_warm"), "encode-cached")
        self.assertEqual(hub.resident_heavies,
                         {DIT: 12 * GB, ENC: 20 * GB})

    def test_a_qualified_video_lane_takes_the_warm_path(self):
        """9.39's warm-video path needs every heavy claimed resident; a
        warm re-roll whose encoder was evicted after the last clip now
        qualifies on the no-encoder bill alone - and never wipes."""
        hub = _WarmHub()
        hub.resident_heavies = {DIT: 12 * GB}
        g = warm_graph()
        anchor(hub, g)
        job, out = run_butler(
            hub, {DIT: 12, ENC: 20, VAE: 0.5}, 12, template="h3_i2v",
            info={"canvas_mp": 1.0, "frames": 121})
        self.assertEqual(job.get("_warm"), "encode-cached")
        self.assertEqual(hub.flushes, [], "a warm clip never sends /free")
        self.assertEqual(hub.reclaims, [])
        self.assertEqual(hub.resident_heavies, {DIT: 12 * GB})

    def test_a_stale_epoch_prices_the_full_stack_and_wipes(self):
        """A flush since the anchor: the encode is gone, so the job is
        today's job - full bill, make-room reclaim, free_memory wipe."""
        hub = _WarmHub()
        hub.flush_epoch = 2          # something flushed after the anchor
        g = warm_graph()
        anchor(hub, g, epoch=1)
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 20)
        self.assertIsNone(job.get("_warm"))
        self.assertTrue(hub.reclaims, "the make-room reclaim must fire")
        self.assertIn((True, True),
                      [(u, f) for _w, u, f in hub.flushes],
                      "and it is the free_memory wipe, not the trim")

    def test_no_anchor_is_todays_behavior(self):
        """A fresh sidecar (or a first job) never qualifies."""
        hub = _WarmHub()
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 20)
        self.assertIsNone(job.get("_warm"))
        self.assertTrue(hub.reclaims)
        self.assertNotIn("warm re-run", out)

    def test_a_signature_mismatch_is_todays_behavior(self):
        hub = _WarmHub()
        hub._warm_encode = ("someone-elses-scene", 1)
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 20)
        self.assertIsNone(job.get("_warm"))
        self.assertTrue(hub.reclaims)

    def test_the_fall_through_when_even_the_encoderless_stack_cannot_fit(self):
        """Correctness beats warmth: qualified, but a 1GB-free card cannot
        hold the DiT alone - today's full-bill path runs, wipe included."""
        hub = _WarmHub()
        g = warm_graph()
        anchor(hub, g)
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 1)
        self.assertIsNone(job.get("_warm"))
        self.assertTrue(hub.reclaims,
                        "the make-room reclaim must fire at full bill")
        self.assertIn("does not fit", out)
        # The reclaim target prices the WHOLE stack, encoder included:
        # 20.5GB weights + act + the 2.0GB floor.
        target = hub.reclaims[0][1]
        self.assertGreater(target, 20 * GB)

    def test_the_ram_floor_still_applies_when_warm(self):
        """Floors are untouched: VRAM fits the warm bill, host RAM does
        not - the job falls through and prices the reload."""
        hub = _WarmHub()
        g = warm_graph()
        anchor(hub, g)
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 30,
                              ram_gb=1)
        self.assertIsNone(job.get("_warm"))
        self.assertTrue(hub.reclaims)

    def test_the_guard_band_trims_never_wipes_when_warm(self):
        """The last job ended inside PREV_JOB_FREE_GUARD: the warm path
        takes the guard's bounded escalation - no idle lane, no brain, so
        the unload=False trim - and never the free_memory wipe."""
        hub = _WarmHub()
        hub.prev_job_free_min = int(0.5 * GB)
        g = warm_graph()
        anchor(hub, g)
        job, out = run_butler(hub, {DIT: 12, ENC: 20, VAE: 0.5}, 20)
        self.assertEqual(job.get("_warm"), "encode-cached")
        self.assertEqual(len(hub.reclaims), 1)
        _why, target, unload = hub.reclaims[0]
        self.assertFalse(unload, "the guard band is the trim, never the wipe")
        self.assertEqual(hub.flushes, [])


if __name__ == "__main__":
    unittest.main()
