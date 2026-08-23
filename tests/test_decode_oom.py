"""A decode OOM is not a sampling OOM.

The failure that prompted this: an LTX 2.5 clip sampled for 40 minutes, then
died in the VAE decode -

    na_diffusion_decoder.py line 156 -> comfy_kitchen.na3d(q, k, v, ...)
      -> torch.empty_like(q)
    torch.OutOfMemoryError: Allocation on device 0 would exceed allowed memory

Pixal read only `exception_message` off ComfyUI's `execution_error` and threw
away the `node_id`/`node_type` it also sends, so this was indistinguishable
from running out of room while sampling. The retry therefore shortened the
CLIP - throwing away forty minutes of sampling that had actually succeeded,
and changing nothing about the step that failed.

Two things are asserted here: that the shipped templates chunk their decode in
time at all, and that a decode OOM turns the decode down rather than the clip.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"


def _tiled_decodes():
    """(template name, node id, inputs) for every VAEDecodeTiled we ship."""
    out = []
    for path in sorted(TEMPLATES.glob("*.json")):
        try:
            g = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(g, dict):
            continue
        for node_id, node in g.items():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") == "VAEDecodeTiled":
                out.append((path.stem, node_id, node.get("inputs") or {}))
    return out


class TiledDecodeChunksInTime(unittest.TestCase):

    def test_we_ship_at_least_one_tiled_decode(self):
        """Guards the two tests below from passing vacuously if the templates
        are renamed or the decode swapped."""
        self.assertTrue(_tiled_decodes(), "no VAEDecodeTiled found to check")

    def test_no_decode_asks_for_the_whole_clip_at_once(self):
        """ComfyUI's temporal_size is 'amount of frames to decode at a time',
        default 64, max 4096. We shipped 4096 - the maximum - on both LTX 2.5
        decodes, which after the VAE's 8x temporal compression hands na3d 512
        latent frames in one allocation instead of 8. Temporal extent is
        exactly what it allocates over."""
        loud = [(t, n, ins.get("temporal_size"))
                for t, n, ins in _tiled_decodes()
                if not isinstance(ins.get("temporal_size"), int)
                or ins["temporal_size"] > 256]
        self.assertEqual(loud, [], "temporal chunking is off or far too large: "
                                   "%s" % (loud,))

    def test_overlap_stays_under_half_the_chunk(self):
        """ComfyUI halves temporal_overlap when it is >= temporal_size/2, so an
        overlap that outgrows its chunk silently stops being the value written
        here. Keep them honest instead."""
        bad = [(t, n, ins.get("temporal_size"), ins.get("temporal_overlap"))
               for t, n, ins in _tiled_decodes()
               if isinstance(ins.get("temporal_size"), int)
               and isinstance(ins.get("temporal_overlap"), int)
               and ins["temporal_overlap"] * 2 > ins["temporal_size"]]
        self.assertEqual(bad, [], "temporal_overlap will be silently halved: "
                                  "%s" % (bad,))


class DecodeOomTurnsDownTheDecode(unittest.TestCase):
    """The retry plan is pure given a job dict, so it is testable without a
    card, a server or ComfyUI."""

    def _plan(self, job):
        import server
        return server.HUB.oom_retry_plan(job)

    def _job(self, **kw):
        job = {"template": "ltx25_i2v", "cid": "c", "seed": 1,
               "spec": {"seconds": 10.0}, "scene": "s",
               "error": "torch.OutOfMemoryError: Allocation on device 0 would "
                        "exceed allowed memory. (out of memory)"}
        job.update(kw)
        return job

    def test_a_decode_oom_does_not_shorten_the_clip(self):
        """The whole point. Sampling succeeded; its length is not the problem."""
        plan = self._plan(self._job(
            _oom_node={"id": "32", "type": "VAEDecodeTiled"}))
        self.assertIsNotNone(plan, "a decode OOM should still be retried")
        spec, _note = plan
        self.assertEqual(spec.get("seconds"), 10.0,
                         "the clip was shortened for a failure in the decode")

    def test_a_decode_oom_halves_the_temporal_chunk(self):
        spec, note = self._plan(self._job(
            _oom_node={"id": "32", "type": "VAEDecodeTiled"}))
        over = [o for o in (spec.get("overrides") or ())
                if o.get("input") == "temporal_size"]
        self.assertEqual(len(over), 1, "expected one temporal_size override")
        self.assertEqual(over[0]["node"], "32")
        self.assertLess(over[0]["value"], 256)
        self.assertGreaterEqual(over[0]["value"], 8, "below ComfyUI's floor")
        self.assertIn("clip itself was fine", note)

    def test_a_sampling_oom_still_shortens_the_clip(self):
        """The existing behaviour has to survive: when the SAMPLER runs out of
        room, length is exactly the right lever."""
        spec, _note = self._plan(self._job(
            _oom_node={"id": "6", "type": "SamplerCustomAdvanced"}))
        self.assertLess(spec.get("seconds"), 10.0,
                        "a sampling OOM should still shorten the clip")
        self.assertFalse([o for o in (spec.get("overrides") or ())
                          if o.get("input") == "temporal_size"],
                         "a sampling OOM should not touch the decode")

    def test_an_unnamed_node_still_shortens_the_clip(self):
        """Older ComfyUI builds, or any path that does not report the node, must
        keep the previous behaviour rather than doing nothing."""
        spec, _note = self._plan(self._job())
        self.assertLess(spec.get("seconds"), 10.0)

    def test_a_second_oom_is_terminal(self):
        self.assertIsNone(self._plan(self._job(
            _oom_retry=True, _oom_node={"id": "32", "type": "VAEDecodeTiled"})))

    def test_a_non_oom_failure_is_not_retried(self):
        self.assertIsNone(self._plan(self._job(
            error="Prompt outputs failed validation",
            _oom_node={"id": "32", "type": "VAEDecodeTiled"})))


if __name__ == "__main__":
    unittest.main()
