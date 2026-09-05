"""The finish chain reaches the card and the lightbox (Jesse, 2026-09-01:
"the little hover tags dont always show ... have it so the light box also
shows those tags in the lower left where the other information is - might
be nice to put steps, sampler, scheduler too").

Why the chips missed: the builder announces jobinfo BEFORE the render, and
_record_finish writes the chain into job["info"] at delivery, after that
broadcast - so a live card kept the empty info forever and only a card
rehydrated from history carried the chain. The contract now:

  server - finalize re-broadcasts jobinfo with the job's final info, right
           before jobdone, whenever the job carries an info dict.
  web    - finishChips lives in names.js, ONE source for the card's hover
           strip and the lightbox readout; the lightbox's meta carries
           tuning / finish / upscaler and its rows print the sampler
           schedule through tuningLine, the same line the job card prints.
"""

import time
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = spec_from_file_location("pixal_server_finish_chips", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)

WEB = ROOT / "web" / "src"
CHAT = (WEB / "components" / "Chat.jsx").read_text(encoding="utf-8")
CARD = (WEB / "components" / "JobCard.jsx").read_text(encoding="utf-8")
NAMES = (WEB / "lib" / "names.js").read_text(encoding="utf-8")


class _Hub:
    """Just enough Hub for finalize, recording every broadcast in order."""

    def __init__(self):
        self.critic_hot = False
        self.prev_job_free_min = None
        self.flush_epoch = 1
        self._warm_encode = None
        self.events = []

    def broadcast(self, **kw):
        self.events.append(kw)

    def ledger_append(self, entry):
        pass

    finalize = server.Hub.finalize


def _job(**extra):
    return {"id": "f1", "cid": "c", "template": "realism",
            "started": time.time(), "images": [{"filename": "a.png"}],
            "error": None, "scene": "s", "seed": 1, "count": 1,
            "spec": {}, **extra}


class FinalizeResendsInfo(unittest.TestCase):

    def test_the_final_info_reaches_the_card_before_jobdone(self):
        hub = _Hub()
        job = _job(info={"model": "m", "tuning": {"steps": 8}})
        server._record_finish(job, "deshine")        # the delivery-time write
        server._record_finish(job, "grain@1.6")
        hub.finalize(job)
        kinds = [e["type"] for e in hub.events]
        self.assertIn("jobinfo", kinds)
        self.assertLess(kinds.index("jobinfo"), kinds.index("jobdone"))
        info = next(e for e in hub.events if e["type"] == "jobinfo")
        self.assertEqual(info["job_id"], "f1")
        self.assertEqual(info["finish"], "deshine+grain@1.6")
        self.assertEqual(info["tuning"], {"steps": 8})

    def test_a_job_without_info_sends_none(self):
        hub = _Hub()
        hub.finalize(_job())
        self.assertNotIn("jobinfo", [e["type"] for e in hub.events])


class OneChipSource(unittest.TestCase):

    def test_finish_chips_lives_in_names_and_both_surfaces_import_it(self):
        self.assertIn("export const finishChips", NAMES)
        self.assertNotIn("const finishChips = (info)", CARD)
        self.assertIn('import { tuningLine, finishChips } from "../lib/names.js";', CARD)
        self.assertIn('tuningLine, finishChips } from "../lib/names.js";', CHAT)

    def test_the_chips_read_data_in_pixel_order(self):
        body = NAMES.split("export const finishChips")[1].split("};")[0]
        order = [body.index(s) for s in ("dlss5", "deshine", "upscaler", "grain")]
        self.assertEqual(order, sorted(order))


class LightboxReadout(unittest.TestCase):

    def test_meta_carries_the_chain_and_the_schedule(self):
        meta = CHAT.split("const metaFor = (src) =>")[1].split("});")[0]
        for key in ("tuning: src.info && src.info.tuning",
                    "finish: src.info && src.info.finish",
                    "upscaler: src.info && src.info.upscaler"):
            self.assertIn(key, meta)

    def test_the_rows_print_the_sampler_schedule(self):
        self.assertIn("tuningLine(m.tuning)", CHAT)

    def test_the_chips_sit_in_the_lower_left_readout(self):
        self.assertIn("const chips = finishChips(imageFinishInfo(cur, m));", CHAT)
        self.assertIn('aria-label="Finish chain"', CHAT)


if __name__ == "__main__":
    unittest.main()
