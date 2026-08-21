r"""Regression tests for the chat -> sampler path.

    .venv\Scripts\python.exe tests\test_chat_pipeline.py

No pytest: the project has no test dependency and the installer's engine is
stdlib-only, so the harness is too. Every case below is a real incident, not a
hypothetical - the fixture text is lifted from chat 629d1c68 and from the four
contaminated entries in history.jsonl.

The point of this file, in one line: a render must never be given a string the
user did not mean as a prompt.

Two entry points, one body: direct run prints its own pass/fail summary and
exits with it; unittest discovery runs the same checks once through
ChatPipelineTests. Importing the module runs nothing.
"""
import asyncio
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import server  # noqa: E402

PASS, FAIL = [], []


def check(name, got, want):
    (PASS if got == want else FAIL).append(name)
    if got != want:
        print(f"  FAIL {name}\n       got:  {got!r}\n       want: {want!r}")


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL {name} {detail}")


# The 717-character scene from turn [6] of chat 629d1c68. The brain answered it
# with the bare word "generate" and the card rendered that word.
TURN6 = (
    "The platinum blonde anime girl is seated cross-legged on the shoulder of her "
    "Japanese black mech, Onyx. She wears a crop top green t-shirt with a centered "
    "logo - no sleeves, no embellishment beyond that mark. Her hair falls in soft "
    "waves over one shoulder; she gazes forward with calm eyes, not looking at the "
    "camera. Onyx's black metallic frame curves beneath her like a throne and "
    "protector of her, its joints visible and sleek, designed for mobility and "
    "speed. She is positioned on his left shoulder. she looks like she is having "
    "the most fun of her life. Ultra modern anime style")

COMPOSER = ("\n\n[COMPOSER: writing for template=identity_edit. Model, loras, size "
            "and reference are applied server-side - never mention file names.]")


# ------------------------------------------------------- the full turn path --
def replay(user_text, convo, enhance=False):
    """Run one turn with the GPU and the brain replaced by capture stubs."""
    captured = {}

    async def fake_submit(cid, src, template, scene, spec, count=1, parent=None,
                          flags=None, verbatim=False):
        clean, fault = server.scene_gate(template, scene, verbatim=verbatim)
        captured.update(template=template, scene=clean, verbatim=verbatim, error=fault)
        return {"id": "test1234", "error": fault}

    async def fake_llm(messages, tools=None, cid=None):
        captured["tools"] = [t["function"]["name"] for t in (tools or [])]
        return 200, {"choices": [{"message": {"role": "assistant",
                                              "content": "generate"}}]}

    # broadcast is stubbed too, or a test run writes its chatter into the real
    # lane.json - the dev lane filled up with "Got it - rendering your prompt
    # exactly as written" from the suite before this was noticed.
    real = (server.HUB.submit, server.llm_call, server.HUB.broadcast)
    server.HUB.submit, server.llm_call = fake_submit, fake_llm
    server.HUB.broadcast = lambda **kw: captured.setdefault(
        "said", []).append(kw.get("text")) if kw.get("type") == "text" else None
    try:
        asyncio.run(server._kimi_reply(
            "testcid", {"role": "user", "content": user_text}, convo,
            {"prompt_enhance": enhance}))
    finally:
        server.HUB.submit, server.llm_call, server.HUB.broadcast = real
    return captured


def main():
    # ----------------------------------------------------------- scene_gate --
    print("scene_gate - the seed forms that used to leak")
    for form in ("Seed = 8979871423", "seed: 8979871423", "seed=8979871423",
                 "SEED = 8979871423."):
        clean, err = server.scene_gate("realism", f"A fox in snow. {form}")
        ok(f"strips {form!r}", err is None and "8979871423" not in clean, repr(clean))

    print("scene_gate - shapes that are not a prompt")
    for bad, why in (("generate", "a bare tool name"),
                     ("Show me", "an accept turn"),
                     ("show me!", "an accept turn with punctuation"),
                     ("go", "an affirmative"),
                     ('{"name": "generate", "arguments": {"scene": "a fox"}}',
                      "a printed tool call")):
        _, err = server.scene_gate("realism", bad)
        ok(f"refuses {why}", err is not None, f"accepted {bad!r}")

    # A composer block is CLEANED rather than refused - it rides on legitimate user
    # turns by design, so the scene around it is still what they meant. In verbatim
    # mode nothing is rewritten, so there it has to be refused instead.
    dirty = "A fox in snow. [COMPOSER: writing for template=realism.]"
    clean, err = server.scene_gate("realism", dirty)
    ok("composer block is stripped", err is None and "[COMPOSER" not in clean, repr(clean))
    _, err = server.scene_gate("realism", dirty, verbatim=True)
    ok("composer block is refused when verbatim", err is not None)

    print("scene_gate - things it must NOT touch")
    clean, err = server.scene_gate("realism", TURN6)
    ok("a real scene passes", err is None and clean == TURN6)
    clean, err = server.scene_gate("realism", "render a cyberpunk street at noon")
    ok("a render verb WITH a scene passes", err is None, repr(err))
    # qwen_edit takes an instruction, not a scene: "make her jacket red" is the
    # whole legitimate prompt there and the prose rules would destroy it.
    clean, err = server.scene_gate("qwen_edit", "make her jacket red")
    check("qwen_edit is exempt", (clean, err), ("make her jacket red", None))
    clean, err = server.scene_gate("h3_i2v", "she turns to camera. Seed = 42")
    ok("motion briefs are exempt", err is None and clean.endswith("Seed = 42"))

    print("scene_gate - verbatim leaves the user's words alone")
    typed = "A fox in snow. Rich saturated colour."   # the retired house caption
    clean, err = server.scene_gate("realism", typed, verbatim=True)
    check("verbatim does not rewrite", (clean, err), (typed, None))
    clean, _ = server.scene_gate("realism", typed)
    ok("non-verbatim still scrubs the caption", "saturated" not in clean, repr(clean))
    _, err = server.scene_gate("realism", "generate", verbatim=True)
    ok("verbatim still refuses a bare command", err is not None)


    # --------------------------------------------------- scene_is_command --
    # The line between "please render THIS" and "please render what I already
    # wrote". A three-word cap was tried first and refused "draw a cat".
    print("scene_is_command - accepts vs. short prompts")
    for text, want in (
            # short, but they name something to look at
            ("draw a cat", False), ("shoot a portrait", False),
            ("render a cyberpunk street", False), ("a fox in snow", False),
            ("make me a sandwich", False), ("show me a photo", False),
            ("create an image of a dog", False),
            ("show me the girl on the mech", False),
            # longer, but they only point back at something already written
            ("generate", True), ("show me", True), ("render it", True),
            ("render it now", True), ("show me please", True),
            ("show it to me", True), ("render that one", True),
            ("make it", True), ("go", True), ("go ahead", True),
            ("yes", True), ("", True)):
        ok(f"{text!r} command={want}", server.scene_is_command(text) is want)


    # ------------------------------------------------------ captured_prompt --
    print("captured_prompt - an accept turn reaches back for the real prompt")
    convo = [
        {"role": "user", "content": TURN6 + COMPOSER},
        {"role": "assistant", "content": "generate"},
        {"role": "user", "content": "generate" + COMPOSER},
    ]
    check("'generate' resolves to the scene", server.captured_prompt(convo, "generate"), TURN6)
    check("'show me' resolves to the scene", server.captured_prompt(convo, "show me"), TURN6)
    check("a real turn is used as-is", server.captured_prompt(convo, TURN6), TURN6)
    check("no prior prompt -> the turn itself",
          server.captured_prompt([], "generate"), "generate")

    # The composer block is appended to the user's turn by the server; it must never
    # come back out as part of the prompt.
    ok("composer block never rides along", "[COMPOSER" not in server.captured_prompt(convo, "go"))


    # A queue receipt is appended with role "user" so the brain can see a render
    # happened. captured_prompt walked back onto one and rendered a picture of the
    # words (2026-08-18, first live pass). Both the capture and the gate must refuse it.
    RECEIPT = "[SYSTEM: the server queued that prompt as job 8bbda870 (realism) - no reply needed.]"
    after_render = [
        {"role": "user", "content": TURN6 + COMPOSER},
        {"role": "user", "content": RECEIPT},
    ]
    check("an accept after a render skips the receipt",
          server.captured_prompt(after_render, "show me"), TURN6)
    _, err = server.scene_gate("realism", RECEIPT)
    ok("the gate refuses a queue receipt", err is not None)
    _, err = server.scene_gate("realism", RECEIPT, verbatim=True)
    ok("verbatim refuses it too", err is not None)


    # --------------------------------------------------- the full turn path --
    print("_kimi_reply - the 629d1c68 replay")

    # The exact transcript that shipped the word "generate" to the sampler.
    got = replay("generate" + COMPOSER,
                 [{"role": "user", "content": TURN6 + COMPOSER},
                  {"role": "assistant", "content": "generate"}])
    ok("the word 'generate' never reaches the sampler",
       got.get("scene") != "generate", repr(got.get("scene")))
    check("it renders the scene the user actually wrote", got.get("scene"), TURN6)
    ok("and it goes verbatim", got.get("verbatim") is True)
    ok("with no error", got.get("error") is None, repr(got.get("error")))

    # A fresh, fully-written prompt with enhancement off: straight through, no brain.
    got = replay(TURN6 + COMPOSER, [])
    check("a written prompt passes through untouched", got.get("scene"), TURN6)
    ok("the brain was never called", "tools" not in got)

    # Enhancement ON must still go to the brain rather than the bypass.
    got = replay(TURN6 + COMPOSER, [], enhance=True)
    ok("enhance ON still consults the brain", "tools" in got)

    # Iteration must NOT bypass - the change has to be merged into the prior scene.
    got = replay("make her jacket red" + COMPOSER,
                 [{"role": "user", "content": TURN6 + COMPOSER}])
    ok("iteration is not passed through as the whole prompt",
       got.get("scene") != "make her jacket red", repr(got.get("scene")))

    # The local lane must keep generate even on a turn scored as conversation.
    if server.load_config()["llm"]["base_url"].find("127.0.0.1") >= 0:
        got = replay("hey there", [], enhance=True)
        ok("local lane keeps generate on a chat turn",
           "generate" in got.get("tools", []), repr(got.get("tools")))
    else:
        print("  skip local-lane tool test (configured brain is not local)")


    # What the person actually sees. A bare tool name must never be one of them.
    got = replay("generate" + COMPOSER,
                 [{"role": "user", "content": TURN6 + COMPOSER},
                  {"role": "assistant", "content": "generate"}])
    said = got.get("said") or []
    ok("nothing shown to the user is a bare tool name",
       not any(server.scene_is_command(s or "") for s in said), repr(said))


    # ------------------------------------------------------------- verdict --
    print()
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed:", ", ".join(FAIL))
    return 1 if FAIL else 0


class ChatPipelineTests(unittest.TestCase):
    def test_chat_pipeline(self):
        self.assertEqual(main(), 0, f"chat pipeline checks failed: {FAIL}")


if __name__ == "__main__":
    sys.exit(main())
