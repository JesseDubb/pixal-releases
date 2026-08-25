"""Brief 9.19c — the add-LoRA popup stops explaining itself in paragraphs.

The popup carried a two-line paragraph ("Showing only Krea 2 LoRAs compatible
with the current model profile."), a redundant count line restating it ("107
Krea 2 LoRAs available"), a placeholder doing a label's job and clipping at
the rail's width ("filter compatible installed LoRAs…"), no search icon, and
LoRA names head-truncated at one line - which throws away the distinguishing
suffix community LoRAs carry at the END of their names. Jesse: "just doesnt
look professional."

The deal (DESIGN.md: no control carries a paragraph; state goes in a label):

  - the paragraph and the count line are GONE, not merely conditional -
    replaced by one line of state sitting with the filter control:
    "Krea 2 · 107" (family, then count; the 120-cap caveat folds into the
    same line as "120 of 300", never a second sentence)
  - at most 10 visible words in that state line
  - the search field carries a Phosphor MagnifyingGlass inside the field and
    its placeholder is exactly "Search"
  - a LoRA name clamps at TWO lines, allows mid-token breaks so the tail
    survives, and its full string rides the tile's `title`
  - the set of LoRAs rendered is unchanged: same profile match, same text
    predicate, same 120 cap, same tile mapping

Static source analysis in the style of test_settings_copy.py - this repo has
no JS test runner. A word is a whitespace token containing a letter or
digit; ${...} interpolations are live values and count as zero; a ternary
counts at its longest branch.

unittest.TestCase because `unittest discover` is this repo's runner and
CI's. RED proof: the five design tests fail against the pre-9.19c tree
(assertion messages name what is missing); the sixth is a preservation
guard, proven live by mutation - flipping the predicate to `True` makes it
fail - and it stayed green across the surgery, which is its job.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "Composer.jsx").read_text(encoding="utf-8")

WORD = re.compile(r"[A-Za-z0-9]")


def _block(src, start_marker, end_marker):
    """src[start_marker : end_marker], both found at or after the start."""
    i = src.index(start_marker)
    return src[i:src.index(end_marker, i)]


def _add_search():
    """The `addSearch` element (filter field + strength box + state line)."""
    return _block(SRC, "const addSearch = (", "const addControl = (")


def _filter_input():
    return _block(SRC, "const FilterInput = (", "lora thumbnails")


def _lora_tile():
    return _block(SRC, "const LoraTile = (", "attached-source icons")


def _name_span():
    """The <span> inside LoraTile whose children are the display name."""
    tile = _lora_tile()
    m = re.search(r">\s*\{lora\.title \|\| lora\.short \|\| lora\.name\}", tile)
    assert m, "LoraTile no longer renders lora.title || lora.short || lora.name"
    start = tile.rindex("<span", 0, m.start())
    return tile[start:tile.index("</span>", m.start())]


def _expr_chunks(s):
    """Top-level {...} JSX expressions in s (braces balanced, strings and
    template literals opaque - their ${…} interpolations are balanced in
    this codebase)."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "{":
            depth, j = 0, i
            while j < n:
                c = s[j]
                if c in "\"'":
                    q = c
                    j += 1
                    while j < n and s[j] != q:
                        j += 2 if s[j] == "\\" else 1
                elif c == "`":
                    j += 1
                    while j < n and s[j] != "`":
                        j += 1
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(s[i:j + 1])
            i = j + 1
        else:
            i += 1
    return out


def _strip_exprs(s):
    """s with every top-level {...} expression blanked out - what a reader
    sees as static text."""
    for chunk in _expr_chunks(s):
        s = s.replace(chunk, " ", 1)
    return s


def _lit_words(expr):
    """Words in the string/template literals of one expression. ${…} are live
    values (zero words); a ternary counts at its longest branch."""
    merged = re.sub(r'(["\'])\s*\+\s*\1', "", expr)
    lits = re.findall(r'"(?:[^"\\]|\\.)*"|`[^`]*`|\'(?:[^\'\\]|\\.)*\'', merged)
    counts = []
    for lit in lits:
        body = re.sub(r"\$\{[^}]*\}", " ", lit)
        counts.append(sum(1 for tok in body.split() if WORD.search(tok)))
    if not counts:
        return 0
    return max(counts) if "?" in expr else sum(counts)


def _state_line():
    """The state line is the filter chip on the popover's title row
    (2026-08-25): `{profileLabel} · …` to the chip's </button>."""
    i = SRC.index("{profileLabel} ·")
    return SRC[i:SRC.index("</button>", i)]


class LoraPickerCopy(unittest.TestCase):

    def test_the_two_prose_lines_are_gone(self):
        # Gone, not merely conditional: the strings appear nowhere in the
        # file, so no flag or branch can resurrect them.
        self.assertNotIn("Showing only", SRC,
                         "the compatibility paragraph is still in the popup")
        self.assertNotIn("compatible with the current model profile", SRC,
                         "the compatibility paragraph is still in the popup")
        self.assertNotIn("LoRA{installedTotal", SRC,
                         "the count line's pluralisation is still rendered")
        self.assertNotIn('" available"', SRC,
                         "the count line's trailing copy is still rendered")

    def test_state_line_is_compact_and_sits_with_the_filter(self):
        block = _add_search()
        self.assertIn("{profileLabel} ·", block,
                      "no `family · count` state line beside the filter control")
        jsx = _state_line()
        words = sum(_lit_words(e) for e in _expr_chunks(jsx))
        words += sum(1 for tok in _strip_exprs(jsx).split() if WORD.search(tok))
        self.assertLessEqual(words, 10,
                             "the state line carries %d words of prose" % words)
        # The 120-cap caveat survives, folded into the same line - a silent
        # truncation reads as "that is everything you have installed".
        self.assertIn("installed.length < installedTotal", jsx,
                      "the cap caveat no longer travels with the count")

    def test_search_field_has_icon_and_exact_placeholder(self):
        block = _add_search()
        self.assertIn('placeholder="Search"', block,
                      "the filter's placeholder is not exactly `Search`")
        self.assertNotIn("filter compatible installed LoRAs", SRC,
                         "the sentence-long placeholder survived")
        self.assertIn("icon={<MagnifyingGlass", block,
                      "no MagnifyingGlass rides inside the filter field")
        imports = re.search(r"import \{([\s\S]*?)\} from \"@phosphor-icons/react\"", SRC)
        self.assertIsNotNone(imports)
        self.assertIn("MagnifyingGlass", imports.group(1),
                      "MagnifyingGlass is referenced but never imported")
        field = _filter_input()
        self.assertIn("placeholder, icon })", field,
                      "FilterInput does not accept an icon")
        self.assertIn('position: "relative"', field,
                      "the icon is not pinned inside the field's box")
        self.assertIn('position: "absolute"', field,
                      "the icon is not pinned inside the field's box")

    def test_a_long_name_carries_its_full_string_in_title(self):
        span = _name_span()
        self.assertIn("title={lora.title || lora.short || lora.name}", span,
                      "the clipped name does not offer the full string on hover")

    def test_the_name_clamps_at_two_lines_not_one(self):
        span = _name_span()
        self.assertIn("WebkitLineClamp: 2", span,
                      "the name is not clamped to two lines")
        self.assertNotIn('whiteSpace: "nowrap"', span,
                         "the one-line head truncation survived")
        # The distinguishing suffix sits at the END of community names:
        # mid-token breaks let line two fill, so the tail survives longest.
        self.assertIn('overflowWrap: "anywhere"', span,
                      "long names cannot break mid-token, so the tail clips first")

    def test_the_rendered_set_is_unchanged(self):
        # The no-behaviour-change contract: same profile match, same text
        # predicate, same cap, same tile mapping - only the copy moved.
        flat = re.sub(r"\s+", " ", SRC)
        self.assertIn("!activeNames.has(lora.name) && !recipeNames.has(lora.name)", flat)
        self.assertIn("loraMatchesProfile(lora, profile)", flat)
        self.assertIn("(!filter || `${lora.title || \"\"} ${lora.short || \"\"} ${lora.name}`"
                      " .toLowerCase().includes(filter.toLowerCase()))", flat)
        self.assertIn("const installedTotal = installedAll.length;", flat)
        self.assertIn("const installed = installedAll.slice(0, 120);", flat)
        popup = _block(SRC, "const addControl = (", "</Pop>")
        self.assertIn("installed.map((lora)", popup,
                      "the popup no longer maps the filtered set")
        self.assertIn("<LoraTile", popup,
                      "the popup no longer renders the set as LoraTile")


if __name__ == "__main__":
    unittest.main()
