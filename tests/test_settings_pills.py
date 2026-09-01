"""Brief 10.0 — Settings speaks the pill language on a strict beat.

The blessed mockup (briefs/ref/settings-pills/v6-blessed.png) defines one
control family — the pixal toggle (42x16, dark-ink knob on chartreuse), the
pill selector (2-4 options hugging their labels on a right-hand rail), the
value pill (24px picker trigger) and the two badge registers — and one
rhythm: every setting row is ONE 34px line, the label with its one-fact
subline inline, the control on the right rail; section titles take the
cluster register (micro caps, hairline right). Restyle centrally: the shared
Switch / SegmentedControl / Section / Field carry the skin, callsites
migrate onto them.

These tests are static in the style of test_composer_canvas.py - this repo
has no JS runner, so the contracts assert the structure of the source. Every
behaviour test here was proven RED against the pre-fix tree (3d56e64): the
old Switch was a 30x17 accentMut-wash toggle, SegmentedControl had no pill
variant, the pickers were 38/28px input-radius triggers, the panel was a
stacked wall with micro-caps Field labels above full-width controls, the tab
read "Brain", there was no search and no badge. The two guard tests (About
byte-identity, no --success) pass on both trees; their teeth were proven by
mutation.
"""

import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "web" / "src" / "components" / "SettingsMenu.jsx"
SRC = SETTINGS.read_text(encoding="utf-8")
SWITCH = (ROOT / "web" / "src" / "lib" / "Switch.jsx").read_text(encoding="utf-8")
SEG = (ROOT / "web" / "src" / "lib" / "SegmentedControl.jsx").read_text(encoding="utf-8")
PICKER = (ROOT / "web" / "src" / "lib" / "Picker.jsx").read_text(encoding="utf-8")
TOKENS = (ROOT / "web" / "src" / "lib" / "design-tokens.js").read_text(encoding="utf-8")

# The About tab is frozen by the brief ("I like the about page so dont touch
# that"): this is the sha256 of its extracted JSX region on the start commit
# 3d56e64. One changed byte inside the region - a space, a comma - and the
# hash misses.
ABOUT_SHA256 = "c74849e9252fc22ed11eee01f83dd87d2b643120e297336a84f76dc4d75ae478"

COLOR_LITERAL = re.compile(r"#[0-9A-Fa-f]{3,8}\b|rgba?\(")


def _region(src, start_mark, end_mark):
    """Slice src[start_mark … end_mark). Both marks must exist - a missing
    mark means the structure the test reads is gone, which is a failure with
    a message, not a blind pass."""
    start = src.index(start_mark)
    end = src.index(end_mark, start)
    return src[start:end]


def _tag_end(src, start):
    """Index just past the closing '>' of the JSX open tag at `start`,
    respecting {…} nesting (the house scanner, verbatim from
    test_settings_copy.py - a label prop can itself hold JSX)."""
    depth = 0
    j = start
    while j < len(src):
        c = src[j]
        if c in '"\'':
            q = c
            j += 1
            while src[j] != q:
                if src[j] == '\\':
                    j += 1
                j += 1
        elif c == '`':
            j += 1
            while src[j] != '`':
                j += 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == '>' and depth == 0:
            return j + 1
        j += 1
    raise ValueError("unterminated tag")


def _field_labels():
    """Every Field row's label text's first character, from string-literal
    labels (label="Appearance") and fragment labels (label={<>Skin finish …}).
    The sentence-case pass lives in the strings, so the test reads them."""
    for m in re.finditer(r"<Field\s", SRC):
        tag = SRC[m.start():_tag_end(SRC, m.start())]
        lit = re.search(r'\blabel="((?:[^"\\]|\\.)*)"', tag)
        if lit:
            yield lit.group(1)
            continue
        frag = re.search(r"\blabel=\{<>([^<]{0,60})", tag)
        if frag:
            yield frag.group(1).strip()


class PixalToggleGeometry(unittest.TestCase):
    """The shared Switch IS the pixal toggle: wide, low, pill - 42x16 track,
    an 11px knob 2px inset, and the signature dark-ink knob on chartreuse.
    Jesse: "pill toggles, the wider not so high toggle style ... make them
    unique to pixal" - the white knob is everyone else's toggle."""

    def test_the_track_is_42x16_pill(self):
        self.assertIn("width: 42", SWITCH)
        self.assertIn("height: 16", SWITCH)
        self.assertIn("borderRadius: RADIUS.pill", SWITCH)

    def test_on_is_accent_track_with_accentink_knob(self):
        self.assertIn('background: on ? "var(--accent)" : "var(--bg4)"', SWITCH)
        self.assertIn('"var(--accentInk)"', SWITCH)

    def test_off_is_bg4_track_bordered_with_bg1_knob(self):
        self.assertIn('"var(--bg4)"', SWITCH)
        self.assertIn('"var(--borderStr)"', SWITCH)
        self.assertIn('"var(--bg1)"', SWITCH)

    def test_the_knob_is_11px_and_slides_on_motion_state(self):
        self.assertIn("width: 11", SWITCH)
        self.assertIn("height: 11", SWITCH)
        self.assertIn("MOTION.state", SWITCH)

    def test_no_color_literals_in_the_toggle(self):
        self.assertIsNone(COLOR_LITERAL.search(SWITCH),
                          "a color literal crept into Switch.jsx")


class PillSelectorSpecs(unittest.TestCase):
    """variant="pill" on the one shared SegmentedControl: the bg3 track with
    a hairline border and 2px padding/gap, options hugging their label at
    3px 11px, idle ink textSec, the active option full accent with
    accentInk text - the full-intensity register of the one color story."""

    def test_the_pill_variant_exists_on_the_shared_component(self):
        self.assertIn('variant === "pill"', SEG)

    def test_the_track_spec(self):
        track = _region(SEG, "const PILL_TRACK", "};")
        self.assertIn('background: "var(--bg3)"', track)
        self.assertIn('border: "1px solid var(--border)"', track)
        self.assertIn("borderRadius: RADIUS.pill", track)
        self.assertIn("padding: 2", track)
        self.assertIn("gap: 2", track)
        self.assertIsNone(COLOR_LITERAL.search(track))

    def test_the_option_spec(self):
        opt = _region(SEG, "const pillStyle", "};")
        self.assertIn('"3px 11px"', opt)
        self.assertIn("fontSize: TYPE.label", opt)
        self.assertIn("fontWeight: W.nav", opt)
        self.assertIn('"var(--textSec)"', opt)
        self.assertIn('background: active ? "var(--accent)" : "transparent"', opt)
        self.assertIn('"var(--accentInk)"', opt)
        self.assertIn("borderRadius: RADIUS.pill", opt)
        self.assertIsNone(COLOR_LITERAL.search(opt))

    def test_settings_rows_ride_the_pill_variant(self):
        # every SegmentedControl in SettingsMenu migrated onto the pill skin
        uses = re.findall(r"<SegmentedControl\b(?![^>]*variant=)", SRC)
        self.assertEqual(uses, [],
                         "%d settings SegmentedControl(s) did not migrate to "
                         'variant="pill"' % len(uses))


class ValuePillSpecs(unittest.TestCase):
    """The picker trigger is the value pill: 24px, bg3, pill radius, label
    type at nav weight, the picked value in --text, the chevron in
    --textTer. Both pickers settings uses carry it - the panel's own
    ScrollPicker and the shared lib Picker."""

    def test_the_scrollpicker_trigger_is_the_value_pill(self):
        trigger = _region(SRC, "const ScrollPicker", "// One edit-lane option")
        self.assertIn("height: 24", trigger)
        self.assertIn('background: "var(--bg3)"', trigger)
        self.assertIn("borderRadius: RADIUS.pill", trigger)
        self.assertIn("fontSize: TYPE.label", trigger)
        self.assertIn("fontWeight: W.nav", trigger)
        self.assertIn('"var(--textTer)"', trigger)   # the chevron's ink

    def test_the_shared_picker_trigger_is_the_value_pill(self):
        trigger = _region(PICKER, '<button type="button" aria-haspopup="listbox"',
                          "</button>")
        self.assertIn("height: 24", trigger)
        self.assertIn('background: "var(--bg3)"', trigger)
        self.assertIn("borderRadius: RADIUS.pill", trigger)
        self.assertIn("fontSize: TYPE.label", trigger)
        self.assertIn("fontWeight: W.nav", trigger)
        self.assertIn('"var(--textTer)"', trigger)

    def test_no_color_literals_in_the_shared_picker(self):
        self.assertIsNone(COLOR_LITERAL.search(PICKER),
                          "a color literal crept into lib/Picker.jsx")


class BadgeRegisters(unittest.TestCase):
    """Two badge registers, both pill micro type: state-satisfied (Installed)
    is the DIMMED chartreuse - never --success, the old sage was the wrong
    green; action (Install) is the outlined-mid register. The dim values are
    tokens (accentDim/accentDimMut) so light mode flips them with the theme;
    no color literals in the component."""

    def test_the_dim_chartreuse_register_is_a_token(self):
        self.assertIn('accentDim: "rgba(214,243,47,0.58)"', TOKENS)
        self.assertIn('accentDimMut: "rgba(214,243,47,0.07)"', TOKENS)
        # light mode: the same register derived from the olive accent
        self.assertIn('accentDim: "rgba(110,139,0,0.58)"', TOKENS)
        self.assertIn('accentDimMut: "rgba(110,139,0,0.07)"', TOKENS)

    def test_the_badge_component_carries_both_registers(self):
        badge = _region(SRC, "const Badge", ");")
        self.assertIn('"var(--accentDim)"', badge)
        self.assertIn('"var(--accentDimMut)"', badge)
        self.assertIn('"var(--accent)"', badge)
        self.assertIn('"var(--accentMut)"', badge)
        self.assertIn("var(--accentStr)", badge)   # the 1px outline

        self.assertIn("fontSize: TYPE.micro", badge)
        self.assertIn("fontWeight: W.nav", badge)
        self.assertIn('"0.04em"', badge)
        self.assertIn("borderRadius: RADIUS.pill", badge)
        self.assertIsNone(COLOR_LITERAL.search(badge),
                          "the badge mixes its own colors instead of the tokens")

    def test_installed_never_wears_success_green(self):
        self.assertNotIn("--success", SRC)
        self.assertIn(">Installed<", SRC)

    def test_the_action_register_renders_where_absence_is_known(self):
        # visual state only: no install flow in this brief, so no handler
        badge = _region(SRC, "const Badge", ");")
        self.assertNotIn("onClick", badge)
        self.assertNotIn("cursor", badge)   # not even a pointer - it is not a button
        self.assertIn(">Install<", SRC)


class TheRowBeat(unittest.TestCase):
    """Every setting row is ONE 34px line: label TYPE.body at body weight,
    the one-fact subline inline at TYPE.label/300 in textTer, nowrap with
    ellipsis, the control on a right-hand rail. Section titles take the
    cluster register: TYPE.micro, W.nav, uppercase, .09em, textTer, hairline
    running right."""

    def test_the_row_is_34px_with_the_inline_subline(self):
        field = _region(SRC, "const Field", "// Cluster heading")
        self.assertIn("height: 34", field)
        self.assertIn("fontSize: TYPE.body", field)
        self.assertIn("fontWeight: W.body", field)
        self.assertIn("fontSize: TYPE.label", field)
        self.assertIn("fontWeight: W.label", field)
        self.assertIn('"var(--textTer)"', field)
        self.assertIn('whiteSpace: "nowrap"', field)
        self.assertIn('textOverflow: "ellipsis"', field)
        self.assertIn('marginLeft: "auto"', field)   # the right-hand rail

    def test_section_titles_take_the_cluster_register(self):
        section = _region(SRC, "const Section", "const inputStyle")
        self.assertIn("fontSize: TYPE.micro", section)
        self.assertIn("fontWeight: W.nav", section)
        self.assertIn('"uppercase"', section)
        self.assertIn('"0.09em"', section)
        self.assertIn('"var(--textTer)"', section)
        self.assertIn('borderTop: "1px solid var(--border)"', section)

    def test_rows_travel_in_named_runs(self):
        # consecutive rows touch; a run continuing its cluster after a
        # Section sits 16 under it, not a full section gap away
        self.assertIn('"px-set-rows px-set-rows--cont"', SRC)
        self.assertIn("<Rows>", SRC)
        css = _region(SRC, "const CSS = `", "`;")
        self.assertIn(".px-set-rows--cont", css)


class ToggleMigration(unittest.TestCase):
    """The mockup's binary rows are pixal toggles, not two-option pill rows:
    skin finish, shine removal, the H3 2x default and official prompting all
    migrate onto the shared Switch with their stored values and apply
    payloads unchanged (restyle, not restructure)."""

    def test_the_switch_is_imported(self):
        self.assertIn('import { Switch } from "../lib/Switch.jsx";', SRC)

    def test_the_four_binary_settings_are_toggles(self):
        # 10.1 swapped the seat: skin finish (retired) -> film grain.
        for value in ["on={stillCfg.film_grain}",
                      "on={stillCfg.de_shine}",
                      "on={videoCfg.upscale_2x}",
                      "on={officialPrompting}"]:
            self.assertIn(value, SRC, "a binary row did not become a toggle")
        self.assertNotIn("skin_finish", SRC, "skin1x is retired (10.1)")

    def test_the_toggles_keep_their_apply_payloads(self):
        self.assertIn("apply({ still: { film_grain: on } }", SRC)
        self.assertIn("apply({ still: { de_shine: on } }", SRC)
        self.assertIn("apply({ video: { upscale_2x: on } }", SRC)
        self.assertIn("apply({ llm: { official_prompting: on } }", SRC)


class ChatTabLabel(unittest.TestCase):
    """Brain is Chat (Jesse: "brain should be chat") - the LABEL only: the
    persisted tab id stays "brain" so pixal.settings.tab survives, and a
    saved "brain" still restores to the same room."""

    def test_the_brain_tab_renders_as_chat(self):
        self.assertIn('{ id: "brain", label: "Chat" }', SRC)
        self.assertNotIn('{ id: "brain", label: "Brain" }', SRC)

    def test_the_persisted_tab_id_is_unchanged(self):
        self.assertIn('"pixal.settings.tab"', SRC)
        m = re.search(r"const TABS = \[(.*?)\];", SRC, re.S)
        ids = re.findall(r'\{ id: "(\w+)"', m.group(1))
        self.assertEqual(ids, ["general", "image", "video", "models",
                               "brain", "about"])


class SearchSettings(unittest.TestCase):
    """The header carries the search field; '/' focuses it; the filter is a
    case-insensitive match on section titles AND row labels, hiding
    non-matching rows and empty sections while typing and restoring
    everything on an empty query. Client-side only - no config writes."""

    def test_the_field_sits_in_the_header_with_the_slash_hint(self):
        self.assertIn('placeholder="Search settings"', SRC)
        self.assertIn("<kbd", SRC)

    def test_slash_focuses_the_field(self):
        self.assertIn('e.key !== "/"', SRC)   # the guard that keys on "/"
        self.assertIn("searchRef.current?.focus()", SRC)

    def test_the_filter_is_case_insensitive_and_covers_titles_and_labels(self):
        self.assertIn(".toLowerCase()", SRC)
        section = _region(SRC, "const Section", "const inputStyle")
        field = _region(SRC, "const Field", "// Cluster heading")
        self.assertIn("textOf(title)", section)
        self.assertIn("textOf(label)", field)

    def test_non_matching_rows_and_empty_sections_hide(self):
        section = _region(SRC, "const Section", "const inputStyle")
        field = _region(SRC, "const Field", "// Cluster heading")
        self.assertIn("return null", section)
        self.assertIn("return null", field)

    def test_the_search_writes_no_config(self):
        # the field's onChange only sets local state - an apply() on
        # keystrokes would spam config.json (the live-machine rule)
        self.assertIn("onChange={(e) => setQuery(e.target.value)}", SRC)
        search = _region(SRC, 'placeholder="Search settings"', "</div>")
        self.assertNotIn("apply(", search)


class SentenceCaseLabels(unittest.TestCase):
    """The sentence-case pass on row labels ("Text encoder", "Whole frame",
    "Brain runs on") - capital first letter in the string, never in CSS."""

    def test_every_row_label_starts_with_a_capital(self):
        labels = list(_field_labels())
        self.assertGreater(len(labels), 10, "the label sweep went blind")
        offenders = [l for l in labels if l and l[0].islower()]
        self.assertEqual(offenders, [],
                         "row labels starting lowercase: %s" % offenders)


class AboutByteIdentical(unittest.TestCase):
    """The About tab ships byte-identical to the start commit (Jesse: "I
    like the about page so dont touch that"). The region runs from the
    `{tab === "about" && (` mark to the auto-saves comment; the hash pins
    every byte of it, and the markers + a known string pin the extraction
    itself, so an empty or shifted region fails too."""

    def test_the_about_region_is_untouched(self):
        region = _region(SRC, '{tab === "about" && (',
                         "{/* Every control auto-saves")
        self.assertIn("Developed by Jesse", region)
        self.assertEqual(hashlib.sha256(region.encode("utf-8")).hexdigest(),
                         ABOUT_SHA256,
                         "the About tab changed - the brief freezes it")


if __name__ == "__main__":
    unittest.main()
