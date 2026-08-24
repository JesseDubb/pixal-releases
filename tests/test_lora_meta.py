"""Brief 9.19d — 415 LoRAs get a spine: family groups and a search that reaches.

Appended to this file after 9.19e; the 9.19e classes below are untouched.

  - the compatibility rule is ONE callable now: server.lora_compatible, exported
    beside lora_stack and enforced by it at build time. The popup reads its
    verdicts off a sparse per-LoRA map ("family:variant" -> reason code, absent
    = compatible) that options() computes BY calling it - the JS restatement
    (loraMatchesProfile's family match + hardcoded Z-Image gate) is gone, and
    with it the drift where the picker promised what the sampler drops.
  - the compatibility filter gains an off switch: everything, grouped by
    family, active profile's family first and expanded, the rest collapsed
    (persisted via LORA_PICKER_GROUPS_KEY). Incompatible entries stay visible,
    dimmed and disabled, carrying the reason.
  - "unknown" is labelled "not identified yet" and reported as UNUSABLE (the
    stack drops it before the sampler), with the way out: rescan, or a
    .metadata.json sidecar.
  - search is always visible, autofocused, matches name/filename/base model,
    and reaches every group regardless of the filter - "3 in Krea 2 · 1 not
    identified yet".

RED proof: every 9.19d class failed against the pre-9.19d tree (the predicate
did not exist; the JSX carried no groups, no verdict map, no banner). Two
tests are preservation guards for behaviour that predates this brief
(test_build_time_drops_it_before_the_sampler - lora_stack always dropped
unknowns; test_a_by_hash_only_lora_leaves_unknown - 9.19b's classifier): their
teeth were proven by mutation, noted per-test, not by claiming a false red.

Brief 9.19e — a list view for the add-LoRA popup, and a LoRA says when it arrived.

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
SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8")

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


_UNKNOWN_LP = {"family": "unknown", "variant": "any", "supported": False,
               "base_model": None}


class SharedCompatibilityPredicate(unittest.TestCase):
    """The picker's compatibility verdict IS lora_stack's: one callable
    (server.lora_compatible), two call sites. The picker used to restate the
    rule in JS - a family match plus a hardcoded Z-Image base/turbo gate -
    and once 9.19a made the rule table-DRIVEN, the JS copy was one new
    families.json row away from silently promising LoRAs the sampler drops."""

    def test_lora_stack_defers_keep_drop_to_lora_compatible(self):
        # Whatever the shared predicate says, lora_stack does: patch the
        # callable and the build-time decision follows it. That is "same
        # callable" - not two implementations that happen to agree today.
        self.assertTrue(hasattr(server, "lora_compatible"),
                        "server.lora_compatible does not exist - the predicate "
                        "is not exported, so the picker cannot share it")
        with patch.object(server, "resolve_lora", side_effect=lambda name: name), \
             patch.object(server, "lora_compatible", return_value="family") as pred:
            kept, dropped = server.lora_stack(["Krea 2\\probe.safetensors:0.7"],
                                              family="krea2", variant="any")
        self.assertEqual(kept, [])
        self.assertEqual(dropped, ["incompatible probe"])
        pred.assert_called_once_with("Krea 2\\probe.safetensors", "krea2", "any")
        with patch.object(server, "resolve_lora", side_effect=lambda name: name), \
             patch.object(server, "lora_compatible", return_value=None):
            kept, dropped = server.lora_stack(["Krea 2\\probe.safetensors:0.7"],
                                              family="krea2")
        self.assertEqual(kept, [("Krea 2\\probe.safetensors", 0.7)])
        self.assertEqual(dropped, [])

    def test_the_picker_has_no_js_copy_of_the_rule(self):
        flat = _flat(SRC)
        self.assertIn("lora.incompatible", flat,
                      "the picker never reads the server's verdict map - it "
                      "must still be deciding compatibility itself")
        self.assertNotIn("lora.family === profile.family", flat,
                         "the family comparison is restated in JS - the drift "
                         "this brief exists to kill")
        self.assertNotIn('profile.family !== "zimage"', flat,
                         "the hardcoded Z-Image gate survived in JS")
        block = _block("const loraMatchesProfile =", "const recipeStageLabel")
        self.assertIn("lora.incompatible", _flat(block),
                      "loraMatchesProfile no longer consults the shared "
                      "predicate's verdicts")

    def test_the_wire_is_the_predicate_enumerated(self):
        # options() ships the predicate's verdicts per LoRA, sparse:
        # "family:variant" -> reason code, absent key = compatible.
        self.assertIn('"incompatible":', SERVER_SRC,
                      "the options payload carries no verdict map")
        self.assertIn("lora_compatible(", SERVER_SRC,
                      "the payload's verdict map is not built by the shared "
                      "callable")
        self.assertTrue(hasattr(server, "_LORA_PROFILE_KEYS"),
                        "no enumerated profile keys beside the predicate")
        for key in ("zimage:base", "zimage:turbo", "krea2:any", "unknown:any"):
            self.assertIn(key, server._LORA_PROFILE_KEYS,
                          f"no verdict is computed for profile {key}")

    def test_reason_codes(self):
        zt = {"family": "zimage", "variant": "turbo", "supported": True,
              "base_model": None}
        self.assertIsNone(server.lora_compatible("x", "zimage", "turbo", lp=zt))
        self.assertEqual(server.lora_compatible("x", "zimage", "base", lp=zt),
                         "variant")
        self.assertEqual(server.lora_compatible("x", "krea2", "any", lp=zt),
                         "family")
        self.assertEqual(server.lora_compatible("x", "krea2", "any", lp=_UNKNOWN_LP),
                         "unknown")


class ByHashOnlyClassificationGroups(unittest.TestCase):
    """A LoRA classified only by its by-hash base lands in its family group,
    not in unknown."""

    def test_a_by_hash_only_lora_leaves_unknown(self):
        # GUARD: the classifier half of this predates 9.19d (it is 9.19b's
        # machine). Teeth proven by mutation: blanking BY_HASH_BASE_MODEL
        # under this test fails the zimage assert.
        rel = "misc\\probe-9-19d.safetensors"   # no sidecar/header/folder hint
        with patch.dict(server.BY_HASH_BASE_MODEL, {rel: "Z-Image Turbo"}), \
             patch.object(server, "adjacent_metadata", return_value={}), \
             patch.object(server, "_lora_header_declared_base", return_value=""):
            profile = server.lora_profile(rel)
        self.assertEqual(profile["family"], "zimage")
        self.assertNotEqual(profile["family"], "unknown")
        self.assertEqual(profile["variant"], "turbo")

    def test_the_picker_groups_on_the_classifiers_family(self):
        flat = _flat(SRC)
        self.assertIn('lora.family || "unknown"', flat,
                      "the groups are not keyed on the server-classified "
                      "family - a by-hash LoRA cannot find its group")


class FilterOffKeepsIncompatibleVisible(unittest.TestCase):
    """Filter on: an incompatible LoRA is absent. Filter off (or searching):
    present, dimmed, disabled, and carrying the reason - never hidden without
    saying why (that silence is how 172 unusable LoRAs went unnoticed)."""

    def test_the_flat_list_is_the_compatible_set(self):
        flat = _flat(SRC)
        self.assertIn("const installedAll = available.filter((lora) => "
                      "loraMatchesProfile(lora, profile));", flat,
                      "the flat list is no longer the compatible set")

    def test_the_filter_has_an_off_switch(self):
        # Added with the switch itself; teeth proven by mutation (deleting the
        # button fails both asserts).
        block = _flat(_add_search())
        self.assertIn("setShowAll", block,
                      "nothing in the popup turns the filter off")
        self.assertIn('"show all"', block,
                      "the off switch does not say what it does")

    def test_grouped_entries_render_disabled_dimmed_with_reason(self):
        popup = _flat(_add_control())
        self.assertEqual(popup.count("reason={loraIncompatible(lora, profile)}"), 2,
                         "both densities must hand each grouped LoRA its verdict")
        for name, block in (("list row", _lora_row()), ("grid tile", _lora_tile())):
            with self.subTest(surface=name):
                self.assertIn("disabled={!!reason}", block,
                              f"the {name} stays clickable when incompatible - "
                              "the pick would be dropped at build time")
                self.assertIn("opacity: reason ?", block,
                              f"the {name} is not dimmed when incompatible")
                self.assertIn("{reason}", block,
                              f"the {name} carries no visible reason")

    def test_the_reason_names_the_loras_own_family(self):
        flat = _flat(SRC)
        self.assertIn("made for ${familyName(lora.family)}", flat,
                      "the reason does not name the LoRA's own family")
        self.assertIn('"not identified yet"', flat,
                      "the unknown reason is not the briefed label")


class UnknownIsUnusableNotUngrouped(unittest.TestCase):
    """An unknown-family LoRA is reported as unusable - it will not render -
    not merely filed under a different heading."""

    def test_unknown_family_is_a_verdict_not_a_group_only(self):
        for family, variant in (("krea2", "any"), ("zimage", "base"),
                                ("zimage", "turbo")):
            with self.subTest(family=family, variant=variant):
                self.assertEqual(
                    server.lora_compatible("x", family, variant, lp=_UNKNOWN_LP),
                    "unknown")

    def test_build_time_drops_it_before_the_sampler(self):
        # GUARD: lora_stack dropped unknowns before 9.19d too. What is NEW is
        # that the drop now travels through the shared callable - which this
        # exercises end to end via the real lora_profile -> predicate path.
        # Teeth proven by mutation: lora_compatible returning None for the
        # unknown family fails both asserts.
        with patch.object(server, "resolve_lora", side_effect=lambda name: name), \
             patch.object(server, "lora_profile", return_value=dict(_UNKNOWN_LP)):
            kept, dropped = server.lora_stack(["misc\\ghost.safetensors:1"],
                                              family="krea2")
        self.assertEqual(kept, [])
        self.assertEqual(dropped, ["incompatible ghost"])

    def test_the_group_says_the_cost_and_the_way_out(self):
        self.assertIn('"not identified yet"', SRC,
                      "the unknown group is not relabelled")
        popup = _flat(_add_control())
        self.assertIn("will not render", popup,
                      "the group never says what unknown costs")
        self.assertIn("rescan", popup,
                      "the way out does not name the metadata pass")
        self.assertIn(".metadata.json", popup,
                      "the way out does not name the sidecar")


class SearchReachesEveryGroup(unittest.TestCase):
    """The search hunts through ALL groups regardless of the compatibility
    filter - finding a file you own is not the filter's decision to make."""

    def test_search_ignores_the_compatibility_filter(self):
        flat = _flat(SRC)
        self.assertIn("available.filter(textMatch)", flat,
                      "search runs on the compat-filtered set - the filter "
                      "decides what you may find")
        self.assertIn("!searching && !showAll", flat,
                      "searching does not enter the all-groups view")
        groups = _block("const familyGroups =", "const groupLabel")
        self.assertNotIn("loraMatchesProfile", groups,
                         "the group builder filters on compatibility")
        self.assertNotIn("loraIncompatible", groups,
                         "the group builder filters on the verdict")

    def test_search_matches_name_filename_and_base_model(self):
        flat = _flat(SRC)
        self.assertIn('(lora.base_model || "").toLowerCase().includes(',
                      flat, "the base model is not in the search haystack")
        self.assertIn('${lora.title || ""} ${lora.short || ""} ${lora.name}',
                      flat, "the title/filename haystack regressed")

    def test_search_reports_where_the_matches_are(self):
        flat = _flat(SRC)
        self.assertIn(" in ${groupLabel(", flat,
                      "the summary does not count matches per group")
        self.assertIn('.join(" · ")', flat,
                      "the per-group counts are not joined into one line")

    def test_the_search_field_is_autofocused(self):
        self.assertIn("autoFocus", _add_search(),
                      "the picker's search field is not autofocused")
        field = _block("const FilterInput = (", "lora thumbnails")
        self.assertIn("autoFocus={autoFocus}", field,
                      "FilterInput never forwards autoFocus to its input")


class GroupCountsAndCollapse(unittest.TestCase):
    """Every group header carries the count of the set it renders; the
    active profile's family leads and starts open; collapse persists."""

    def test_the_groups_partition_the_pool(self):
        groups = _flat(_block("const familyGroups =", "const groupLabel"))
        self.assertIn("for (const lora of pool)", groups)
        self.assertIn(".push(lora)", groups,
                      "a pooled LoRA can fall between groups - the counts "
                      "would sum to less than the catalog")

    def test_group_headers_carry_the_groups_own_count(self):
        popup = _add_control()
        self.assertIn("{group.items.length}", popup,
                      "the header does not render the count of the set it "
                      "opens onto")

    def test_the_active_family_leads_and_starts_open(self):
        flat = _flat(SRC)
        self.assertIn("a.fam === profile.family ? -1", flat,
                      "the active profile's family does not lead the sort")
        self.assertIn("?? (group.fam !== profile.family)", flat,
                      "collapsed does not default to 'every family but the "
                      "active one'")

    def test_collapse_state_persists(self):
        self.assertIn('LORA_PICKER_GROUPS_KEY = "pixal.', SRC,
                      "no persisted group-collapse key beside the view key")
        flat = _flat(SRC)
        self.assertIn("window.localStorage.getItem(LORA_PICKER_GROUPS_KEY)", flat,
                      "the saved collapse state is never read back")
        self.assertIn("window.localStorage.setItem(LORA_PICKER_GROUPS_KEY, "
                      "JSON.stringify(groupsCollapsed))", flat,
                      "the chosen collapse state is never written back")


class ZImageGateMatchesBuildTime(unittest.TestCase):
    """The base/turbo rule the picker shows IS the one the graph enforces,
    across the whole variant matrix - not two implementations agreeing today."""

    CASES = [("turbo", "base", True), ("base", "base", False),
             ("any", "base", False), ("turbo", "turbo", False),
             ("base", "turbo", True), ("any", "turbo", False)]

    def test_pick_time_verdict_equals_build_time_drop(self):
        for lp_variant, model_variant, incompatible in self.CASES:
            with self.subTest(lora=lp_variant, model=model_variant):
                lp = {"family": "zimage", "variant": lp_variant,
                      "supported": True, "base_model": None}
                verdict = server.lora_compatible("probe", "zimage",
                                                 model_variant, lp=lp)
                self.assertEqual(bool(verdict), incompatible)
                with patch.object(server, "resolve_lora",
                                  side_effect=lambda name: name), \
                     patch.object(server, "lora_profile", return_value=lp):
                    kept, dropped = server.lora_stack(
                        ["ZImage\\probe.safetensors:1"], family="zimage",
                        variant=model_variant)
                self.assertEqual(not kept, incompatible,
                                 "build time disagrees with the predicate")
                self.assertEqual(bool(dropped), incompatible)


if __name__ == "__main__":
    unittest.main()
