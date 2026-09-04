"""Brief 9.69 - the Picker's popover escapes its clipping card.

The composer's tuning card folds through AccordionPanel, whose inner box is
``overflow: hidden`` and must stay that way (it clips for the grid-rows
fold). An in-tree ``position: absolute`` listbox was therefore cut at the
card's foot - Jesse's Scheduler Picker showed only its find box
(screenshot, 2026-08-27 22:36). The listbox now portals to document.body,
positions from the trigger's ``getBoundingClientRect()``, and flips above
the trigger when the room below runs short.

Source-level assertions in the test_disclosure_motion.py style: this repo
has no JS runner, the JSX is the contract, and a pattern that stops
matching IS the regression report.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICKER = (ROOT / "web" / "src" / "lib" / "Picker.jsx").read_text(encoding="utf-8")


class PortalEscape(unittest.TestCase):
    """The listbox leaves every clipping ancestor: createPortal to
    document.body, geometry from the trigger's rect - never an in-tree
    absolute box again."""

    def test_listbox_portals_to_document_body(self):
        self.assertIn('from "react-dom"', PICKER)
        self.assertIn("createPortal(", PICKER)
        self.assertIn("document.body", PICKER)

    def test_no_in_tree_absolute_popover_survives(self):
        self.assertNotIn('top: "calc(100% + 6px)"', PICKER)

    def test_position_comes_from_the_trigger_rect(self):
        self.assertIn("getBoundingClientRect()", PICKER)
        # left/width are the trigger's: the caller's layout must not change.
        # 10.0's hug mode (the settings value pill) right-aligns instead,
        # floored at 240 so the list never opens comically narrow.
        self.assertIn("hug ? r.right - w : r.left", PICKER)
        self.assertIn("Math.min(window.innerWidth - 24", PICKER)
        self.assertIn("Math.max(r.width, 340)", PICKER)
        self.assertIn("window.innerWidth - w - 12", PICKER)
        self.assertRegex(PICKER, r"top:\s*up \? null : r\.bottom \+ GAP")

    def test_the_flip_is_gated_on_room_below_and_above(self):
        # Named in the source, and never a blind flip: the room below must
        # run short of the popover's max AND the room above must be larger.
        self.assertIn("flip", PICKER.lower())
        self.assertRegex(PICKER, r"below < POP_MAX && above > below")
        self.assertRegex(PICKER, r'pop\.up \? "bottom center" : "top center"')


class FollowAndDismiss(unittest.TestCase):
    """Portal mechanics: the box follows the trigger and still dismisses
    exactly when it should."""

    def test_repositions_on_resize_and_any_ancestors_scroll(self):
        self.assertIn('window.addEventListener("resize", follow)', PICKER)
        # Capture phase: a bubbling listener never sees a scroll container's
        # own scroll, and the rail plus the chain's px-scroll both are one.
        self.assertIn('window.addEventListener("scroll", follow, true)', PICKER)
        self.assertIn("requestAnimationFrame(place)", PICKER)

    def test_away_click_accepts_trigger_and_portal(self):
        # The portal is outside boxRef's subtree: contains() on the trigger
        # alone would read every option click as away and close on choice.
        self.assertRegex(
            PICKER,
            r"boxRef\.current\?\.contains\(e\.target\) \|\| "
            r"popRef\.current\?\.contains\(e\.target\)")

    def test_escape_handler_rides_the_popover_root(self):
        # Key events fire inside the portal now; the handler must be on the
        # listbox node itself, not only on the trigger's wrapper.
        self.assertRegex(
            PICKER,
            r'ref=\{popRef\} onKeyDown=\{navigate\}')
        self.assertIn("onEsc(e);", PICKER)
        self.assertIn('window.addEventListener("keydown", escape, true)', PICKER)
        self.assertIn('e.key === "Escape"', PICKER)


class LookAndStack(unittest.TestCase):
    """What must not change while the box moves: its animation class, its
    theme, and a z-index above the composer's own popups."""

    def test_keeps_the_open_animation_and_gains_the_theme_scope(self):
        # px-root: applyThemeCss scopes every var to that class and body
        # sits outside it (InfoTip's body-plus-px-root pair).
        self.assertIn('className="px-root px-picker px-ov-pop"', PICKER)

    def test_sits_at_the_dropdown_tier_above_the_composer_popups(self):
        # The composer's model/LoRA popups run zIndex 25 (docked) / 45
        # (rail); a portaled popover stacks globally, where the tokens put
        # popovers and menus at Z.dropdown (100).
        self.assertIn("zIndex: Z.dropdown", PICKER)


if __name__ == "__main__":
    unittest.main()
