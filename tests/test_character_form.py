"""The character form, redesigned as the 10.13 casting card.

9.82 led the left pane with the composed caption: the data model's view,
output framed as the hero. Jesse, 2026-09-04: "the form is really not warm
and fun to use … we didn't group things intuitively … the controls are super
half baked. Even the crop has this thing where you need to draw the square
perfect - there are no handles." The casting card puts the portrait in a
fixed left rail, the person in a right sheet, and the composed sentence in
a full-width footer after every group. The crop dialog still opens with a
region already placed, movable, with the design system's eight resize handles.

Source-level pins on web/src/components/CharacterForm.jsx, the same way
test_segmented_control.py pins its callsites: the JSX is the contract, and a
regex that stops matching IS the regression report.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "CharacterForm.jsx").read_text(
    encoding="utf-8")


def _block(src, start_marker, end_marker):
    """The source from start_marker up to end_marker (both must exist)."""
    i = src.index(start_marker)
    j = src.index(end_marker, i + len(start_marker))
    return src[i:j]


class ThePersonLeads(unittest.TestCase):
    """The fields describe a person in the order you would describe them to a
    friend; the sentence is the READOUT and closes the whole card."""

    def test_the_sentence_band_follows_every_group(self):
        self.assertIn("<footer", SRC)
        footer = SRC.index("<footer")
        for marker in ('aria-label="Name"', "<Group label={<>Always true",
                       "<Group label={<>Wired references",
                       "<Group label={<>For the writer"):
            self.assertLess(SRC.index(marker), footer,
                            "%s sits below the sentence band" % marker)
        self.assertNotIn("Every caption carries", SRC)

    def test_the_wardrobe_lock_lives_inside_the_footer(self):
        self.assertIn("<footer", SRC)
        footer = _block(SRC, "<footer", "</footer>")
        self.assertIn("<Disclosure", footer)


class TheCropHasHandles(unittest.TestCase):
    """Jesse, 2026-09-04: "you need to draw the square perfect, there are no
    handles." The crop region is adjustable: it opens pre-placed, drags to
    move, resizes from eight handles, and a drag on the dimmed outside draws
    a fresh one. Handle geometry is the design system's locked spec."""

    def test_the_region_opens_pre_placed(self):
        # Never a blank state to get right on the first try: load sets a
        # centred region immediately.
        loaded = _block(SRC, "const loaded = () => {", "const begin")
        self.assertIn("setCrop({", loaded)

    def test_all_three_drag_modes_exist(self):
        for mode in ('begin("draw")', 'begin("move")', "begin(k)"):
            self.assertIn(mode, SRC, "%s drag mode is gone" % mode)

    def test_eight_handles_at_the_spec_geometry(self):
        # Corner dots 10px circles, edge pills 18x6 / 6x18, white with a
        # 25%-alpha hairline, no shadows - the locked handle spec.
        self.assertEqual(len(re.findall(r'\{ k: "\w+",\s+fx:', SRC)), 8)
        self.assertIn("width: 10, height: 10, borderRadius: 999", SRC)
        self.assertIn("width: 6, height: 18", SRC)
        self.assertIn("width: 18, height: 6", SRC)
        self.assertIn('border: "1px solid rgba(0, 0, 0, 0.25)"', SRC)
        handles = _block(SRC, "CROP_HANDLES.map", "</div>")
        self.assertNotIn("boxShadow", handles, "handles carry no shadows")

    def test_resize_clamps_to_a_minimum(self):
        self.assertIn("const CROP_MIN = 24;", SRC)

    def test_the_frame_is_the_one_pixel_white_of_the_spec(self):
        self.assertIn('border: "1px solid #FFFFFF"', SRC)
        self.assertIn('cursor: "move"', SRC)


class TheControlsAreShared(unittest.TestCase):
    """The shared controls remain shared; only the face rail has the bespoke
    horizontal strip the approved mockup calls for."""

    def test_one_button_two_kinds(self):
        self.assertIn("const Btn = (", SRC)
        # The primary kind appears where an action commits: save, use-crop.
        self.assertGreaterEqual(SRC.count('<Btn kind="primary"'), 2)

    def test_input_browser_stays_only_in_the_accessory_picker(self):
        self.assertIn("const InputBrowser = (", SRC)
        self.assertEqual(SRC.count("<InputBrowser"), 1,
                         "only AccessoryPicker keeps the full browser")


class TheEditFollowsTheLane(unittest.TestCase):
    """The queued 10.11 follow-up: this second EditDirector caller read
    qwen_edit unconditionally and its result watcher excluded klein_edit -
    so with Settings routing whole-frame edits to Klein, the edit fired on
    one lane and the form waited for another."""

    def test_the_routes_come_from_the_server(self):
        self.assertIn('editRoutes.whole_frame || "qwen_edit"', SRC)
        self.assertIn('editRoutes.masked || "klein_inpaint"', SRC)

    def test_the_watcher_accepts_every_edit_lane(self):
        for lane in ('"qwen_edit"', '"klein_edit"', '"klein_inpaint"'):
            self.assertIn("e.template === %s" % lane, SRC)

    def test_the_director_learns_the_whole_frame_lane(self):
        self.assertIn("wholeFrameRecipe={editRecipe}", SRC)


class SexIsTheSharedControl(unittest.TestCase):
    """The hand-rolled three-button row is replaced by the ONE segmented
    control (9.23b) - the grid variant, so the three labels can never clip."""

    def test_the_hand_rolled_row_is_gone(self):
        self.assertNotIn('["female", "male", "other"].map', SRC,
                         "the hand-rolled sex buttons are back")
        self.assertNotIn('role="radiogroup"', SRC,
                         "radiogroup semantics belong to the lib component")

    def test_the_edit_reads_inside_the_modal(self):
        """A photo edit used to sample behind the dialog with no sign of it
        (Jesse, 2026-09-04). The portrait now carries the app's generation
        effect and the job's own step counter - the SAME DotMatrix and bar a
        job card shows, subscribed per job so a step repaints only the tile."""
        self.assertIn("const EditingVeil = ", SRC)
        self.assertIn('import { api, useJobLive } from "../store.js";', SRC)
        self.assertIn('import { DotMatrix } from "../lib/DotMatrix.jsx";', SRC)
        veil = SRC[SRC.index("const EditingVeil = "):]
        veil = veil[:veil.index("\n};")]
        self.assertIn("useJobLive(jobId)", veil)
        self.assertIn("<DotMatrix preview={live.preview}", veil)
        self.assertIn("sampling ${p.value}/${p.max}", veil)
        self.assertIn("GLASS_SOLID.background", veil,
                      "the face dims under the effect")
        self.assertRegex(SRC, r"pendingEdit \? \(\s*<EditingVeil")

    def test_a_profile_edit_never_posts_into_the_chat(self):
        """The photo edit renders where the user is looking. It used to post a
        job card into the conversation behind the modal - two cards animating
        one render (Jesse, 2026-09-04). The job is silent in the lane; it still
        samples, still calms the UI, still lands in the ledger."""
        store = (ROOT / "web" / "src" / "store.js").read_text(encoding="utf-8")
        self.assertIn("const silentCids = new Set();", store)
        self.assertIn("silentCids.add(correlate);", store)
        job = store[store.index('    case "job":'):]
        job = job[:job.index('    case "jobinfo"')]
        self.assertIn("if (d.cid && silentCids.delete(d.cid)) { emit(); break; }",
                      job)
        self.assertLess(job.index("silentCids.delete"), job.index("appendMsg("),
                        "the silence check has to come BEFORE the message")

    def test_the_shared_heights_are_declared_before_they_are_read(self):
        """A const read above its own declaration is a temporal dead zone -
        FACE_ACTION read FIELD_H from 57 lines below it and the chips rendered
        14px tall (2026-09-04). Declaration order is the pin."""
        self.assertLess(SRC.index("const FIELD_H = 34;"),
                        SRC.index("const FACE_ACTION"),
                        "FIELD_H must be declared before anything reads it")
        self.assertLess(SRC.index("const NAME_H"), SRC.index("const Group"))

    def test_the_name_is_a_field_not_a_square(self):
        """It is display type, but it is still a field: a field's radius (its
        focus ring was a bare square), a field's 12px text inset so the name
        and the age below it share an axis, and an even height."""
        i = SRC.index('aria-label="Name"')
        name = SRC[i:i + 700]
        self.assertIn("borderRadius: RADIUS.card", name)
        self.assertIn("padding: `0 ${SPACE[12]}px`", name)
        self.assertIn("height: NAME_H", name)
        self.assertRegex(SRC, r"const NAME_H = 44;")

    def test_the_face_actions_land_on_whole_pixels(self):
        """276 / 3 with an 8px gap is 86.666px per chip and a 7.9px gap - the
        half-pixel spacing Jesse called out on 2026-09-04. A 3-column grid at
        gap 6 makes every chip exactly 88, and one content inset puts all three
        icons on the same axis."""
        self.assertIn("const FACE_ACTION_GAP = SPACE[6];", SRC)
        self.assertIn('gridTemplateColumns: "repeat(3, 1fr)"', SRC)
        face = SRC[SRC.index("const FACE_ACTION = {"):]
        face = face[:face.index("};")]
        self.assertIn('justifyContent: "center"', face,
                      "equal boxes read balanced with their content centred")
        self.assertIn("height: FIELD_H", face,
                      "the actions sit on the form's one height")
        self.assertIn("padding: `0 ${SPACE[12]}px`", face)
        self.assertIn("gap: SPACE[8]", face, "12 + 12 + 8 puts the label at 32")
        self.assertIn('boxShadow: "inset 0 0 0 1px var(--border)"', face,
                      "a 1px border would push every distance to an odd number")
        self.assertIn('border: "none"', face)
        self.assertEqual(SRC.count("style={FACE_ACTION}"), 2)
        self.assertNotIn('style={{ flex: 1, minWidth: 0, height: 32, padding: 0,', SRC)

    def test_the_row_of_controls_shares_one_height(self):
        """ONE height for every control in the form - DESIGN.md's 34 beat.
        Shrinking age and race to 30 to match the toggle made them one-offs
        against the 34px fields (Jesse, 2026-09-04); the toggle takes the beat
        instead. One named constant, used by every control."""
        self.assertRegex(SRC, r"const FIELD_H = 34;")
        m = re.search(r"<SegmentedControl\b(.+?)/>", SRC, re.S)
        self.assertIn("height: FIELD_H", m.group(1),
                      "the sex track takes the row's height, not its own")
        for label in ('aria-label="Age"', 'aria-label="Race"'):
            i = SRC.index(label)
            field = SRC[i:i + 400]
            self.assertIn("height: FIELD_H", field,
                          label + " must take the row's height")
        self.assertNotRegex(SRC, r"height: 30,\s+minWidth: 0,\s+\n?\s*display: \"flex\"",
                            "the row itself takes the constant too")

    def test_the_callsite_is_the_pill_variant(self):
        self.assertIn('from "../lib/SegmentedControl.jsx"', SRC)
        self.assertEqual(SRC.count("<SegmentedControl"), 1,
                         "exactly one segmented control - the sex row")
        m = re.search(r"<SegmentedControl\b(.+?)/>", SRC, re.S)
        self.assertIsNotNone(m, "no SegmentedControl callsite at all")
        call = m.group(1)
        self.assertIn('variant="pill"', call)
        self.assertIn("ariaLabel", call,
                      "the group takes its accessible name from ariaLabel")
        self.assertIn('{ v: "female", label: "Female" }', call,
                      "options drifted from the one-key `v` contract")

    def test_the_label_less_meta_row_names_every_control(self):
        self.assertIn('as: Tag = "label"', SRC)
        self.assertNotIn('label="Sex"', SRC)
        self.assertIn('aria-label="Age"', SRC)
        self.assertIn('aria-label="Race"', SRC)
        self.assertIn('ariaLabel="sex"', SRC)


class ThePreviewTracksItsFields(unittest.TestCase):
    """The preview re-runs from every field that feeds the composed sentence;
    a field missing from the effect types into a stale card."""

    EFFECT = _block(SRC, "// Debounced so typing a name", "characterPreview(ch)")

    def test_the_payload_carries_all_nine_composed_fields(self):
        # 9.95: build, hair and grooming joined the composed sentence.
        for piece in ("name: name.trim()", "sex,", "style: style.trim()",
                      "wardrobe_lock: wardrobe.trim()", "ch.age", "ch.race",
                      "build: build.trim()", "hair: hair.trim()",
                      "grooming: grooming.trim()"):
            self.assertIn(piece, self.EFFECT,
                          "%s no longer feeds the preview" % piece)

    def test_the_dep_array_lists_all_nine(self):
        self.assertIn("}, [name, age, race, sex, style, wardrobe, build, hair, grooming]);",
                      SRC,
                      "a field was dropped from the preview effect's deps")


class TheFieldsTellTheTruth(unittest.TestCase):
    """Labels are sentence case nouns; each rule keeps exactly one channel.
    The copy that taught false things - notes inviting the jobs-and-lifestyle
    backstory SYSTEM_LOCAL tells the writer to discard - is gone."""

    def test_the_false_teaching_is_gone(self):
        for dead in ("who they are off-camera", "barista",
                     "how they read at a glance"):
            self.assertNotIn(dead, SRC, '"%s" is back' % dead)

    def test_each_rule_remains_in_its_single_channel(self):
        # The photo-decides-the-face fact stays where the photo IS: on the
        # left portrait/drop target after the casting-card relayout.
        self.assertIn("The photo decides the face — nothing typed here changes it.",
                      SRC)
        self.assertRegex(
            SRC,
            r'<Group label=\{<>Always true <InfoTip\b[^>]*'
            r'text="only what is true in every picture — what changes shot to shot belongs in the prompt"')
        self.assertRegex(
            SRC,
            r'<Group label=\{<>For the writer <InfoTip\b[^>]*'
            r'text="look and identity only, not jobs or lifestyle"')

    def test_grooming_example_keeps_every_scope_fact(self):
        self.assertIn(
            'placeholder="manicured nails, small hoop earrings, natural makeup"',
            SRC)


class TheCastingCardSurface(unittest.TestCase):
    """The approved mockup's defining shapes are source-level contracts."""

    def test_the_portrait_is_three_four_and_crops_to_cover(self):
        self.assertIn('aspectRatio: "3 / 4"', SRC)
        self.assertRegex(
            SRC, r'(?s)aspectRatio: "3 / 4".*?'
                 r'<img src=\{inputFullUrl\(ref\)\}')
        photo = re.search(
            r'<img src=\{inputFullUrl\(ref\)\}.*?'
            r'style=\{\{(.*?)\}\}\s*/>', SRC, re.S)
        self.assertIsNotNone(photo)
        for pin in ('objectFit: "cover"', "inset: -1",
                    'width: "calc(100% + 2px)"',
                    'height: "calc(100% + 2px)"'):
            self.assertIn(pin, photo.group(1))

    def test_the_portrait_veils_the_full_filename(self):
        # The folder and the count are the search field's tooltip now,
        # not a line of their own.
        self.assertIn("Swap the photo — ComfyUI/input", SRC)
        self.assertRegex(SRC, r'className="px-cast-search" title=\{summary\}')
        self.assertIn("<MagnifyingGlass", SRC)
        photo = SRC.index('<img src={inputFullUrl(ref)}')
        actions = SRC.index("{/* FACE ACTIONS */}", photo)
        portrait = SRC[photo:actions]
        self.assertRegex(portrait, r'background:\s*["`]linear-gradient\(')
        for pin in ("fontFamily: MONO", "fontSize: TYPE.micro", "title={ref}",
                    'textOverflow: "ellipsis"'):
            self.assertIn(pin, portrait)

    def test_name_is_display_type_not_a_field_row(self):
        self.assertNotIn('<Field label="Name">', SRC)
        mark = SRC.index('aria-label="Name"')
        start = SRC.rfind("<input", 0, mark)
        name = SRC[start:SRC.index("/>", mark)]
        for pin in ('background: "transparent"', 'border: "none"',
                    "fontSize: 28", "fontWeight: W.heading",
                    'letterSpacing: "-0.01em"',
                    'caretColor: "var(--accent)"', 'placeholder="Mia"'):
            self.assertIn(pin, name)

    def test_footer_is_the_bg0_sentence_band_and_save_is_a_pill(self):
        self.assertIn("<footer", SRC)
        footer = _block(SRC, "<footer", "</footer>")
        for pin in ('background: "var(--bg0)"',
                    'borderTop: "1px solid var(--border)"',
                    'color: "var(--cream)"',
                    '{preview?.subject || "…"}'):
            self.assertIn(pin, footer)
        save = _block(footer, '<Btn kind="primary"', "</Btn>")
        for pin in ("height: 34", "borderRadius: RADIUS.pill",
                    'color: "var(--accentInk)"'):
            self.assertIn(pin, save)

    def test_identity_picker_is_a_horizontal_strip_with_a_selected_ring(self):
        self.assertRegex(
            SRC, r'(?s)px-cast-search.*?'
                 r'className="px-scroll".*?overflowX: "auto".*?'
                 r'overflowY: "hidden"')
        self.assertRegex(SRC, r'width:\s*(?:compact\s*\?\s*)?56')
        self.assertRegex(SRC, r'height:\s*(?:compact\s*\?\s*)?56')
        self.assertRegex(
            SRC, r'boxShadow:\s*(?:compact\s*&&\s*)?selected\s*\?\s*'
                 r'"0 0 0 1px var\(--accentStr\)"')
        self.assertIn('borderColor: selected ? "var(--accent)"', SRC)
        strip = _block(SRC, "const IdentityStrip =", "// ------------------------------------------------------------------ CropDialog")
        self.assertIn("selected={selected}", strip)
        self.assertIn('contentVisibility: "auto"', SRC)


if __name__ == "__main__":
    unittest.main()
