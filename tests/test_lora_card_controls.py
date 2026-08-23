"""Recipe controls live on the card they act on (brief 9.23a).

The `identity_edit` dials - Likeness, Grounding and the bypass variant - used
to render in a standalone "Advanced" fold (`RecipeDials`) mounted twice in
Chat.jsx: under the rail's LoRA chain, or in flow above the composer. A
control floated free of the thing it acted on: the bypass variant chose which
LoRA file loads, yet lived two cards away from the bypass card in the chain.

9.23a moves every dial onto its card: the bypass variant onto the
`vector_bypass` core card (bound by the dial's `choices_from` naming the
stage's `slot`), and the recipe-level number dials onto a recipe card that
leads the chain's column. The rule from the brief: everything in the rail is
a card, every card expands to its own controls, a control never floats free,
and a card with no controls shows no expand affordance.

These tests are static in the style of test_rail_vs_inline.py - this repo has
no JS test runner, so the contracts below assert the structure of the source.
Each was proven RED against the tree that still had the standalone fold.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT = (ROOT / "web" / "src" / "components" / "Chat.jsx").read_text(encoding="utf-8")
COMPOSER = (ROOT / "web" / "src" / "components" / "Composer.jsx").read_text(encoding="utf-8")
STORE = (ROOT / "web" / "src" / "store.js").read_text(encoding="utf-8")
WEB_SRC = ROOT / "web" / "src"


def _lora_chain_mounts(src):
    """The attribute text of every <LoraChain ... /> mount in `src`.

    The mounts are JSX, so the attribute text itself contains `>` (every
    arrow function does, including the onDial wiring these tests assert).
    `[^>]*` therefore truncates a mount at its first `=>` and can never
    capture the props being checked; mounts end `/>`, so capture up to
    that instead."""
    return [m.group(1) or "" for m in re.finditer(r"<LoraChain\b([\s\S]*?)/>", src)]


class LoraCardControls(unittest.TestCase):

    def test_every_dial_stays_reachable_on_the_same_wire(self):
        """The wire is frozen: opts.dials[recipeId], written by
        store.setRecipeDial. The dials moved cards, not keys - LoraChain takes
        the onDial prop the deleted fold used to get, reads its overrides from
        the same map, and still renders both dial kinds (choice + number)."""
        self.assertRegex(COMPOSER, r"export const LoraChain = \(\{[^)]*onDial",
                         "LoraChain does not accept onDial - the dials have no home")
        mounts = _lora_chain_mounts(CHAT)
        self.assertEqual(len(mounts), 2, "Chat.jsx should mount LoraChain twice (rail + in flow)")
        for attrs in mounts:
            self.assertIn("onDial={(key, value) => store.setRecipeDial(key, value)}", attrs,
                          "a LoraChain mount is not wired to store.setRecipeDial")
        self.assertRegex(STORE, r"setRecipeDial\(key, value\) \{[\s\S]{0,800}?state\.opts\.dials",
                         "setRecipeDial no longer writes the opts.dials map")
        self.assertRegex(COMPOSER, r"\(\(opts\?\.dials \|\| \{\}\)\)\[recipeId\]",
                         "overrides are no longer read from opts.dials[recipeId]")
        self.assertRegex(COMPOSER, r'dial\.kind === "choice"',
                         "the choice-dial branch is gone - the bypass variant is unreachable")
        self.assertRegex(COMPOSER, r"onDial\(dial\.key,",
                         "no control reports back through onDial(dial.key, ...)")

    def test_the_standalone_advanced_fold_is_gone(self):
        """Gone, not merely unused: no RecipeDials identifier anywhere in
        web/src, and its 'Advanced' title with it. A dormant fold is a second
        surface waiting to contradict the cards."""
        for path in list(WEB_SRC.rglob("*.jsx")) + list(WEB_SRC.rglob("*.js")):
            self.assertNotIn("RecipeDials", path.read_text(encoding="utf-8"),
                             "RecipeDials survives in %s" % path.relative_to(ROOT))
        self.assertNotRegex(COMPOSER, r">\s*Advanced\s*<",
                            "the Advanced fold's title is still rendered")

    def test_a_card_with_no_controls_has_no_disclosure_affordance(self):
        """Never a chevron onto an empty drawer. Both expand affordances - the
        recipe card's and a chain card's - are gated on that card actually
        carrying dials, so a control-less card renders no disclosure at all."""
        self.assertRegex(COMPOSER, r"\{recipeCardDials\.length > 0 && \(",
                         "the recipe card's disclosure is not gated on having dials")
        self.assertRegex(COMPOSER, r"\{stageDials\.length > 0 && \(",
                         "a chain card's disclosure is not gated on having dials")

    def test_a_collapsed_card_states_its_override(self):
        """An override must never hide inside a collapsed card. Three parts,
        all per card now: the card opens itself while one of its dials is
        overridden, the bypass card's collapsed line swaps its vector count
        for the override in accent, and the resolved-values summary line that
        the fold carried survives on the recipe card."""
        self.assertRegex(COMPOSER,
                         r"openCards, setOpenCards\] = useState\(\(\) => \{[\s\S]{0,600}?"
                         r"dialOverridesMap\[dial\.key\] !== undefined",
                         "cards no longer open themselves while an override is set")
        self.assertRegex(COMPOSER,
                         r"stageDials\.some\(\(dial\) => isSet\(dial\.key\)\)[\s\S]{0,400}?"
                         r"var\(--accent\)",
                         "a collapsed bypass card does not state its override")
        self.assertIn("follows the recipe", COMPOSER,
                      "the collapsed resolved-values summary is gone")
        self.assertNotIn("RecipeDials", COMPOSER,
                         "the summary still lives on the deleted fold instead of a card")

    def test_recipe_dials_render_only_inside_the_chain(self):
        """The dials' only surface is the chain's cards - rail or in-flow
        explorer, never a standalone fold outside it. Chat.jsx mounts nothing
        but LoraChain, and every mount hands it the dial writer."""
        self.assertNotRegex(CHAT, r"RecipeDials",
                            "Chat.jsx still mounts the standalone fold")
        for attrs in _lora_chain_mounts(CHAT):
            self.assertIn("onDial", attrs,
                          "a LoraChain mount without onDial leaves the dials homeless")

    def test_the_recipe_card_leads_the_column(self):
        """The brief's recommendation, implemented: the recipe is the first
        card in the chain's column, carrying the recipe-level dials (Likeness,
        Grounding - sampler/encode settings no single LoRA owns) ahead of
        every LoRA card, and the stage binding is by the declaration's
        `choices_from` naming the slot."""
        self.assertIn("choices_from", COMPOSER,
                      "nothing binds a stage dial to its card's slot")
        self.assertIn("recipeCardDials.length > 0", COMPOSER)
        self.assertIn("{core.map(", COMPOSER)
        self.assertLess(COMPOSER.index("recipeCardDials.length > 0"),
                        COMPOSER.index("{core.map("),
                        "the recipe card does not lead the chain's column")

    def test_the_drawer_opens_below_the_card_that_owns_it(self):
        """Expanding a card must not shove the cards below it out from under
        the cursor mid-click: each drawer renders BELOW its own card's header
        (the chevron is earlier in the source than the drawer it opens), so
        the header - the thing under the cursor - never moves when it opens."""
        self.assertIn("toggleCard(stage.slot)", COMPOSER)
        self.assertIn("cardOpen && stageDials.length > 0", COMPOSER)
        self.assertLess(COMPOSER.index("toggleCard(stage.slot)"),
                        COMPOSER.index("cardOpen && stageDials.length > 0"),
                        "a stage card's drawer is not below its header")
        self.assertIn('toggleCard("recipe")', COMPOSER)
        # The leading brace anchors the drawer gate; the collapsed summary's
        # gate is the same text negated (`!openCards.recipe && ...`).
        self.assertIn("{openCards.recipe && recipeCardDials.length > 0", COMPOSER)
        self.assertLess(COMPOSER.index('toggleCard("recipe")'),
                        COMPOSER.index("{openCards.recipe && recipeCardDials.length > 0"),
                        "the recipe card's drawer is not below its header")

    def test_an_override_is_stated_even_with_the_chain_collapsed(self):
        """The fold used to survive the chain's own collapse to a glyph strip;
        moving the dials onto the cards must not regress that. With the chain
        collapsed, a set override still prints itself in accent under the
        glyphs."""
        self.assertRegex(COMPOSER, r"allDials\.some\(\(dial\) => isSet\(dial\.key\)\)",
                         "a collapsed chain no longer states a live override")

    def test_the_way_home_copy_travels_with_the_dials(self):
        """'Always a way home' stays visible: the sentence explaining that a
        dial back on the recipe's own number clears the override moves onto
        the recipe card with the dials, not into the graveyard with the fold."""
        # The source wraps the sentence across a string concatenation; the
        # needle is the clause one line of it always carries. The ordering
        # anchor is what proves it moved: on the old tree the sentence sat in
        # the fold, defined AFTER the chain's rows; on a card it precedes them.
        self.assertIn("dial back on the recipe's own number", COMPOSER,
                      "the way-home explanation did not travel to the recipe card")
        self.assertLess(COMPOSER.index("dial back on the recipe's own number"),
                        COMPOSER.index("{core.map("),
                        "the way-home copy still lives below the chain's rows, off the cards")


if __name__ == "__main__":
    unittest.main()
