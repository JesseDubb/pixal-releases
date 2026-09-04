"""Settings retains the shared Pixal controls in the roomier 2026 workspace.

These source contracts cover component wiring. Executable search/index/width
cases live in test_settings_workspace.mjs; visual geometry is a separate audit.
The About content remains frozen, independently of the new outer frame.
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
WORKSPACE = (ROOT / "web/src/components/SettingsWorkspace.jsx").read_text(encoding="utf-8")
SEARCH = (ROOT / "web/src/lib/settings-search.js").read_text(encoding="utf-8")

# The JSX below matches HEAD (1ee7850) byte-for-byte. The extraction now
# excludes the old scroll-container closing tag, which belongs to the frame.
ABOUT_SHA256 = "ca86785a1a40e98a5d35bca30ab1da081890cdf78e7af083ce385628c0c6b9ef"

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
    PILL_OPTION_H tall and 11px at the sides, idle ink textSec, the active option full accent with
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
        self.assertIn('height: PILL_OPTION_H, padding: "0 11px"', opt)
        self.assertIn("fontSize: TYPE.label", opt)
        # 550, not 500: dark ink on full chartreuse read thin, and 600 was
        # bold - "I dont want bold I just wanted slightly thicker … split the
        # difference" (Jesse, 2026-09-04). A half step only renders because
        # Geist is variable and now actually LOADS; under the Arial fallback
        # this shipped with, 550 rounded straight to bold.
        self.assertIn("fontWeight: W.emphasis", opt)
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
    """The picker trigger is the value pill: HEIGHT.rail, bg3, pill radius, label
    type at nav weight, the picked value in --text, the chevron in
    --textTer. Both pickers settings uses carry it - the panel's own
    ScrollPicker and the shared lib Picker."""

    def test_the_scrollpicker_delegates_to_the_shared_value_pill(self):
        adapter = _region(SRC, "const ScrollPicker", "// One edit-lane option")
        self.assertIn("<Picker hug", adapter)
        self.assertIn("id: item.name", adapter)
        self.assertIn("onChange={onPick}", adapter)
        self.assertNotIn("<button", adapter)
        self.assertNotIn("useState", adapter)

    def test_the_shared_picker_trigger_is_the_value_pill(self):
        trigger = _region(PICKER, '<button ref={triggerRef} type="button" aria-haspopup="listbox"',
                          "</button>")
        self.assertIn("height: HEIGHT.rail", trigger)
        self.assertIn('background: "var(--bg3)"', trigger)
        self.assertIn("borderRadius: RADIUS.pill", trigger)
        self.assertIn("fontSize: TYPE.label", trigger)
        self.assertIn("fontWeight: W.nav", trigger)
        self.assertIn('"var(--textTer)"', trigger)

    def test_no_color_literals_in_the_shared_picker(self):
        self.assertIsNone(COLOR_LITERAL.search(PICKER),
                          "a color literal crept into lib/Picker.jsx")


class LibraryPresentation(unittest.TestCase):
    """Status is honest, quiet and distinct from an available action."""

    def test_the_dim_chartreuse_register_is_still_shared(self):
        self.assertIn('accentDim: "rgba(214,243,47,0.58)"', TOKENS)
        self.assertIn('accentDim: "rgba(110,139,0,0.58)"', TOKENS)

    def test_absence_does_not_advertise_a_nonexistent_install_action(self):
        self.assertIn(">Not installed<", SRC)
        self.assertNotIn(">Install<", SRC)
        self.assertNotIn("const Badge", SRC)

    def test_families_disclose_readable_names_paths_and_sizes(self):
        family = _region(SRC, "const LibraryFamily", "LibraryFamily.settingsKind")
        self.assertIn("<Disclosure", family)
        self.assertIn("onToggle={onToggle}", family)
        row = _region(SRC, "const LibraryRow", "LibraryRow.settingsKind")
        for part in ("px-library-name", "px-library-file", "px-library-size"):
            self.assertIn(part, row)
        self.assertIn("sharedLanes", row)
        self.assertIn("overflow-wrap:anywhere", WORKSPACE)

    def test_settings_reuses_the_chat_surface_palette(self):
        chat = (ROOT / "web/src/components/Chat.jsx").read_text(encoding="utf-8")
        self.assertIn('background: rendering ? "var(--surfaceSolid)" : "var(--surface)"', chat)
        self.assertIn('background: renderBusy ? "var(--surfaceSolid)" : "var(--surface)"', SRC)
        self.assertIn('background: "var(--surfaceInset)"', chat)
        self.assertIn("background:var(--surfaceInset)", WORKSPACE)
        self.assertEqual(TOKENS.count('surfaceInset: "rgba(255,255,255,0.03)"'), 2)
        self.assertNotIn("settingsSurface:", TOKENS)
        self.assertNotIn("settingsCard:", TOKENS)
        self.assertNotIn("--bg1:", WORKSPACE)

class TheRowBeat(unittest.TestCase):
    """Reading rows can grow; shared controls keep their compact height."""

    def test_labels_and_live_hints_are_not_forced_into_one_clipped_line(self):
        field = _region(SRC, "const Field", "Field.settingsKind")
        self.assertIn("px-setting-label", field)
        self.assertIn("px-setting-hint", field)
        self.assertIn("px-setting-rail", field)
        self.assertNotIn("height:", field)
        self.assertIn("min-height:${SETTINGS.row}px", WORKSPACE)
        self.assertIn("overflow-wrap:anywhere", WORKSPACE)

    def test_one_header_divider_not_a_line_between_every_row(self):
        self.assertIn("px-settings-card-header", SRC)
        header = _region(WORKSPACE, ".px-settings-card-header {", "}")
        self.assertIn("border-bottom:1px", header)
        row = _region(WORKSPACE, ".px-setting {", "}")
        self.assertNotIn("border-top", row)
        self.assertNotIn("border-bottom", row)
        self.assertNotIn(".px-setting + .px-setting", WORKSPACE)
        group = _region(WORKSPACE, ".px-settings-group-heading {", "}")
        self.assertNotIn("border", group)

    def test_rows_travel_in_named_cards(self):
        self.assertIn('const Rows = ({ children }) => <div className="px-set-rows">', SRC)
        self.assertIn(".px-settings-group-body > .px-set-rows", WORKSPACE)
        self.assertIn("gap:${SETTINGS.cardGap}px", WORKSPACE)


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
    """Search is global, navigational and never a configuration mutation."""

    def test_the_field_sits_in_the_header_with_the_slash_hint(self):
        self.assertIn('aria-label="Search all settings"', WORKSPACE)
        self.assertIn("<kbd>/</kbd>", WORKSPACE)

    def test_slash_focuses_the_field_without_stealing_an_input_keystroke(self):
        self.assertIn('e.key !== "/"', SRC)
        self.assertIn("searchRef.current?.focus()", SRC)
        self.assertIn('t.tagName === "INPUT"', SRC)
        self.assertIn("t.isContentEditable", SRC)

    def test_all_pages_and_installed_models_feed_the_index(self):
        self.assertIn("pages={TABS.map", SRC)
        self.assertIn("matchSettings(indexPages(pages), query)", WORKSPACE)
        self.assertIn('kind === "model"', SEARCH)
        self.assertIn("optionText(props.children)", SEARCH)
        self.assertNotIn("props.value", SEARCH)

    def test_results_reveal_the_target_and_keep_the_tabstrip_visible(self):
        self.assertIn("entry.reveal?.()", WORKSPACE)
        self.assertIn("onTab(entry.tab)", WORKSPACE)
        self.assertIn("node.scrollIntoView", WORKSPACE)
        self.assertIn("node.focus({ preventScroll: true })", WORKSPACE)
        self.assertIn('role="tablist"', WORKSPACE)
        self.assertIn('role={searching ? "region" : "tabpanel"}', WORKSPACE)

    def test_the_search_writes_no_config(self):
        self.assertIn("onChange={(e) => onQuery(e.target.value)}", WORKSPACE)
        self.assertNotIn("fetch(", WORKSPACE)
        self.assertNotIn("apply(", WORKSPACE)
        self.assertNotIn("localStorage", SEARCH)

    def test_escape_clears_search_then_closes_and_a_picker_gets_first_refusal(self):
        self.assertIn('event.key !== "Escape" || event.defaultPrevented', WORKSPACE)
        self.assertIn('else onClose()', WORKSPACE)
        self.assertIn('if (query) { onQuery("");', WORKSPACE)
        self.assertIn('window.addEventListener("keydown", escape, true)', PICKER)
        self.assertIn("e.preventDefault(); e.stopPropagation();", PICKER)
        self.assertIn("triggerRef.current?.focus()", PICKER)

    def test_footer_reserves_its_space_and_keeps_the_full_message_accessible(self):
        footer = _region(WORKSPACE, ".px-settings-footer {", "}")
        self.assertIn("height:42px", footer)
        self.assertNotIn("min-height", footer)
        self.assertIn("<span title={status}>{status}</span>", WORKSPACE)


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
    """Freeze About content, not the surrounding workspace markup."""

    def test_the_about_region_is_untouched(self):
        region = _region(SRC, '{tab === "about" && (',
                         "\n    </>\n  );").rstrip()
        self.assertIn("Developed by Jesse", region)
        self.assertEqual(hashlib.sha256(region.encode("utf-8")).hexdigest(),
                         ABOUT_SHA256,
                         "the About tab changed - the brief freezes it")


if __name__ == "__main__":
    unittest.main()
