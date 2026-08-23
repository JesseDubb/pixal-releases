"""A NEW badge nobody can earn is worse than no badge at all.

9.19e wired the LoRA picker to render `NewChip` on `lora.is_new`, in both grid
and list view, and pinned the client contract with a test. Then it reported the
half it could not fix from where it stood:

    "on disk, /api/options lora entries don't yet carry is_new (only
     model_meta does)... the badges are dead until it is."

So the feature shipped inert. This closes it, and pins the specific trap that
would make it look closed while staying inert:

`is_new_model` reads `entry["mtime"]`. In `options()` there are TWO dicts per
LoRA - the catalog entry `e` from `model_catalog("loras")`, which HAS an mtime,
and the picker dict assembled into `loras_by_rel`, which does not. Passing the
picker dict is the natural mistake, it raises nothing, and it returns False for
every LoRA forever. A test that only asserted "is_new_model is called somewhere
in the lora block" would pass against exactly that bug.
"""

import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "server.py").read_text(encoding="utf-8")


def _lora_block():
    """The lora loop in options(), from its `for` to the sort that ends it.

    Sliced rather than read whole so an assertion cannot accidentally be
    satisfied by the MODEL decoration a few dozen lines below, which has
    badged correctly all along.

    Anchored on `loras_by_rel = {}` and NOT on the `for` line: 9.19b added a
    second `for e in model_catalog("loras")` inside refresh_civitai_meta, and
    the first draft of this helper sliced that one instead - so it would have
    reported on a function that has nothing to do with the picker payload."""
    anchor = SRC.index("loras_by_rel = {}")
    start = SRC.index('for e in model_catalog("loras"):', anchor)
    end = SRC.index("loras.sort(", start)
    return SRC[start:end]


class TheWindowItself(unittest.TestCase):
    """Behaviour, not source. `is_new_model` is pure given a dict."""

    def _fresh(self, **kw):
        import server
        return server.is_new_model(kw)

    def test_a_recent_file_is_new(self):
        import server
        self.assertTrue(self._fresh(mtime=time.time() - 3600))

    def test_a_file_outside_the_window_is_not(self):
        import server
        self.assertFalse(
            self._fresh(mtime=time.time() - server.MODEL_NEW_WINDOW - 3600))

    def test_a_dict_with_no_mtime_is_never_new(self):
        """The trap, stated as behaviour. This is what the picker dict is, and
        it is why passing the wrong one is silent rather than loud."""
        self.assertFalse(self._fresh())
        self.assertFalse(self._fresh(mtime=0))


class TheLoraEntryGetsBadged(unittest.TestCase):

    def test_the_lora_block_exists(self):
        """Guards the tests below from passing vacuously on a refactor."""
        self.assertIn('for e in model_catalog("loras"):', SRC)

    def test_the_lora_block_decorates_is_new(self):
        self.assertTrue("is_new" in _lora_block(),
                        "lora entries never carry is_new, so 9.19e's badge can "
                        "never render - the client contract is already pinned "
                        "by tests/test_lora_meta.py")

    def test_it_reads_the_catalog_entry_not_the_picker_dict(self):
        """The real assertion. The picker dict has no mtime, so handing it to
        is_new_model returns False for every LoRA, forever, silently."""
        call = re.search(r"is_new_model\(\s*([A-Za-z_][\w\[\]\"']*)",
                         _lora_block())
        self.assertIsNotNone(call, "no is_new_model call in the lora block")
        self.assertEqual(call.group(1), "e",
                         "is_new_model must be handed the catalog entry `e`, "
                         "which carries mtime - not the assembled picker dict, "
                         "which does not and would badge nothing")


if __name__ == "__main__":
    unittest.main()
