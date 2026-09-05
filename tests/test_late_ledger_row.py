"""A finished picture whose job was finalized while its finishers ran still
gets a ledger row - once - and the gallery hears about it (2026-09-05).

Before the finishers moved off the event loop this could not happen: Stop
could not interleave with a blocking finish chain. Now it can, and a render
that is on disk and on the card must not vanish on the next refresh."""
import json
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


class LateLedgerRow(unittest.TestCase):
    def _job(self):
        return {"id": "late01", "cid": "c", "template": "zimage", "scene": "a still",
                "full_prompt": "a still", "seed": 7, "count": 1, "spec": {"mp": 1.0},
                "info": {"model": "z"}, "images": [], "seen": set(),
                "started": time.time() - 30, "elapsed": 25.0, "error": "stopped",
                "finalized": True}

    def test_row_is_written_once_and_announced(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            Image.new("RGB", (8, 8), "#888").save(root / "output" / "late.png")
            ledger = root / "history.jsonl"
            events = []
            job = self._job()
            img = {"filename": "late.png", "subfolder": "", "type": "output",
                   "media": "image", "finish": "grain@1"}
            job["images"].append(img)
            with patch.object(server, "CDIR", root), \
                    patch.object(server, "LEDGER", ledger), \
                    patch.object(server.HUB, "broadcast",
                                 lambda **ev: events.append(ev)):
                server.HUB._late_image_row(job, img)
                rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
                self.assertEqual([r["id"] for r in rows], ["late01"])
                self.assertEqual(rows[0]["images"][0]["filename"], "late.png")
                self.assertTrue(job["_row_written"])
                self.assertEqual([e["type"] for e in events], ["ledger"])
                self.assertEqual(events[0]["entry"]["id"], "late01")
                self.assertNotIn("full_prompt", events[0]["entry"])   # lite row
                self.assertEqual(events[0]["entry"]["images"][0]["filename"], "late.png")
                # A second late frame for a job that already has its row is
                # logged, never appended: the ledger is append-only per job.
                server.HUB._late_image_row(job, img)
                rows = [l for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
                self.assertEqual(len(rows), 1)
                self.assertEqual(len(events), 1)

    def test_finalize_marks_its_own_row_so_no_second_one_is_written(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "history.jsonl"
            job = self._job()
            job["_row_written"] = True             # finalize wrote the row
            with patch.object(server, "CDIR", root), \
                    patch.object(server, "LEDGER", ledger), \
                    patch.object(server.HUB, "broadcast", lambda **ev: None):
                server.HUB._late_image_row(job, {"filename": "x.png", "media": "image"})
                self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
