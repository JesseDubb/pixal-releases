"""Brief 9.17b — Settings: cut the copy.

Settings carried ~435 words of prose around 13 controls (33.5 each), many
with a paragraph above AND another below. Jesse: "People dont like to read
and when you put multiple multiline paragraphs around controls it makes the
interface very hard to navigate and understand." The deal:

  - no control carries prose both above (gloss) and below (footnote/hint)
  - <= 10 visible words per control; the why and the caveat move to InfoTip
  - under 150 visible words total
  - live values ("3 installed", "the card reads as 32 GB", "Found 614
    files") stay visible - status, not help - and never inside a tip
  - warnings stay visible, just shorter (the PiD experimental note and the
    non-commercial licence note)
  - tips stay keyboard reachable; one per control
  - /api/settings write surface stays frozen

How words are counted (static source analysis; no JS runtime): the surfaces
are every Section's `gloss`, every Field's `hint`, every <Foot>, and the two
LockKey trust notes in the brain tab. A slot expression containing a ternary
is counted at its longest branch - the most prose that can be on screen at
once; "+"-concatenated literals in one branch are merged first. ${...}
interpolations are live values and count as zero words, but the static text
framing them counts. A word is a whitespace token containing a letter or
digit.

These hang off a unittest.TestCase because `unittest discover` is this
repo's runner and CI's; bare module-level test functions are collected by
pytest locally and silently skipped by the gate (that is what happened to
9.17a's tests before 941c84c rescued them).
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "SettingsMenu.jsx").read_text(encoding="utf-8")
TIP_SRC = (ROOT / "web" / "src" / "components" / "InfoTip.jsx").read_text(encoding="utf-8")
HELP = (ROOT / "HELP.md").read_text(encoding="utf-8")

WORD = re.compile(r"[A-Za-z0-9]")


def _scan_prop_expr(src, start):
    """src[start] is the first char of a JSX prop value: a "..." literal or a
    {…} expression. Returns the expression source. Braces/parens/brackets
    nest; string and template literals are opaque (their ${…} interpolations
    are balanced in this codebase)."""
    i = start
    if src[i] == '"':
        j = i + 1
        while src[j] != '"':
            j += 1
        return src[i:j + 1]
    assert src[i] == '{', "unexpected prop value: %r" % src[i:i + 40]
    depth = 0
    j = i
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
            if depth == 0:
                return src[i:j + 1]
        j += 1
    raise ValueError("unbalanced expression")


def _tag_end(src, start):
    """Index just past the closing '>' of the JSX open tag at `start`,
    respecting {…} nesting (a title prop can itself hold JSX now)."""
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


def _props(tag_src):
    out = {}
    for m in re.finditer(r'(\w+)=(?=["{])', tag_src):
        out[m.group(1)] = _scan_prop_expr(tag_src, m.end())
    return out


def _lit_words(lit):
    body = re.sub(r"\$\{[^}]*\}", " ", lit)
    return sum(1 for tok in body.split() if WORD.search(tok))


def _expr_words(expr):
    # merge "+"-concatenated literals first: they are one branch, not two
    merged = re.sub(r'(["\'])\s*\+\s*\1', "", expr)
    lits = re.findall(r'"(?:[^"\\]|\\.)*"|`[^`]*`|\'(?:[^\'\\]|\\.)*\'', merged)
    counts = [_lit_words(l) for l in lits]
    if not counts:
        return 0
    return max(counts) if "?" in expr else sum(counts)


def _sections():
    tags = list(re.finditer(r"<Section\s", SRC))
    for i, m in enumerate(tags):
        end_of_tag = _tag_end(SRC, m.start())
        end = tags[i + 1].start() if i + 1 < len(tags) else len(SRC)
        gl = SRC.find("<GroupLabel>", m.start(), end)
        block = SRC[m.start():gl if gl != -1 else end]
        yield _props(SRC[m.start():end_of_tag]), block


def _field_props(block):
    for m in re.finditer(r"<Field\s", block):
        yield _props(block[m.start():_tag_end(block, m.start())])


def _text_words(jsx):
    inner = re.sub(r"\{[^}]*\}|&apos;", " ", jsx)
    return sum(1 for tok in inner.split() if WORD.search(tok))


def _foot_words(block):
    return sum(_text_words(m.group(1))
               for m in re.finditer(r"<Foot>(.*?)</Foot>", block, re.S))


def _note_words(block):
    """The LockKey trust notes: one per chat-brain mode, so the longer of
    the two is the most that can be on screen."""
    counts = [_text_words(m.group(1))
              for m in re.finditer(r"<LockKey[^/]*/>(.*?)</div>", block, re.S)]
    return max(counts) if counts else 0


def _hints(block):
    """(unconditional_words, max_conditional_words) — a conditional hint is
    live status or a warning about the current state, not help prose."""
    uncond, cond = 0, 0
    for fp in _field_props(block):
        if "hint" not in fp:
            continue
        if "?" in fp["hint"]:
            cond = max(cond, _expr_words(fp["hint"]))
        else:
            uncond += _expr_words(fp["hint"])
    return uncond, cond


def _slots():
    """(title, gloss_words, below_words, conditional_hint_words) per Section.
    below = footnote + unconditional hint + trust note: the prose a control
    can carry under itself."""
    out = []
    for props, block in _sections():
        gloss = _expr_words(props["gloss"]) if "gloss" in props else 0
        hu, hc = _hints(block)
        below = _foot_words(block) + hu + _note_words(block)
        out.append((props.get("title", "")[:50], gloss, below, hc))
    return out


def _tip_texts():
    """Every InfoTip's text expression in SettingsMenu."""
    out = []
    for m in re.finditer(r"<InfoTip\s", SRC):
        props = _props(SRC[m.start():_tag_end(SRC, m.start())])
        out.append(props.get("text"))
    return out


def _visible_strings():
    """Every string literal in a visible-prose surface (gloss, hint, Foot,
    trust note) - never an InfoTip text."""
    out = []
    for props, block in _sections():
        if "gloss" in props:
            out += re.findall(r'"(?:[^"\\]|\\.)*"|`[^`]*`', props["gloss"])
        # 10.0: hints file-wide - the singleton rows left their Sections,
        # their sublines are still visible prose
        for fp in _field_props(SRC):
            if "hint" in fp:
                out += re.findall(r'"(?:[^"\\]|\\.)*"|`[^`]*`', fp["hint"])
    for m in re.finditer(r"<Foot>(.*?)</Foot>", SRC, re.S):
        out.append(m.group(1))
    for m in re.finditer(r"<LockKey[^/]*/>(.*?)</div>", SRC, re.S):
        out.append(m.group(1))
    return out


class SettingsCopy(unittest.TestCase):

    def test_total_visible_prose_is_under_150_words(self):
        # 10.0: singleton rows live OUTSIDE Sections now, so the total is
        # file-wide - every Section gloss plus every Field hint plus the
        # trust notes, wherever they sit. The words moved seat (gloss ->
        # subline), not out of the budget.
        gloss = sum(g for _, g, _, _ in _slots())
        hu, hc = _hints(SRC)
        total = gloss + hu + hc + _foot_words(SRC) + _note_words(SRC)
        self.assertLess(total, 150,
                        "visible prose crept back up to %d words" % total)

    def test_no_control_has_prose_above_and_below(self):
        offenders = [t for t, gloss, below, _ in _slots()
                     if gloss > 0 and below > 0]
        self.assertEqual(offenders, [],
                         "controls with prose on both sides: %s" % offenders)

    def test_every_visible_string_is_ten_words_or_less(self):
        long_ones = [(s[:60], _lit_words(s)) for s in _visible_strings()
                     if _lit_words(s) > 10]
        self.assertEqual(long_ones, [],
                         "visible strings over ten words: %s" % long_ones)

    def test_live_values_stay_visible_and_out_of_tips(self):
        # status, not help: the count of installed/found things and the
        # detected card are read at a glance, never hover-only
        visible = " ".join(_visible_strings())
        for marker in ["reads as", "Found", "compatible installed",
                       "installed",
                       # The clip scale itself, not the sentence around it.
                       # It used to be pinned as the literal "Doubled at",
                       # which both broke on a re-word and hid that the copy
                       # was wrong: the scale is settable from 1x to 4x, so
                       # "Doubled" was a lie at every value except 2.
                       "${upscale.video_scale}"]:
            self.assertIn(marker, visible, "live value %r went missing" % marker)
        tips = _tip_texts()
        self.assertTrue(tips and all(tips), "an InfoTip is missing its text")
        for tip in tips:
            self.assertNotIn("${", tip, "a live value is trapped in a tip")
            self.assertNotIn("installed", tip, "a count is trapped in a tip")

    def test_warnings_stay_visible_not_in_tips(self):
        visible = " ".join(_visible_strings())
        self.assertIn("Non-commercial license", visible)
        self.assertIn("Experimental", visible)
        for tip in _tip_texts():
            self.assertNotIn("Non-commercial license", tip)
            self.assertNotIn("Experimental", tip)

    def test_one_infotip_per_control(self):
        for props, block in _sections():
            self.assertLessEqual(props.get("title", "").count("<InfoTip"), 1,
                                 "two tips on one title")
            for fp in _field_props(block):
                self.assertLessEqual(fp.get("label", "").count("<InfoTip"), 1,
                                     "two tips on one field label")
                # 10.0: a row MAY pair a tip with its subline - the subline is the
                # one FACT, the tip is the RULE; the 9.17b XOR died with the
                # stacked layout the rule was written for

            self.assertNotIn("<InfoTip", props.get("gloss", ""),
                             "a tip is hiding inside the visible gloss")
    def test_edit_section_names_both_lanes(self):
        """9.29: the masked lane was invisible in Settings while the job card
        named Klein 9B. Both lanes get a named row in the one section. (The
        labels are JSX fragments since 9.52 hung the undistilled tip off
        them, so the name is matched inside the fragment.)"""
        for props, block in _sections():
            if "Edit model" in props.get("title", ""):
                labels = [fp.get("label") for fp in _field_props(block)]
                self.assertTrue(any(l and "Whole frame" in l for l in labels))
                self.assertTrue(any(l and "Masked area" in l for l in labels))
                break
        else:
            self.fail("the Edit model section is gone")

    def test_both_edit_pickers_warn_about_an_undistilled_build(self):
        """9.52: a Klein True pick in either lane runs ~20 steps, not the
        distill's 4 - the five-times-longer render has to explain itself
        where the pick is made."""
        for props, block in _sections():
            if "Edit model" in props.get("title", ""):
                labels = [fp.get("label", "") for fp in _field_props(block)]
                hits = [l for l in labels
                        if "An undistilled build runs ~20 steps" in l
                        and "five times longer" in l]
                self.assertEqual(len(hits), 2,
                                 "both edit pickers need the undistilled tip")
                break
        else:
            self.fail("the Edit model section is gone")

    def test_the_edit_tip_says_what_a_mask_does(self):
        """The fact nobody could discover tonight: a painted mask routes the
        edit to the masked lane; no mask runs the whole-frame lane."""
        self.assertTrue(
            any(tip and "painted mask routes the edit to the masked lane" in tip
                for tip in _tip_texts()),
            "the mask-routing fact is missing from the edit lane's tip")

    def test_the_edit_tip_names_what_each_whole_frame_family_is_for(self):
        """9.44: the whole-frame row now offers Klein next to Qwen, and the
        reason to pick one over the other lives in the tip."""
        self.assertTrue(
            any(tip and "Klein keeps skin texture" in tip
                for tip in _tip_texts()),
            "the Klein whole-frame fact is missing from the edit lane's tip")

    def test_the_whole_frame_picker_folders_both_edit_families(self):
        """The two families read as families, not one undifferentiated list:
        Qwen builds folder under familyName("qwen_edit"), Klein builds under
        familyName("klein") - the picker's existing grouping, no new control."""
        self.assertIn('familyName("qwen_edit")', SRC)
        self.assertIn('familyName("klein")', SRC)

    def test_tips_stay_keyboard_reachable(self):
        # the ported component carries the focus + label; this guards the port
        self.assertIn("tabIndex={0}", TIP_SRC)
        self.assertIn("aria-label={text}", TIP_SRC)
        self.assertGreater(len(_tip_texts()), 5, "the tips did not land")

    def test_settings_wire_is_frozen(self):
        # 9.17a's test: top-level keys of every apply({...}) payload = the
        # /api/settings write surface; this brief forbids changing it
        found = set(re.findall(r"\bapply\(\{\s*(\w+)", SRC))
        self.assertEqual(found, {
            "comfy_url", "comfy_editor", "comfy_console", "explicit",
            "vram_profile", "video", "critic", "vae", "edit", "upscale",
            "pid", "llm", "extra_model_roots",
            # 1.1.4b: the still finish joined the write surface.
            "still",
            # 9.91: the H3 model slots joined the write surface.
            "h3",
        })

    def test_help_settings_section_quotes_the_new_copy(self):
        # DESIGN.md §4: when a surface is restructured the manual's matching
        # section moves in the same pass, or it describes a ghost
        s6 = HELP.split("## 6. Settings reference")[1].split("## 7.")[0]
        s6 = re.sub(r"\s+", " ", s6)
        for quote in ["System follows Windows.",
                      "Another rig's address borrows its GPU",
                      "A full card is a slow render.",
                      "Sharper drop-in; can over-sharpen on one pass.",
                      "Model enlarges; PiD repaints.",
                      "Suggests fixes for what you made.",
                      "auto reads your words; never keeps subjects dressed.",
                      "The popup still decides per clip — this sets the default.",
                      "Only your provider sees the key",
                      "Runs entirely on this PC"]:
            self.assertIn(quote, s6, "HELP.md §6 lost the shipped copy: %r" % quote)
        self.assertNotIn("How the app looks", s6)
        self.assertNotIn("what happens local stays local", s6)


class CtaSentenceCase(unittest.TestCase):
    """9.45: every segment option label and every button in SettingsMenu is
    sentence case with a capital first letter - "Auto", "Allow", "Never",
    "Open the graph editor", "Rescan folders". Jesse, 2026-08-25, on the
    Appearance row reading right while the rest stayed lowercase: "looks
    weird being lowercase always in CTAs." The case lives in the strings,
    never in CSS (this suite reads the strings), so this walks the source:
    every label literal inside a SegmentedControl options array - quotes and
    template literals both, the VRAM row's `Auto${...}` is how the lowercase
    one hid from a plain grep - and every literal <Btn> text. A label may
    legitimately start caseless: a digit ("2×") or an interpolation
    ("${t} GB"); a dynamic text ({q.label}) has no literal to pin. So the
    assertion is that no CTA literal starts with a lowercase letter - the
    next lowercase CTA fails here instead of reaching Jesse. Field labels,
    GroupLabel headings, InfoTip prose and sublines are out of scope on
    purpose: nouns and prose, not CTAs."""

    @staticmethod
    def _segment_option_labels():
        for m in re.finditer(r"<SegmentedControl\s", SRC):
            props = _props(SRC[m.start():_tag_end(SRC, m.start())])
            if "options" not in props:
                continue
            for lm in re.finditer(r'label:\s*"((?:[^"\\]|\\.)*)"',
                                  props["options"]):
                yield lm.group(1)
            for lm in re.finditer(r"label:\s*`([^`]*)`", props["options"]):
                yield lm.group(1)

    @staticmethod
    def _button_texts():
        for m in re.finditer(r"<Btn\s", SRC):
            end = _tag_end(SRC, m.start())
            text = SRC[end:SRC.index("</Btn>", end)].strip()
            if text and not text.startswith("{"):
                yield " ".join(text.split())

    def test_every_cta_starts_with_a_capital(self):
        ctas = list(self._segment_option_labels()) + list(self._button_texts())
        self.assertGreater(len(ctas), 20, "the CTA sweep went blind")
        offenders = [s for s in ctas if s[0].islower()]
        self.assertEqual(offenders, [],
                         "CTA labels starting lowercase: %s" % offenders)


class CleanUpSection(unittest.TestCase):
    """9.46: Clean up gives memory back and says how much. Five actions in
    the pinned order, every toast naming the GB it actually freed; the
    brain's idle window is the one setting; everything sleeps while a
    render is in flight. The wording is Jesse's - these are pins, not
    suggestions."""

    @staticmethod
    def _block():
        for props, block in _sections():
            if "Clean up" in props.get("title", ""):
                return props, block
        raise AssertionError("the Clean up section is gone")

    def test_the_section_carries_its_tip_and_gloss(self):
        props, _ = self._block()
        self.assertIn("Nothing hands memory back until asked. "
                      "Each button says what it freed.", props["title"])
        # 10.0: the gloss moved into the tip - "A full card is a slow render."
        # states a rule, and a rule rides the tip, not the subline
        self.assertIn("A full card is a slow render.", props["title"])

    def test_the_five_actions_in_their_order(self):
        _, block = self._block()
        labels = []
        for m in re.finditer(r"<Btn\s", block):
            end = _tag_end(block, m.start())
            text = block[end:block.index("</Btn>", end)].strip()
            labels.append(" ".join(text.split()))
        self.assertEqual(labels, ["Free VRAM", "Free brain", "Free RAM",
                                  "Reset desktop", "Free all"])

    def test_every_action_reports_what_it_freed(self):
        # the single buttons name the resource; Free all toasts the total
        self.assertIn("`${label}: ${n} GB back`", SRC)
        self.assertIn("`${Math.round(total * 10) / 10} GB back`", SRC)
        # a declined UAC is the user's own choice and says exactly that
        self.assertIn('"Desktop reset cancelled"', SRC)

    def test_the_reset_desktop_tip_carries_the_warning(self):
        self.assertIn("Restarts Explorer and the Windows compositor, which "
                      "hoard video memory. One screen flash, Explorer "
                      "windows close, admin prompt; an idle ComfyUI may "
                      "restart.", SRC)

    def test_the_brain_idle_window_is_the_one_setting(self):
        _, block = self._block()
        self.assertIn("Brain idles after", block)
        for label in ['"5 min"', '"10 min"', '"30 min"', '"Never"']:
            self.assertIn("label: %s" % label, block)
        self.assertIn("apply({ llm: { local_idle_minutes: v } }", block)
        self.assertIn("A warmed brain holds ~8 GB. Idle, it unloads; the "
                      "next message wakes it in seconds.", block)

    def test_the_buttons_sleep_while_a_render_is_in_flight(self):
        _, block = self._block()
        self.assertIn("renderBusy", block)
        self.assertIn('"wait for the render"', block)
        self.assertIn("store.liveJobs", SRC)

    def test_the_frees_moved_out_of_compute(self):
        # Compute keeps the address, Restart, and the boot behaviour - the
        # flush buttons live in Clean up now.
        for props, block in _sections():
            if "Compute" in props.get("title", ""):
                self.assertNotIn("/api/comfy/free", block)
                self.assertNotIn("/api/llm/free", block)
                self.assertIn("/api/comfy/restart", block)
                return
        self.fail("the Compute section is gone")


class ModelsLibraryTab(unittest.TestCase):
    """9.30: the Models tab is the read-only library — what you own, what it
    runs, what it weighs. It sits after Video because it is browsed, not
    tuned; choosing per lane stays on the medium tabs. Pins: the tab's
    place, the summary's unprofiled-LoRA count, the three required tips, and
    the row contract (pretty name, raw path in the tooltip, human reasons,
    heavier-than-card as advisory)."""

    def test_the_tab_sits_after_video_before_brain(self):
        tabs = SRC[SRC.index("const TABS = ["):]
        tabs = tabs[:tabs.index("];")]
        ids = re.findall(r'\{ id: "(\w+)"', tabs)
        self.assertEqual(ids, ["general", "image", "video", "models",
                               "brain", "about"])

    def test_the_summary_line_counts_the_profileless(self):
        # 141 of 416 on the machine this shipped from — the single most
        # useful fact the app had never told anyone
        self.assertIn("have no profile", SRC)

    def test_the_three_required_tips_ship(self):
        tips = _tip_texts()
        self.assertTrue(any(t and "architecture, not a brand" in t
                            for t in tips), "the family tip is missing")
        self.assertTrue(any(t and "A profile is what Pixal knows" in t
                            for t in tips), "the profile tip is missing")
        self.assertTrue(any(t and "offloads to system memory" in t
                            and "never a block" in t for t in tips),
                        "the weight-vs-card tip is missing or reads as a block")

    def test_rows_hold_the_row_contract(self):
        self.assertIn("prettyModel(", SRC)        # never a raw filename
        self.assertIn("familyName(", SRC)         # family group headings
        self.assertIn("title={rel", SRC)          # raw relpath is the tooltip
        # the server reason, said in the user's language
        self.assertIn("a video model — used by the Animate lanes", SRC)
        # heavier than the card: the 9.29 advisory, never a block
        self.assertIn("it will offload and run slowly", SRC)
        # Civitai where the match is free (brief: thread the field, do it)
        self.assertIn("civitai_url", SRC)

    def test_the_server_publishes_what_the_rows_read(self):
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('meta["size"]', server)
        self.assertIn('meta["civitai_url"]', server)


class H3Upscale2xSection(unittest.TestCase):
    """9.31: the H3 2× default lives where the other clip upscalers do - its
    own Section in the Video tab's finishing group, immediately after the
    Upscaler Section. The InfoTip is required: it carries the two facts a
    user cannot discover - the pass runs INSIDE the render (it needs the
    render's own latent, so it can never be a button on a finished clip)
    and it costs roughly 3× the render time."""

    def test_the_section_sits_in_finishing_right_after_the_upscaler(self):
        video = SRC[SRC.index('{tab === "video" &&'):]
        fin = video.index("<GroupLabel>Finishing</GroupLabel>")
        upscaler = video.index('<Section title={<>Upscaler', fin)
        # 10.0: the 2x default is a ROW now, immediately after the section
        nxt = video.index("<Field ", video.index("</Section>", upscaler))
        # 2026-09-01: the factor renders as the little Chip, not label prose
        self.assertIn("H3 <Chip>2×</Chip> upscale", video[nxt:nxt + 300],
                      "the row right after Upscaler is not the H3 2× one")

    def test_the_infotip_names_both_undiscoverable_facts(self):
        tips = [t for t in _tip_texts() if t and "inside the render" in t]
        self.assertTrue(tips, "no tip says why 2× can never be a clip action")
        self.assertIn("finished clip", tips[0])
        self.assertIn("3×", tips[0])

    def test_the_row_disables_with_a_truthful_hint(self):
        self.assertIn("upscale_2x_available", SRC)
        self.assertIn("Needs the MMH3 Ultimate Upscale pack and 659 MB weights.",
                      SRC)


class H3ResolutionSection(unittest.TestCase):
    """9.55: the H3 resolution default sits next to the H3 2× Section in the
    Video tab's finishing group - the same shape, the same gloss contract
    ("the popup still decides per clip"), one fact per option title (the MP
    and the relative time), Lumen SegmentedControl only. It follows rather
    than precedes the 2× Section because 9.31 pinned Upscaler -> H3 2×
    adjacency above."""

    def test_the_section_sits_next_to_the_2x_one(self):
        video = SRC[SRC.index('{tab === "video" &&'):]
        two_x = video.index('label={<>H3 <Chip>2×</Chip> upscale')
        nxt = video.index("<Field ", two_x + 1)
        self.assertIn("H3 resolution", video[nxt:nxt + 300],
                      "the row right after H3 2× upscale is not the "
                      "H3 resolution one")

    def test_the_wire_key_is_h3_resolution(self):
        self.assertIn("apply({ video: { h3_resolution: id } }", SRC)
        self.assertIn('value={videoCfg.h3_resolution || "standard"}', SRC)

    def test_every_option_title_is_one_fact(self):
        # the MP and the relative time - no adjectives
        self.assertIn("`${r.mp} MP — the fast default.`", SRC)
        self.assertIn("~${Math.round(r.mp)}x the render time.", SRC)

    def test_the_gloss_is_the_per_clip_contract(self):
        section = SRC[SRC.index('label={<>H3 resolution'):]
        # 10.0: the gloss is the row's inline subline now, same words
        section = section[:section.index("</Field>")]
        self.assertIn("The popup still decides per clip — this sets the default.",
                      section)
        self.assertIn("<SegmentedControl", section)
        self.assertIn("<InfoTip", section)
        self.assertIn("detail comes from the model, not an upscaler", section)


if __name__ == "__main__":
    unittest.main()
