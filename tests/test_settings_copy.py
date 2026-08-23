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
        for fp in _field_props(block):
            if "hint" in fp:
                out += re.findall(r'"(?:[^"\\]|\\.)*"|`[^`]*`', fp["hint"])
        for m in re.finditer(r"<Foot>(.*?)</Foot>", block, re.S):
            out.append(m.group(1))
        for m in re.finditer(r"<LockKey[^/]*/>(.*?)</div>", block, re.S):
            out.append(m.group(1))
    return out


class SettingsCopy(unittest.TestCase):

    def test_total_visible_prose_is_under_150_words(self):
        total = sum(g + b + c for _, g, b, c in _slots())
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
                self.assertFalse("<InfoTip" in fp.get("label", "") and "hint" in fp,
                                 "a field has both a tip and a hint - pick one")
            self.assertNotIn("<InfoTip", props.get("gloss", ""),
                             "a tip is hiding inside the visible gloss")

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
        })

    def test_help_settings_section_quotes_the_new_copy(self):
        # DESIGN.md §4: when a surface is restructured the manual's matching
        # section moves in the same pass, or it describes a ghost
        s6 = HELP.split("## 6. Settings reference")[1].split("## 7.")[0]
        s6 = re.sub(r"\s+", " ", s6)
        for quote in ["System follows Windows.",
                      "Another rig's address borrows its GPU",
                      "Sharper drop-in; can over-sharpen on one pass.",
                      "Model enlarges; PiD repaints.",
                      "Suggests fixes for what you made.",
                      "auto reads your words; never keeps subjects dressed.",
                      "Only your provider sees the key",
                      "Runs entirely on this PC"]:
            self.assertIn(quote, s6, "HELP.md §6 lost the shipped copy: %r" % quote)
        self.assertNotIn("How the app looks", s6)
        self.assertNotIn("what happens local stays local", s6)


if __name__ == "__main__":
    unittest.main()
