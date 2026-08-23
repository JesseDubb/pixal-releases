"""Brief 9.19e — a list view for the add-LoRA popup, and a LoRA says when it arrived.

The unbriefed half of Jesse's sentence: "Might even want to improve the UX to
support list view with new tags on newly added."

  - the popup gains a grid/list toggle, persisted the way the rail's collapsed
    state is persisted: one localStorage key, a lazy useState initializer that
    reads it, an effect that writes it back. Grid stays the default Jesse
    chose; an unrecognised saved value falls back to it - the same restore
    guard the settings tab uses (`TABS.some(...) ? saved : "general"`).
  - both views carry the NEW badge via the server's is_new_model (a 7-day
    window read from the file's own mtime), over the same `is_new` wire field
    the model picker already badges on, and both badge through the existing
    NewChip - the eighth chip reused, not a ninth invented (DESIGN.md's
    census; consolidation is 9.20's brief, not this one).
  - a list row has the width the grid tile lacks, so the full name stands
    unclamped - the distinguishing tail of a community LoRA name is what the
    mode is FOR. The grid tile keeps 9.19c's two-line clamp.
  - a view is a density, not a different screen: both map the same filtered,
    capped `installed` set, so the search and profile filter hold in both.

The server machinery (is_new_model, MODEL_NEW_WINDOW, mtime on catalog
entries) already exists at server.py:396 and is exercised here against real
files with real mtimes. The JSX is asserted by static source analysis in the
style of test_lora_picker_copy.py - this repo has no JS test runner.

unittest.TestCase because `unittest discover` is this repo's runner and CI's.
RED proof: the picker-view, list-row, badge and same-set tests fail against
the pre-9.19e tree (assertion messages name what is missing). The grid-clamp
guard, the model-picker wire guard and the chip census are preservation
guards, proven live by mutation - dropping the tile's clamp, inventing a
ninth chip or deleting the model picker's badge fails them. The is_new_model
tests guard machinery that already exists, so they were green on arrival;
their teeth were proven by pointing the same assertions at a stub predicate
(always-True fails the outside-window assert) and by planting a ledger file
in the scanned tree (fails the no-ledger assert) - not by claiming a false
red.
"""

import os
import re
import time
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "Composer.jsx").read_text(encoding="utf-8")

_SPEC = spec_from_file_location("pixal_server", ROOT / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


def _block(start_marker, end_marker):
    """SRC[start_marker : end_marker], both found at or after the start."""
    i = SRC.index(start_marker)
    return SRC[i:SRC.index(end_marker, i)]


def _lora_row():
    return _block("const LoraRow = (", "// A LoRA is chosen by its preview")


def _lora_tile():
    return _block("const LoraTile = (", "attached-source icons")


def _add_search():
    return _block("const addSearch = (", "const addControl = (")


def _add_control():
    return _block("const addControl = (", "</Pop>")


def _view_pref():
    """The view-preference block: key constant, lazy initializer, write-back."""
    i = SRC.index("LORA_PICKER_VIEW_KEY")
    return SRC[i:SRC.index("[pickerView]);", i)]


def _name_span(block):
    """The <span> in `block` whose children are the display name."""
    m = re.search(r">\s*\{lora\.title \|\| lora\.short \|\| lora\.name\}", block)
    assert m, "the block no longer renders lora.title || lora.short || lora.name"
    start = block.rindex("<span", 0, m.start())
    return block[start:block.index("</span>", m.start())]


def _flat(s):
    return re.sub(r"\s+", " ", s)


class PickerViewPreference(unittest.TestCase):
    """The grid/list toggle persists like the rail's collapsed state: one
    localStorage key, a lazy read, an effect write - not a second mechanism."""

    def test_the_view_preference_round_trips_through_one_key(self):
        self.assertIn('LORA_PICKER_VIEW_KEY = "pixal.', SRC,
                      "no persisted view key beside LORA_RAIL_COLLAPSED_KEY")
        block = _view_pref()
        self.assertIn("window.localStorage.getItem(LORA_PICKER_VIEW_KEY)", block,
                      "the saved view is never read back")
        self.assertIn("window.localStorage.setItem(LORA_PICKER_VIEW_KEY, pickerView)",
                      _flat(block), "the chosen view is never written back")

    def test_grid_is_the_default(self):
        self.assertIn("LORA_PICKER_VIEW_KEY", SRC,
                      "no persisted view preference - grid cannot be the default"
                      " of a toggle that does not exist")
        block = _view_pref()
        # Nothing stored -> grid, and an unrecognised saved value (a retired
        # view) restores to grid - the settings tab's guard shape.
        self.assertIn('? saved : "grid"', _flat(block),
                      "an unknown saved view does not fall back to grid")
        self.assertIn('return "grid";', block,
                      "grid is not the no-stored-preference default")

    def test_the_toggle_is_the_existing_segmented_control(self):
        block = _add_search()
        self.assertIn("<SegmentedControl", block,
                      "the view switch is not the shared segmented control")
        self.assertIn('variant="grid"', block,
                      "the view switch is the grid variant - its labels never clip")
        self.assertIn("value={pickerView}", block)
        self.assertIn("onChange={setPickerView}", block)
        self.assertIn("ariaLabel=", block,
                      "the radiogroup lost its accessible name (DESIGN.md §6)")
        # Grid leads the options: it is the default browse mode.
        self.assertIn('v: "grid"', block)
        self.assertIn('v: "list"', block)
        self.assertLess(block.index('v: "grid"'), block.index('v: "list"'),
                        "grid does not lead the toggle")


class ListViewDensity(unittest.TestCase):
    """A view is a density, not a different screen."""

    def test_list_rows_render_the_full_name_without_a_clamp(self):
        self.assertIn("const LoraRow = (", SRC,
                      "no list-row component - the list view is not built")
        span = _name_span(_lora_row())
        self.assertNotIn("WebkitLineClamp", span,
                         "the list row clamps the name - the grid's compromise,"
                         " which the mode exists to escape")
        self.assertNotIn("-webkit-box", span)
        self.assertNotIn('textOverflow: "ellipsis"', span,
                         "an ellipsis is a one-line clamp by another name")
        self.assertNotIn('whiteSpace: "nowrap"', span)
        self.assertIn('overflowWrap: "anywhere"', span,
                      "a name longer than the row cannot break mid-token")

    def test_grid_tiles_keep_the_two_line_clamp(self):
        # Preservation guard for 9.19c: the grid's compromise stays the grid's.
        span = _name_span(_lora_tile())
        self.assertIn("WebkitLineClamp: 2", span,
                      "the grid tile lost its two-line clamp")
        self.assertIn('overflowWrap: "anywhere"', span)

    def test_both_views_render_the_same_filtered_set(self):
        popup = _add_control()
        self.assertEqual(popup.count("installed.map((lora)"), 2,
                         "both views must map the same filtered, capped set -"
                         " one mapping per density, not a second collection")
        self.assertIn("<LoraRow", popup, "the list density is not rendered")
        self.assertIn("<LoraTile", popup, "the grid density is not rendered")
        self.assertIn('pickerView === "list"', popup,
                      "the densities are not switched on the view preference")
        self.assertNotIn("installed.filter(", popup,
                         "the list re-filters: a different screen, not a density")
        self.assertNotIn("installed.slice(", popup,
                         "the list re-caps: a different screen, not a density")

    def test_a_row_shows_cover_name_and_badges(self):
        self.assertIn("const LoraRow = (", SRC,
                      "no list-row component - the list view is not built")
        row = _lora_row()
        self.assertIn("<LoraThumb", row, "the row shows no cover thumb")
        self.assertIn("{lora.title || lora.short || lora.name}", row,
                      "the row shows no name")
        self.assertIn("<NewChip", row, "the row shows no NEW badge")


class NewBadgeInThePicker(unittest.TestCase):
    """NEW badges in both views, via the server's is_new_model, through the
    existing chip."""

    def test_both_views_badge_a_new_lora(self):
        self.assertIn("const LoraRow = (", SRC,
                      "no list-row component - the list view is not built")
        for name, block in (("list row", _lora_row()), ("grid tile", _lora_tile())):
            with self.subTest(surface=name):
                self.assertIn("lora.is_new", block,
                              f"the {name} never reads the newness flag")
                self.assertIn("<NewChip", block,
                              f"the {name} renders no NEW badge")

    def test_the_badge_is_the_existing_chip_not_a_ninth(self):
        # DESIGN.md's census counts eight chips app-wide; Composer.jsx defines
        # three of them. Consolidation is 9.20's brief - this one reuses.
        defined = set(re.findall(r"const (\w+Chip) = \(", SRC))
        self.assertEqual(defined, {"SizeChip", "NewChip", "VariantChip"},
                         "a new chip component appeared - reuse NewChip")
        self.assertEqual(SRC.count("const NewChip = ("), 1)

    def test_the_badge_uses_the_same_wire_field_as_the_model_picker(self):
        # Preservation guard: the model picker's badge is the convention the
        # LoRA badge mirrors - one predicate (is_new_model), one field name.
        self.assertIn("m.is_new && <NewChip />", _flat(SRC),
                      "the model picker's is_new badge is gone")
        self.assertIn("lora.is_new", SRC,
                      "the LoRA badge does not ride the same is_new field")


class NewModelWindow(unittest.TestCase):
    """The badge means "you just downloaded this": the file's own mtime, a
    7-day window, and nothing written down - a first-seen ledger re-badges the
    whole collection the moment any caller hands it a partial list."""

    def _scan(self, root):
        with patch.object(server, "model_roots", return_value=[root / "models"]), \
             patch.dict(server._CATALOG, {"at": 0, "data": None}):
            return server.model_catalog("loras")

    def test_a_file_inside_the_window_badges_and_one_outside_does_not(self):
        now = time.time()
        with TemporaryDirectory() as td:
            root = Path(td)
            loras = root / "models" / "loras"
            loras.mkdir(parents=True)
            (loras / "fresh.safetensors").write_bytes(b"x")
            old = loras / "old.safetensors"
            old.write_bytes(b"x")
            past = now - 30 * 86400
            os.utime(old, (past, past))
            entries = {e["rel"].replace("\\", "/").split("/")[-1]: e
                       for e in self._scan(root)}
        self.assertTrue(server.is_new_model(entries["fresh.safetensors"], now),
                        "a file downloaded an hour ago does not badge")
        self.assertFalse(server.is_new_model(entries["old.safetensors"], now),
                         "a month-old file still badges as new")

    def test_the_window_is_the_seven_day_constant(self):
        now = 1_800_000_000.0
        self.assertEqual(server.MODEL_NEW_WINDOW, 7 * 86400,
                         "the new window is not the briefed 7 days")
        self.assertTrue(server.is_new_model(
            {"rel": "x", "mtime": now - server.MODEL_NEW_WINDOW + 3600}, now))
        # The badge expires rather than sticking to a model forever.
        self.assertFalse(server.is_new_model(
            {"rel": "x", "mtime": now - server.MODEL_NEW_WINDOW - 1}, now))
        # An unreadable stat must not invent newness.
        self.assertFalse(server.is_new_model({"rel": "x", "mtime": 0}, now))
        self.assertFalse(server.is_new_model({"rel": "x"}, now))

    def test_no_first_seen_ledger_is_written(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            loras = root / "models" / "loras"
            loras.mkdir(parents=True)
            (loras / "a.safetensors").write_bytes(b"x")
            (loras / "b.safetensors").write_bytes(b"x")
            before = {str(p.relative_to(root)) for p in root.rglob("*")}
            entries = self._scan(root)
            for entry in entries:
                server.is_new_model(entry)                # the default-now path
                server.is_new_model(entry, time.time())
            after = {str(p.relative_to(root)) for p in root.rglob("*")}
        self.assertEqual(before, after,
                         "the scan wrote something - a ledger by another name")
        for entry in entries:
            self.assertNotIn("first_seen", entry,
                             "a first-seen field rides the catalog entry")


if __name__ == "__main__":
    unittest.main()
