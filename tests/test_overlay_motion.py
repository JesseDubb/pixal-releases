"""Popovers and modals stop appearing out of nothing (brief 9.23d).

Eleven overlays in six files mounted bare: ``{open && (…)}`` — the panel
existed or it did not, with no in-between. This pins the fix:

- one shared overlay entrance, promoted from the ``px-compat-in`` shape
  (opacity + a small transform on ``MOTION.layout`` — the position token
  DESIGN.md §7 assigns to overlays), now living in
  ``web/src/lib/ModalShell.jsx`` as ``OVERLAY_CSS``;
- one shared ``ModalShell`` (scrim + centred box + entrance) replacing the
  five byte-identical fixed-centred modal copies;
- the reduced-motion guard inside the shared CSS, so a consumer cannot
  forget it;
- ``InfoTip``'s portalled tooltip keeping ``className="px-root"`` — the
  theme tokens resolve against that class and the brief forbids disturbing
  it.

These are source-level assertions, the same way test_disclosure_motion.py
pins the fold: the JSX is the contract, and a regex that stops matching IS
the regression report. The behaviour tests (entrances, shell usage) were
proven RED against the pre-fix tree. The guard tests (px-root survives,
opacity/transform only, dismissal unchanged) pass on both trees by design —
their teeth were proven by mutation, the way test_composer_canvas.py does.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"
SHELL = SRC / "lib" / "ModalShell.jsx"

# The brief's modal table: the five files whose fixed-centred box becomes
# the shared shell. SettingsMenu's panel is the fifth — its non-docked modes
# are the same scrim-plus-fixed-card pattern in phone/fallback positions.
MODAL_FILES = (
    "MotionDirector.jsx",
    "CharacterForm.jsx",
    "StyleForm.jsx",
    "EditDirector.jsx",
    "SettingsMenu.jsx",
)

# Files that carried a literal translate(-50%,-50%) box before the shell.
CENTRED_FILES = (
    "MotionDirector.jsx",
    "CharacterForm.jsx",
    "StyleForm.jsx",
    "EditDirector.jsx",
)


def _src(name):
    return (SRC / "components" / name).read_text(encoding="utf-8")


def _shell():
    return SHELL.read_text(encoding="utf-8")


def _block(src, start, end):
    """The slice of src between two markers — one component's source."""
    i = src.index(start)
    j = src.index(end, i + len(start))
    return src[i:j]


class SharedEntranceExists(unittest.TestCase):
    """``OVERLAY_CSS`` in web/src/lib/ModalShell.jsx is the one overlay
    entrance: opacity and a small transform on a MOTION token, with the
    reduced-motion guard baked in so no consumer can forget it."""

    def test_shell_module_exists(self):
        self.assertTrue(SHELL.is_file(),
                        "web/src/lib/ModalShell.jsx does not exist")

    def test_the_three_entrances(self):
        css = _shell()
        self.assertIn("@keyframes px-overlay-in", css,
                      "the popover entrance is gone")
        self.assertIn("@keyframes px-modal-in", css,
                      "the centred-modal entrance is gone")
        self.assertIn("@keyframes px-scrim-in", css,
                      "the scrim fade is gone")

    def test_entrances_are_opacity_and_transform_only(self):
        """An overlay fades and moves; it never grows. Height animation is
        the fold's technique (Disclosure) and has no business on an
        overlay."""
        css = _shell()
        self.assertIsNone(re.search(r"grid-template-rows", css),
                          "an overlay animates grid rows — that is a fold")
        self.assertIsNone(re.search(r"\bheight\b", css),
                          "an overlay animates height — overlays fade and move")

    def test_every_duration_is_a_motion_token(self):
        """Never a literal ms: the ladder is the whole rule (DESIGN.md §7)."""
        css = _shell()
        self.assertIsNone(re.search(r"\d+\s*ms", css),
                          "a literal millisecond duration in the overlay motion")
        self.assertIn("${MOTION.layout}", css,
                      "the entrance no longer runs on the layout token")

    def test_reduced_motion_drops_the_animation_never_the_state(self):
        css = _shell()
        m = re.search(r"@media \(prefers-reduced-motion: reduce\)(.*?)\}",
                      css, re.S)
        self.assertIsNotNone(m, "the reduced-motion guard is gone")
        self.assertIn("animation: none !important", m.group(1),
                      "reduced motion must drop the entrance outright")


class PopoversRenderTheSharedEntrance(unittest.TestCase):
    """Every popover in the brief's table mounts with the shared entrance
    class — no bare panel appears out of nothing."""

    def test_history_hover_caption(self):
        """The most-seen motion in the app: every hover of every tile."""
        src = _src("HistoryGrid.jsx")
        i = src.index("{hov && (")
        self.assertIn('className="px-ov-pop"', src[i:i + 400],
                      "the tile hover caption still appears out of nothing")

    def test_history_hover_action_rail(self):
        src = _src("HistoryGrid.jsx")
        self.assertIn('className="px-rail px-ov-pop"', src,
                      "the tile action rail still appears out of nothing")

    def test_add_lora_search_popover(self):
        block = _block(_src("MotionDirector.jsx"),
                       "const AddLora", "model grouping")
        self.assertIn("px-ov-pop", block,
                      "the add-LoRA popover still appears out of nothing")

    def test_model_picker_dropdown(self):
        # The model picker is the shared lib Picker since 2026-08-26.
        block = (SRC / "lib" / "Picker.jsx").read_text(encoding="utf-8")
        self.assertIn("px-ov-pop", block,
                      "the model picker dropdown still appears out of nothing")

    def test_scroll_picker_dropdown(self):
        block = _block(_src("SettingsMenu.jsx"),
                       "const ScrollPicker", "// One edit-lane option")
        self.assertIn("<Picker hug", block)
        shared = (SRC / "lib/Picker.jsx").read_text(encoding="utf-8")
        self.assertIn("px-ov-pop", shared,
                      "the shared dropdown lost its entrance")

    def test_info_tip_tooltip(self):
        src = _src("InfoTip.jsx")
        self.assertIn("px-ov-pop", src,
                      "the InfoTip tooltip still appears out of nothing")

    def test_popovers_inherit_duration_from_the_shared_class(self):
        """No site types its own animation duration: the class in
        OVERLAY_CSS carries the token, the site carries only the class."""
        for name, start, end in (
            ("MotionDirector.jsx", "const AddLora", "model grouping"),
            ("MotionDirector.jsx", "const ModelPicker", "const ENGINE_ICONS"),
            ("SettingsMenu.jsx", "const ScrollPicker", "// One edit-lane option"),
        ):
            with self.subTest(popover=start):
                block = _block(_src(name), start, end)
                self.assertNotRegex(block, r"animation:\s*`[^`]*\d+\s*ms",
                                    "a popover typed its own millisecond duration")


class ModalsUseTheSharedShell(unittest.TestCase):
    """Five files, one shell: scrim, centred box, entrance on MOTION.layout.
    Contents, sizes and dismissal stay exactly where each modal put them."""

    def test_every_modal_file_imports_and_renders_the_shell(self):
        for name in MODAL_FILES:
            with self.subTest(modal=name):
                src = _src(name)
                self.assertIn('../lib/ModalShell.jsx', src,
                              f"{name} does not import the shared ModalShell")
                self.assertRegex(src, r"<ModalShell[\s>]",
                                 f"{name} never renders <ModalShell>")

    def test_character_form_migrates_both_of_its_dialogs(self):
        """The crop dialog sits on top of the anchor form — two copies of
        the pattern in one file, both go through the shell."""
        src = _src("CharacterForm.jsx")
        self.assertGreaterEqual(src.count("<ModalShell"), 2,
                                "CharacterForm still hand-rolls one of its two dialogs")

    def test_no_hand_centred_box_is_left_behind(self):
        """The literal centring transform was the pattern's fingerprint; it
        belongs to the shell now, nowhere else."""
        for name in CENTRED_FILES:
            with self.subTest(modal=name):
                self.assertNotIn('translate(-50%,-50%)', _src(name),
                                 f"{name} still centres a modal box by hand")

    def test_the_shell_owns_scrim_and_dismissal_unchanged(self):
        """Scrim-click closes, exactly as each modal did it today — and the
        shell adds no Escape handler of its own: MotionDirector's window
        listener stays the only keyboard dismissal there is."""
        shell = _shell()
        self.assertRegex(shell, r"onClick=\{onClose\}",
                         "the scrim no longer closes on click")
        self.assertNotIn("keydown", shell,
                         "the shell grew an Escape handler — dismissal changed")
        self.assertNotIn("addEventListener", shell,
                         "the shell grew a listener — dismissal changed")


class InfoTipKeepsItsTheme(unittest.TestCase):
    """The tooltip portals to document.body, outside .px-root, so it carries
    the class to resolve theme tokens at all (1d61794). Any entrance wrapper
    must keep it on the themed element. Passes on the old tree too — proven
    by mutation, not claimed red."""

    def test_px_root_survives_on_the_portalled_tip(self):
        src = _src("InfoTip.jsx")
        i = src.index("createPortal(")
        self.assertIn('className="px-root', src[i:i + 700],
                      "the portalled tip lost px-root — it will draw unthemed")


if __name__ == "__main__":
    unittest.main()
