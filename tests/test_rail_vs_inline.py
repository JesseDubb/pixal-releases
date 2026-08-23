"""A panel renders in the rail or in flow - never both.

Chat.jsx keeps two presentations of the same controls: a reserved right-hand
rail at >=960px, and the identical components in flow when there is no room
for it. The LoRA chain was gated correctly from the start. `RecipeDials` - the
Advanced fold holding likeness, grounding and the bypass variant - was not
gated at all, so with a chain loaded at desktop width it drew in the rail AND
above the composer: two folds on screen, editing the same overrides, either
one able to contradict what the other displayed.

Found by Jesse in a screenshot, not by a test, because nothing asserted the
two presentations were exclusive. This does.

2026-08-22, brief 9.23a: RecipeDials is gone - the dials moved onto the
chain's own cards (see test_lora_card_controls.py), so the fold cannot draw
twice because there is no fold. LoraChain remains the only component with a
rail presentation and an in-flow one, and its cards inherit its gating.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "web" / "src" / "components" / "Chat.jsx").read_text(encoding="utf-8")

# Every component that has a rail presentation and an in-flow one. Was
# ["LoraChain", "RecipeDials"] until 9.23a deleted the fold outright.
DUAL = ["LoraChain"]


def _sites(name):
    """(rail_uses, inline_uses) for a component, by whether the opening tag
    carries the bare `rail` prop."""
    rail, inline = [], []
    for m in re.finditer(r"<%s(\s[^>]*?)?/?>" % name, SRC, re.S):
        (rail if re.search(r"\brail\b(?!=)", m.group(1) or "") else inline).append(m.start())
    return rail, inline


def _enclosing_expr(pos):
    """The innermost `{ ... }` JSX expression containing `pos`, as the text
    from its opening brace up to pos.

    A backwards window is NOT good enough here, and getting that wrong is how
    the first version of this test passed against the very bug it exists for:
    the LoraChain guard sits a few hundred characters above the RecipeDials
    use, so any fixed lookbehind finds a guard that had already closed.
    """
    depth = 0
    for i in range(pos - 1, -1, -1):
        c = src_at(i)
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return SRC[i:pos]
            depth -= 1
    return ""


def src_at(i):
    return SRC[i]


class RailVsInline(unittest.TestCase):

    def test_each_dual_panel_has_exactly_one_of_each(self):
        for name in DUAL:
            rail, inline = _sites(name)
            self.assertEqual(len(rail), 1, "%s: expected one rail use, got %d" % (name, len(rail)))
            self.assertEqual(len(inline), 1,
                             "%s: expected one in-flow use, got %d" % (name, len(inline)))

    def test_the_in_flow_copy_is_gated_on_the_rail_being_absent(self):
        """Without this the two are not exclusive - which is the whole bug.
        Either guard works: inlineLoraChain already carries !desktopLoraRail."""
        for name in DUAL:
            _, inline = _sites(name)
            self.assertTrue(inline, "%s has no in-flow use to guard" % name)
            guard = _enclosing_expr(inline[0])
            # ANCHORED. _enclosing_expr returns everything from the opening
            # brace, which includes any already-closed sibling conditional as
            # a substring - so an unanchored search finds LoraChain's guard
            # while standing inside an unguarded RecipeDials. That is the
            # second way this test managed to pass against its own bug.
            self.assertTrue(
                re.match(r"\{\s*(?:!desktopLoraRail|inlineLoraChain)\s*&&", guard),
                "%s renders in flow with no guard against the rail - it will "
                "draw twice at >=960px" % name)

    def test_the_rail_and_the_inline_guard_cannot_both_be_true(self):
        """inlineLoraChain is defined so it excludes the rail. If that ever
        stops being true, the guard above stops protecting anything."""
        m = re.search(r"const inlineLoraChain = ([^;]+);", SRC)
        self.assertIsNotNone(m, "inlineLoraChain is gone")
        self.assertIn("!desktopLoraRail", m.group(1),
                      "inlineLoraChain no longer excludes the rail")


if __name__ == "__main__":
    unittest.main()
