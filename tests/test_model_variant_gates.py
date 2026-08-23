"""A finetune is still its base, and the gates have to know that.

`e001e95` split the Animate MODEL row into base checkpoints and finetunes OF a
base. A finetune's id is its own filename stem - `10eros_max_fl2va_skip_edges`,
not `fl2va` - so every gate written as `activeModel?.id === "fl2va"` silently
stopped firing the moment a finetune was selected.

There is no `family` field on a model entry to compare instead. The base is a
substring token in the id, and the rule is implemented TWICE: `modelBaseId` in
MotionDirector.jsx and `h3_model_variant` in server.py. These tests pin that
the UI resolves through its copy rather than re-deriving the answer inline, and
that the two copies still agree about the one case the server refuses outright.

Two bugs prompted this, both in MotionDirector.jsx:

  showVideoLoraChain  - the whole video LoRA chain vanished for any FL2VA
                        finetune, with no error, even though the server had
                        already attached a real `loras` array to that entry.
  bridgeEligible      - never checked the variant at all, so a REF2VA render
                        let you pick an end frame and then 400d on send:
                        "a REF2VA render has no end frame".
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "web" / "src" / "components" / "MotionDirector.jsx"
SERVER = ROOT / "server.py"

SRC = MD.read_text(encoding="utf-8")


def _line_of(needle):
    """1-indexed line number of the first line containing `needle`."""
    for i, line in enumerate(SRC.splitlines(), 1):
        if needle in line:
            return i
    return None


def _statement(name):
    """The WHOLE `const <name> = ...;` statement, not its first line.

    Written after the single-line version of these tests went red against a
    correct fix purely because the condition had grown past 80 columns. A test
    that fails on line wrapping is not testing what it says it tests."""
    start = SRC.index("const %s =" % name)
    end = SRC.index(";", start)
    return " ".join(SRC[start:end].split())


class GatesResolveTheBase(unittest.TestCase):

    def test_the_base_resolver_exists(self):
        """Guards every test below from passing vacuously if it is renamed."""
        self.assertIn("const modelBaseId = (id) =>", SRC)

    def test_no_gate_compares_a_model_id_to_a_base_literal(self):
        """The defect class, stated directly. `id === "fl2va"` is only ever
        true for the stock build, so it is never true for a finetune OF it."""
        bad = re.findall(r'\.id\s*===\s*"(fl2va|ref2va)"', SRC)
        self.assertEqual(bad, [], "a model id is being compared to a base "
                                  "literal; resolve through modelBaseId")

    def test_the_lora_chain_gate_resolves_the_base(self):
        self.assertIn("modelBaseId", _statement("showVideoLoraChain"),
                      "showVideoLoraChain must ask what BASE the active model "
                      "is, not whether it IS the base")

    def test_the_bridge_gate_knows_about_the_variant(self):
        self.assertIn("modelBaseId", _statement("bridgeEligible"),
                      "bridgeEligible never checked the variant, so a REF2VA "
                      "render could arm an end frame the server refuses")


class TheBridgeGateMirrorsTheServer(unittest.TestCase):
    """Two implementations of one rule. If they drift, the UI offers something
    the server rejects - which is exactly the bug."""

    def test_the_server_refuses_ref2va_bridging(self):
        """The other half of the contract. If this ever stops being true, the
        UI rule below is over-strict and this test says so."""
        src = SERVER.read_text(encoding="utf-8")
        self.assertIn("bridging is FL2VA-only", src,
                      "the server's REF2VA bridge refusal moved or changed; "
                      "re-check what the UI should mirror")

    def test_the_ui_excludes_exactly_ref2va(self):
        """Mirror the server, do not out-guess it: the server refuses ref2va
        specifically, and allows a variant it cannot name. Requiring fl2va
        here would block a tokenless H3 finetune the server would have run."""
        self.assertIn('!== "ref2va"', _statement("bridgeEligible"),
                      "the UI should exclude ref2va, matching the server's own "
                      "refusal - not require fl2va, which is stricter")


class DeclaredBeforeUse(unittest.TestCase):
    """`const` has a temporal dead zone. `bridgeEligible` sat 17 lines ABOVE
    `activeModel`, so the obvious one-word fix throws at module scope - and it
    throws on render, not at build, so a bundle ships fine and the dialog is
    blank."""

    def test_bridge_eligible_is_declared_after_the_model_it_reads(self):
        model = _line_of("const activeModel =")
        bridge = _line_of("const bridgeEligible =")
        self.assertIsNotNone(model, "activeModel declaration not found")
        self.assertIsNotNone(bridge, "bridgeEligible declaration not found")
        self.assertGreater(bridge, model,
                           "bridgeEligible reads activeModel before it exists")


if __name__ == "__main__":
    unittest.main()
