"""Brief 9.17c — Settings stops rearranging itself as it loads.

Jesse: "Its weird seeing a control with AUTO as one button then it turns to
LTX / Minimax options all of a sudden as the entire page shifts vertical
spacing and content is pulled in." … "desklight ghost or skeleton loads the
page."

Thirteen slots in SettingsMenu start empty. Twelve land together from
/api/settings - cfg, upscale, editCfg, vae, pidCfg, videoCfg, localList,
criticInstalled, roots, extraRoots, h3Cfg. (The eleventh name, `note`, gets
no ghost: it is action feedback pinned below the scroll region, holds no
panel space while loading, and says nothing until the user acts - there is
nothing to ghost.) The thirteenth, `upd`, is About's update check (9.24a).
Before this brief every control derived from those slots rendered COLLAPSED
first - one segment until videoCfg landed, then four, and everything below
it moved - or lied: Explicit content showed "auto" selected while the
stored value was still in flight, and the VRAM gloss read "Card not read
yet" before the card had been asked.

The rules this file pins, by static source analysis like its rhythm/copy
siblings (no JS runtime):

  1. Every async-derived control has a ghost branch: {slot ? (real) :
     (ghost)}, the ghost from Skeleton.jsx - SegGhost for a SegmentedControl,
     PickerGhost for a ScrollPicker.
  2. The ghost occupies the box its control will - same heights by
     construction, no margins of its own - so the panel's scrollHeight is
     identical before and after the fetches land.
  3. The swap is px-ghost-in: opacity only, no height animation
     (DESIGN.md §5), and prefers-reduced-motion stills it.
  4. A value that is unknown until loaded (the detected card, the
     installed counts) ghosts the VALUE and keeps the label - the row
     never collapses.
  5. No control shows a selection defaulted before its fetch lands.

Hangs off unittest.TestCase because `unittest discover` is this repo's
runner and CI's; bare module-level functions are silently skipped by the
gate (9.17a's ten tests died that death before 941c84c rescued them).
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")
SKEL = (ROOT / "web" / "src" / "components" / "Skeleton.jsx").read_text(encoding="utf-8")
SEG = (ROOT / "web" / "src" / "lib" / "SegmentedControl.jsx").read_text(encoding="utf-8")

# The gated swaps each slot owns. cfg carries the General and Brain controls

# plus the live-value glosses, because everything it feeds lands in the one
# /api/settings batch (the thirteenth is 9.46's brain-idle segment; the
# fourteenth is 9.60's official-prompting toggle); videoCfg owns four
# (engine, model, the 9.38 dialogue format, and the 9.31 H3 2× default);
# upscale owns three (its Image-tab controls, its Video-tab controls, and
# the Image-tab installed-count gloss); editCfg owns one gate that swaps its
# two pickers, color-match switch, count subline, and matching ghosts together.
# h3Cfg owns ONE: 9.91's two model pickers and 9.94's text
# encoder are all in the MiniMax H3 section now, so a single gate swaps three
# PickerGhost value pills for three Pickers. (The encoder briefly had a second gate of
# its own under VRAM profile; it moved on 2026-08-31 - Jesse, "I want the
# option in settings under minimax" - and one gate covering the section is the
# better shape anyway: the three rows land together or not at all.)
GATES = {"cfg": 14, "videoCfg": 5, "upscale": 3, "editCfg": 1,
         # vae owns two since 1.2.0b: the Z-Image decoder row and the Special
         # decoders group (one gate swaps both of its rows together).
         "vae": 2, "pidCfg": 1, "upd": 1,
         # 1.1.4b: the still finish. Its own slot rather than a videoCfg key -
         # it is an image setting and it lands on the Image tab. 2026-09-01:
         # the dlss 5 and finishing groups merged into one "post processing"
         # group (Jesse), so a single gate swaps all three ghost rows.
         "stillCfg": 1, "h3Cfg": 1}

GHOST_MARKERS = ("<SegGhost", "<PickerGhost", "<SwitchGhost", "<LineGhost",
                 "<ValueGhost", "<Bar")


def _skip_string(src, i):
    """src[i] opens a "…" string or `…` template; returns the index just past
    its close. Templates are treated as opaque: their ${…} interpolations are
    balanced in this codebase, so skipping whole is safe for bracket scans.
    Single quotes are NOT string openers here - this file writes literals
    double-quoted, and treating "'" as one would misread JSX text like
    "Pixal's" inside the About update slot."""
    q = src[i]
    j = i + 1
    while j < len(src):
        if src[j] == "\\":
            j += 1
        elif src[j] == q:
            return j + 1
        j += 1
    raise ValueError("unterminated string at %d" % i)


def _bracketed(src, i):
    """src[i] is "(". Returns (inner_source, index_just_past_matching_")").
    Strings, templates and comments are opaque; (), {} and [] all nest."""
    assert src[i] == "(", "expected ( at %d: %.40s" % (i, src[i:])
    depth = 0
    j = i
    while j < len(src):
        c = src[j]
        if c in "\"`":
            j = _skip_string(src, j)
            continue
        if src.startswith("//", j):
            j = src.index("\n", j) + 1
            continue
        if src.startswith("/*", j):
            j = src.index("*/", j) + 2
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j], j + 1
        j += 1
    raise ValueError("unbalanced brackets at %d" % i)


def _skip_ws(src, i):
    while src[i] in " \t\n":
        i += 1
    return i


def _gates(slot):
    """Every {slot ? ( … ) : ( … )} in SettingsMenu ({!slot ? …} counts too -
    the VRAM gloss, the folder rows and the local-model list put the ghost
    FIRST). Yields (inverted, then_src, else_src, then_span, else_span)."""
    out = []
    for m in re.finditer(r"\{(!?)" + slot + r" \? \(", SRC):
        then_src, j = _bracketed(SRC, m.end() - 1)
        k = _skip_ws(SRC, j)
        assert SRC[k] == ":", "gate on %s near %d lost its else" % (slot, m.start())
        k = _skip_ws(SRC, k + 1)
        assert SRC[k] == "(", "gate on %s near %d: the else must be ( … )" % (slot, m.start())
        else_src, j2 = _bracketed(SRC, k)
        assert SRC[_skip_ws(SRC, j2)] == "}", "gate on %s near %d never closed" % (slot, m.start())
        out.append((bool(m.group(1)), then_src, else_src,
                    (m.end(), j - 1), (k, j2 - 1)))
    return out


class SettingsLoading(unittest.TestCase):

    def test_every_async_slot_swaps_a_ghost_for_the_real_control(self):
        """The gate IS the fix: {slot ? (real) : (ghost)}. The ghost side
        renders a Skeleton ghost, the real side fades in (px-ghost-in), and
        each slot owns exactly as many gates as the controls it feeds."""
        counts = {}
        for slot in GATES:
            for inverted, then_src, else_src, _, _ in _gates(slot):
                ghost = then_src if inverted else else_src
                real = else_src if inverted else then_src
                self.assertTrue(any(g in ghost for g in GHOST_MARKERS),
                                "%s gate renders no ghost: %.80s" % (slot, ghost))
                self.assertIn("px-ghost-in", real,
                              "%s gate's real side must fade in, not pop" % slot)
                counts[slot] = counts.get(slot, 0) + 1
        self.assertEqual(counts, GATES)

    def test_every_async_derived_control_has_a_ghost_branch(self):
        """Coverage by name: every segment row, picker and the brain's mode
        strip whose options or stored value arrive async. A label missing
        here renders ungated - which is either a collapse (the video engine
        row growing 1 -> 4 segments) or a lie (Explicit content lit on
        "auto" with "on" stored)."""
        labels, placeholders = set(), set()
        for slot in GATES:
            for inverted, then_src, else_src, _, _ in _gates(slot):
                real = else_src if inverted else then_src
                labels.update(re.findall(r'ariaLabel="([^"]+)"', real))
                placeholders.update(re.findall(r'placeholder="([^"]+)"', real))
        expected_labels = {
            # cfg - General
            "Explicit content", "When ComfyUI boots", "ComfyUI console window",
            "VRAM profile",
            # cfg - Brain
            "Chat brain source", "memory policy", "brain runs on",
            # videoCfg / upscale / pidCfg
            "Default video engine", "Video upscale engine",
            "RTX Super Resolution quality", "Image upscale mode",
            "VAE decode",
        }
        expected_placeholders = {
            "choose a reviewer model…",          # criticInstalled arrives with cfg
            "first available",                   # videoCfg's model picker
            "choose local upscale model…",       # upscale, Image tab
            "recipe default",                    # editCfg
            "stock Z-Image VAE (recommended)",   # vae
        }
        self.assertTrue(expected_labels <= labels,
                        "ungated: %s" % sorted(expected_labels - labels))
        self.assertTrue(expected_placeholders <= placeholders,
                        "ungated: %s" % sorted(expected_placeholders - placeholders))

    def test_no_control_shows_a_selection_before_its_value_lands(self):
        """Every SegmentedControl / ScrollPicker / TabStrip in the file renders
        inside a gate's real branch, except the two synchronous controls:
        Appearance (the theme store) and the top tab strip (localStorage).
        Anything else ungated can show a DEFAULT as if it were the stored
        value - the Explicit-content lie."""
        real_spans = []
        for slot in GATES:
            for inverted, _, _, then_span, else_span in _gates(slot):
                real_spans.append(else_span if inverted else then_span)
        # 10.0: the pixal toggle joined the scan - a Switch shows the same
        # selection lie an ungated segment row would
        for m in re.finditer(r"<(SegmentedControl|ScrollPicker|TabStrip|Switch)\b", SRC):
            ctx = SRC[m.start():m.start() + 200]
            if "value={store.themePref}" in ctx or "value={tab}" in ctx:
                continue  # synchronous: the theme store and the saved tab
            self.assertTrue(any(a <= m.start() < b for a, b in real_spans),
                            "%s renders outside a loading gate" % m.group(1))

    def test_nothing_below_a_ghost_moves_when_the_real_thing_lands(self):
        """The scrollHeight invariant, pinned statically: the collapsed
        partial renders are gone, the ghost is the control's own box, and
        no ghost adds spacing of its own (the rhythm owns every gap -
        test_settings_rhythm.py holds the panel side of that)."""
        # the collapsed partials are gone
        self.assertNotIn("loading…", SRC)
        self.assertNotIn("...((videoCfg && videoCfg.engines) || [])", SRC)
        # PickerGhost IS the value-pill trigger (10.0): same HEIGHT.rail box
        picker_ghost = re.search(r"export const PickerGhost = .*?\n\);", SKEL, re.S)
        self.assertIsNotNone(picker_ghost, "PickerGhost is gone from Skeleton.jsx")
        self.assertIn("height: HEIGHT.rail", picker_ghost.group(0))
        picker = (ROOT / "web/src/lib/Picker.jsx").read_text(encoding="utf-8")
        self.assertIn("height: HEIGHT.rail", picker)
        self.assertIn("<Picker hug label={placeholder", SRC)
        # SegGhost IS the pill selector's capsule: 1px border + 2px padding
        # around a (HEIGHT.rail - 6) option - HEIGHT.rail on both sides.
        seg_ghost = re.search(r"export const SegGhost = .*?\n\);", SKEL, re.S)
        self.assertIsNotNone(seg_ghost, "SegGhost is gone from Skeleton.jsx")
        self.assertIn("h={HEIGHT.rail - 6}", seg_ghost.group(0))
        self.assertIn("padding: 2", seg_ghost.group(0))
        # the flex variant (other surfaces) still renders its own box
        self.assertIn("padding: 3", SEG)
        self.assertIn('"8px 6px"', SEG)
        # and a ghost carries no margins of its own
        self.assertNotIn("margin", SKEL)

    def test_the_swap_is_a_crossfade_and_honours_reduced_motion(self):
        """Opacity only, never a height animation (DESIGN.md §5). Settings
        mounts Skeleton's keyframes itself, px-ghost-in animates nothing
        but opacity, and the reduced-motion query stills both the shimmer
        and the fade."""
        self.assertIn('from "./Skeleton.jsx"', SRC)
        self.assertIn("<SkeletonStyle />", SRC)
        i = SKEL.index("@keyframes px-ghost-in")
        fade = SKEL[i:i + 90]
        self.assertIn("opacity: 0", fade)
        self.assertIn("opacity: 1", fade)
        self.assertNotIn("height", fade)
        calm = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\}",
                         SKEL, re.S)
        self.assertIsNotNone(calm, "the reduced-motion override is gone")
        self.assertIn(".px-shim-skel", calm.group(1))
        self.assertIn(".px-ghost-in", calm.group(1))

    def test_a_late_value_ghosts_but_its_label_stays(self):
        """Where only the VALUE is late the row never collapses: the label
        (and the sentence around the value) stays, the value ghosts. The
        VRAM gloss was the lie in Jesse's screenshot - "Card not read yet"
        rendered before the card had been asked - so the whole line ghosts
        until cfg lands; the counts keep their sentence and ghost only the
        number."""
        # 10.0: the VRAM gloss is the row's inline subline (hint), same gate
        self.assertRegex(SRC, r"(?s)hint=\{!cfg \? \(.{0,300}?<LineGhost[^>]*/>\s*\) : \(")
        self.assertIn("Card not read yet", SRC)  # reachable only past the gate now
        self.assertIn("store.options ? item.count : <ValueGhost", SRC)
        self.assertIn("known ? <>{Number(item.used)", SRC)
        self.assertRegex(SRC, r"(?s)gloss=\{cfg \? \(.{0,400}?Found.{0,400}?<ValueGhost")
        self.assertRegex(
            SRC,
            r"(?s)\{editCfg \? \(.{0,800}?hint=\{`[^`]*compatible installed\.`\}")
        self.assertRegex(
            SRC,
            r'(?s)<Field label="Whole frame".{0,120}?Runs instruction edits\.'
            r'.{0,120}?<ValueGhost')
        self.assertRegex(SRC, r"(?s)gloss=\{upscale \? \(.{0,400}?PiD repaints.{0,400}?<ValueGhost")


if __name__ == "__main__":
    unittest.main()
