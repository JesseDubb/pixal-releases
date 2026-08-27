"""9.64 - deterministic scene repair at the gate.

The 2026-08-27 A/B rounds (briefs/ref/) measured three brain-written scene
failures no prompt rule stops: negation clauses a T2I encoder reads as a
summons ("no crowd" draws the crowd), tool arguments echoed inline
("standing = true"), and meta-rule echoes - the writer narrating its
rulebook or the mood ("This moment captures not just action, but
connection"). repair_scene() fixes them deterministically inside scene_gate
on the brain-written path only; verbatim (prompt enhance OFF) is never
rewritten, nsfw skips the negation pass ("no underwear" is a positive
instruction), and a repair that would gut more than half the scene's words
is refused.

Every fixture below is a quoted instance from briefs/ref/ab_prompts_1.md,
ab_prompts_2.md or fresh_prompts.md; the clean scene is Kimi's rooftop
worked example from briefs/ref/kimi_findings.md (9.63).
"""
import asyncio
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

_SPEC = spec_from_file_location(
    "pixal_server_scene_repair_tests", Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


# --- The six B scenes (ab_prompts_1.md / ab_prompts_2.md, pixal writer) ----

ROOFTOP_B = ("Zara, platinum blonde hair cascading over her shoulders in soft "
             "waves, leans against a sleek metal railing at a rooftop party "
             "during golden hour. She wears a black Louis Vuitton full-body "
             "suit — matte, form-fitting, no seams visible — its surface "
             "catching the warm amber light as it falls across her hourglass "
             "figure. Her brown eyes sparkle with laughter as she looks toward "
             "someone off-camera, lips parted mid-smile, teeth slightly "
             "exposed. A cocktail glass in her right hand glints under the "
             "ambient glow while a gold chain rests low on her neck. The "
             "background is a blur of soft indigo and peach tones — no "
             "buildings, no crowd, just sky and haze fading into dusk. All "
             "light comes from above-right, casting gentle rim highlights "
             "along her hair and suit’s edges.")
ROOFTOP_B_FIXED = ("Zara, platinum blonde hair cascading over her shoulders "
                   "in soft waves, leans against a sleek metal railing at a "
                   "rooftop party during golden hour. She wears a black Louis "
                   "Vuitton full-body suit — matte, form-fitting — its "
                   "surface catching the warm amber light as it falls across "
                   "her hourglass figure. Her brown eyes sparkle with "
                   "laughter as she looks toward someone off-camera, lips "
                   "parted mid-smile, teeth slightly exposed. A cocktail "
                   "glass in her right hand glints under the ambient glow "
                   "while a gold chain rests low on her neck. The background "
                   "is a blur of soft indigo and peach tones — just sky and "
                   "haze fading into dusk. All light comes from above-right, "
                   "casting gentle rim highlights along her hair and suit’s "
                   "edges.")

LAUNDROMAT_B = ("Zara, platinum blonde hair falling in loose waves around her "
                "shoulders, sits atop a stainless steel washing machine at a "
                "laundromat at night. She wears a black Louis Vuitton "
                "full-body suit — matte, form-fitting, no seams visible — its "
                "surface catching the dim overhead light as it hugs her "
                "hourglass figure. Her brown eyes are wide and focused "
                "forward—no makeup, no contouring, just natural skin tone and "
                "unedited features. In her right hand, she holds a plastic cup "
                "of instant noodles; steam curls faintly upward from the "
                "bowl. The background is dark gray concrete walls and a "
                "single flickering fluorescent light above — no other "
                "objects, no crowd, no night sky. All light comes from "
                "directly above, casting soft highlights on her hair’s edges "
                "while keeping the rest of the frame flat and minimalist.")
LAUNDROMAT_B_FIXED = ("Zara, platinum blonde hair falling in loose waves "
                      "around her shoulders, sits atop a stainless steel "
                      "washing machine at a laundromat at night. She wears a "
                      "black Louis Vuitton full-body suit — matte, "
                      "form-fitting — its surface catching the dim overhead "
                      "light as it hugs her hourglass figure. Her brown eyes "
                      "are wide and focused forward—just natural skin tone "
                      "and unedited features. In her right hand, she holds a "
                      "plastic cup of instant noodles; steam curls faintly "
                      "upward from the bowl. The background is dark gray "
                      "concrete walls and a single flickering fluorescent "
                      "light above. All light comes from directly above, "
                      "casting soft highlights on her hair’s edges while "
                      "keeping the rest of the frame flat and minimalist.")

MARKET_B = ("Zara walks her bike through a farmers market on a Sunday "
            "morning, holding a paper bag of peaches. She wears a black Louis "
            "Vuitton full-body suit — matte, form-fitting, no seams visible — "
            "its surface catching the soft dawn light as it hugs her "
            "hourglass figure. Her platinum blonde hair falls in loose waves "
            "around her shoulders; brown eyes are wide and focused forward—no "
            "makeup, no contouring, just natural skin tone and unedited "
            "features. The bike’s handlebars are slightly tilted upward as "
            "she grips them with both hands, the paper bag slung over one "
            "arm. Behind her, rows of wooden stalls stretch into a blur of "
            "muted greens and browns under diffused morning light — no "
            "people, no signs, no sky visible. All light comes from "
            "above-left, casting gentle highlights along the suit’s surface "
            "while keeping the rest of the frame flat and minimalist.")
MARKET_B_FIXED = ("Zara walks her bike through a farmers market on a Sunday "
                  "morning, holding a paper bag of peaches. She wears a black "
                  "Louis Vuitton full-body suit — matte, form-fitting — its "
                  "surface catching the soft dawn light as it hugs her "
                  "hourglass figure. Her platinum blonde hair falls in loose "
                  "waves around her shoulders; brown eyes are wide and "
                  "focused forward—just natural skin tone and unedited "
                  "features. The bike’s handlebars are slightly tilted upward "
                  "as she grips them with both hands, the paper bag slung "
                  "over one arm. Behind her, rows of wooden stalls stretch "
                  "into a blur of muted greens and browns under diffused "
                  "morning light. All light comes from above-left, casting "
                  "gentle highlights along the suit’s surface while keeping "
                  "the rest of the frame flat and minimalist.")

DINER_B = ("Zara, platinum blonde hair falling in loose waves around her "
           "shoulders, sits at a diner booth at 2am. She wears a black Louis "
           "Vuitton full-body suit — matte, form-fitting, no seams visible — "
           "its surface catching the dim ambient glow as it hugs her "
           "hourglass figure. Her brown eyes are focused forward—no makeup, "
           "no contouring, just natural skin tone and unedited features. "
           "Hooded up over her shoulders, she leans slightly forward with one "
           "hand on the table, fingers poised over a phone in her lap. Behind "
           "her, a neon sign reads “OPEN” in bold red letters — glowing "
           "faintly against the dark windowpane. The booth’s wooden surface "
           "reflects soft overhead light while keeping the rest of the frame "
           "flat and minimalist. All lighting comes from above-left, casting "
           "gentle highlights along her hair’s edges while keeping the rest "
           "of the frame shadowed.")
DINER_B_FIXED = ("Zara, platinum blonde hair falling in loose waves around "
                 "her shoulders, sits at a diner booth at 2am. She wears a "
                 "black Louis Vuitton full-body suit — matte, form-fitting — "
                 "its surface catching the dim ambient glow as it hugs her "
                 "hourglass figure. Her brown eyes are focused forward—just "
                 "natural skin tone and unedited features. Hooded up over her "
                 "shoulders, she leans slightly forward with one hand on the "
                 "table, fingers poised over a phone in her lap. Behind her, "
                 "a neon sign reads “OPEN” in bold red letters — glowing "
                 "faintly against the dark windowpane. The booth’s wooden "
                 "surface reflects soft overhead light while keeping the rest "
                 "of the frame flat and minimalist. All lighting comes from "
                 "above-left, casting gentle highlights along her hair’s "
                 "edges while keeping the rest of the frame shadowed.")

FISHERMAN_B = ("An old fisherman, weathered hands gripping a frayed fishing "
               "net, stands at the edge of a wooden dock as dawn breaks over "
               "still water. Fog curls low across the surface like a silent "
               "blanket, muted by soft gray-blue tones and barely piercing "
               "through mist-shrouded ripples. His tattered blue wool coat "
               "flaps slightly in the early breeze; his face is etched with "
               "lines from years at sea — no hat, no glasses, just weathered "
               "skin and quiet focus. He holds the net taut between both "
               "hands, fingers looping over knots as if stitching memory "
               "into fabric. The dock’s planks creak underfoot, worn smooth "
               "by tide and time. No boats, no birds, no sky visible beyond "
               "the mist — only water, wood, and his steady presence. All "
               "light comes from above-left, casting faint gold highlights "
               "across his hands and net while keeping the rest of the frame "
               "in soft shadow.")
FISHERMAN_B_FIXED = ("An old fisherman, weathered hands gripping a frayed "
                     "fishing net, stands at the edge of a wooden dock as "
                     "dawn breaks over still water. Fog curls low across the "
                     "surface like a silent blanket, muted by soft gray-blue "
                     "tones and barely piercing through mist-shrouded "
                     "ripples. His tattered blue wool coat flaps slightly in "
                     "the early breeze; his face is etched with lines from "
                     "years at sea — just weathered skin and quiet focus. He "
                     "holds the net taut between both hands, fingers looping "
                     "over knots as if stitching memory into fabric. The "
                     "dock’s planks creak underfoot, worn smooth by tide and "
                     "time. Only water, wood, and his steady presence. All "
                     "light comes from above-left, casting faint gold "
                     "highlights across his hands and net while keeping the "
                     "rest of the frame in soft shadow.")

BARISTA_B = ("A barista, barefoot and wearing a white apron over dark pants, "
             "stands behind a tiny Tokyo coffee stand as rain taps softly "
             "against the glass window. She pours milk into a black espresso "
             "cup with precise, swirling motions — her hands steady, eyes "
             "locked on the surface. The latte art forms a delicate swirl "
             "pattern in midair, catching the warm glow of an overhead LED "
             "strip that casts golden highlights across her arms and the "
             "counter. Outside, rain streaks down the window like liquid "
             "silk; no sign, no streetlights, just the rhythm of water "
             "against glass. All light comes from above-left, illuminating "
             "the steam rising from the cup while keeping the rest of the "
             "frame in muted shadow.")
BARISTA_B_FIXED = ("A barista, barefoot and wearing a white apron over dark "
                   "pants, stands behind a tiny Tokyo coffee stand as rain "
                   "taps softly against the glass window. She pours milk into "
                   "a black espresso cup with precise, swirling motions — her "
                   "hands steady, eyes locked on the surface. The latte art "
                   "forms a delicate swirl pattern in midair, catching the "
                   "warm glow of an overhead LED strip that casts golden "
                   "highlights across her arms and the counter. Outside, rain "
                   "streaks down the window like liquid silk; just the rhythm "
                   "of water against glass. All light comes from above-left, "
                   "illuminating the steam rising from the cup while keeping "
                   "the rest of the frame in muted shadow.")

# --- The fresh round (fresh_prompts.md) ------------------------------------

ROTI_O = ("A street cook flipping roti at a night market stall in Kuala "
          "Lumpur, vibrant neon lights casting colorful reflections on the "
          "wet pavement, steam rising from sizzling flatbreads, surrounded "
          "by bustling crowds and aromatic spices, captured with sharp focus "
          "and warm ambient glow, low-angle shot emphasizing action and "
          "texture, no background distractions, medium close-up focusing on "
          "hands and roti, standing = true")
ROTI_O_FIXED = ("A street cook flipping roti at a night market stall in "
                "Kuala Lumpur, vibrant neon lights casting colorful "
                "reflections on the wet pavement, steam rising from sizzling "
                "flatbreads, surrounded by bustling crowds and aromatic "
                "spices, captured with sharp focus and warm ambient glow, "
                "low-angle shot emphasizing action and texture, medium "
                "close-up focusing on hands and roti")

BOWLING_P = ("Zara, platinum blonde hair cascading over her shoulders, "
             "stands in the center of a bowling alley lane, mid-throw. Her "
             "body is angled slightly to the left as she grips the ball with "
             "both hands, knuckles white and fingers curled around the "
             "surface. Behind her, three friends are blurred but visible—two "
             "cheering with raised arms while one claps rhythmically. The "
             "lighting comes from an overhead bulb directly above her, "
             "casting a soft spotlight that highlights her focused expression "
             "and the gleam on the polished lane ball as it leaves her hand. "
             "This moment captures not just action, but connection—the "
             "energy of celebration suspended in motion.")
BOWLING_P_FIXED = ("Zara, platinum blonde hair cascading over her shoulders, "
                   "stands in the center of a bowling alley lane, mid-throw. "
                   "Her body is angled slightly to the left as she grips the "
                   "ball with both hands, knuckles white and fingers curled "
                   "around the surface. Behind her, three friends are blurred "
                   "but visible—two cheering with raised arms while one claps "
                   "rhythmically. The lighting comes from an overhead bulb "
                   "directly above her, casting a soft spotlight that "
                   "highlights her focused expression and the gleam on the "
                   "polished lane ball as it leaves her hand.")

BOWLING_O = ("Zara, with her platinum blonde hair and brown eyes, stands "
             "mid-throw at a bowling alley birthday party, her friends "
             "cheering behind her; the scene captures her focused expression "
             "as she releases the ball, her attire matching the vibrant, "
             "celebratory atmosphere without specifying exact colors or "
             "textures beyond what’s implied by context — all details "
             "grounded in the moment: the lane’s polished surface beneath "
             "her feet, the ambient glow of the alley’s lighting, and the "
             "blur of motion behind her.")
BOWLING_O_FIXED = ("Zara, with her platinum blonde hair and brown eyes, "
                   "stands mid-throw at a bowling alley birthday party, her "
                   "friends cheering behind her; the scene captures her "
                   "focused expression as she releases the ball, her attire "
                   "matching the vibrant, celebratory atmosphere: the lane’s "
                   "polished surface beneath her feet, the ambient glow of "
                   "the alley’s lighting, and the blur of motion behind her.")

PLATFORM_P = ("Zara, with platinum blonde hair and brown eyes, stands on a "
              "train platform in the rain, hood down. She holds a paper "
              "coffee cup in her right hand, waiting. Her outfit is not "
              "specified — she wears an opaque garment that covers her "
              "shoulders and arms but leaves her torso bare. The camera "
              "angle is from slightly below eye level, capturing her full "
              "body as she faces forward toward the approaching train. A "
              "single overhead light illuminates her from above, casting "
              "soft shadows on her face and clothing. The scene feels quiet "
              "and contemplative — she’s still, waiting for the next train "
              "to arrive.")
PLATFORM_P_FIXED = ("Zara, with platinum blonde hair and brown eyes, stands "
                    "on a train platform in the rain, hood down. She holds a "
                    "paper coffee cup in her right hand, waiting. Her outfit "
                    "is not specified — she wears an opaque garment that "
                    "covers her shoulders and arms but leaves her torso "
                    "bare. The camera angle is from slightly below eye level, "
                    "capturing her full body as she faces forward toward the "
                    "approaching train. A single overhead light illuminates "
                    "her from above, casting soft shadows on her face and "
                    "clothing. She’s still, waiting for the next train to "
                    "arrive.")

PLATFORM_O = ("Zara, platinum blonde hair, brown eyes, hourglass figure, "
              "standing on a train platform in the rain with hood down, "
              "holding a paper coffee cup, waiting. The scene is rendered in "
              "realism style with soft diffused lighting and wet surfaces "
              "reflecting the grey sky. No other locations, no backstory, "
              "nothing beyond what’s stated.")
PLATFORM_O_FIXED = ("Zara, platinum blonde hair, brown eyes, hourglass "
                    "figure, standing on a train platform in the rain with "
                    "hood down, holding a paper coffee cup, waiting. With "
                    "soft diffused lighting and wet surfaces reflecting the "
                    "grey sky.")

ARMCHAIR_K = ("An old man asleep in a sunlit armchair, head tilted back, one "
              "hand draped over his chest; a tabby cat curls on his lap, "
              "ears relaxed, tail tucked. A crumpled newspaper lies flat on "
              "the floor beside the chair’s footrest. Low afternoon sun from "
              "the right bathes the armchair’s fabric and the cat’s fur in "
              "warm amber light; no shadowed corners. The room has plain "
              "walls and a wooden floor, unadorned except for a single dust "
              "mote floating near the ceiling.")
ARMCHAIR_K_FIXED = ("An old man asleep in a sunlit armchair, head tilted "
                    "back, one hand draped over his chest; a tabby cat curls "
                    "on his lap, ears relaxed, tail tucked. A crumpled "
                    "newspaper lies flat on the floor beside the chair’s "
                    "footrest. Low afternoon sun from the right bathes the "
                    "armchair’s fabric and the cat’s fur in warm amber "
                    "light. The room has plain walls and a wooden floor, "
                    "unadorned except for a single dust mote floating near "
                    "the ceiling.")

PLATFORM_K = ("Zara stands on a wet platform, hood down, holding a paper "
              "coffee cup in her right hand; steam curls from its rim. Her "
              "platinum blonde hair falls over one shoulder, brown eyes "
              "fixed ahead. A thin gold chain glints at her neck. Raindrops "
              "streak the concrete beneath her feet; muted grey light casts "
              "soft reflections off puddles. She wears a dark coat with "
              "frayed cuffs and a subtle patterned scarf wrapped loosely "
              "around her neck. No crowd nearby — just the platform’s quiet "
              "hum and distant train whistle.")
PLATFORM_K_FIXED = ("Zara stands on a wet platform, hood down, holding a "
                    "paper coffee cup in her right hand; steam curls from "
                    "its rim. Her platinum blonde hair falls over one "
                    "shoulder, brown eyes fixed ahead. A thin gold chain "
                    "glints at her neck. Raindrops streak the concrete "
                    "beneath her feet; muted grey light casts soft "
                    "reflections off puddles. She wears a dark coat with "
                    "frayed cuffs and a subtle patterned scarf wrapped "
                    "loosely around her neck. Just the platform’s quiet hum "
                    "and distant train whistle.")

# Kimi's rooftop worked example from briefs/ref/kimi_findings.md (9.63) - the
# clean scene: no negations, no tool fields, no meta echoes, so the repair
# must leave it byte-identical.
KIMI_ROOFTOP = ("Restage her at a rooftop party at golden hour, leaning back "
                "against the roof railing with both elbows hooked over it, a "
                "cocktail glass held loose in one hand, laughing at someone "
                "just off camera to her right. A dozen guests stand in small "
                "clusters behind her with drinks, strings of bulbs crossing "
                "overhead between the roof vents, the skyline low and warm "
                "in the last of the sun. Her eyes are brown. The sun is "
                "behind the camera, low and amber, catching the glass and "
                "the railing's edge. The laugh is the frame: head tipped "
                "back, one hand rising halfway toward her mouth.")


class WriterSceneTests(unittest.TestCase):
    """The six B scenes and the fresh Official roti scene, repaired through
    the gate with the listed removals and nothing else."""

    def _gate(self, template, scene):
        repairs = []
        clean, err = server.scene_gate(template, scene, repairs=repairs)
        self.assertIsNone(err)
        return clean, repairs

    def test_rooftop_b(self):
        clean, repairs = self._gate("identity_edit", ROOFTOP_B)
        self.assertEqual(clean, ROOFTOP_B_FIXED)
        self.assertEqual(repairs, ["negation", "negation"])

    def test_laundromat_b(self):
        clean, repairs = self._gate("identity_edit", LAUNDROMAT_B)
        self.assertEqual(clean, LAUNDROMAT_B_FIXED)
        self.assertEqual(repairs, ["negation"] * 3)

    def test_market_b(self):
        clean, repairs = self._gate("identity_edit", MARKET_B)
        self.assertEqual(clean, MARKET_B_FIXED)
        self.assertEqual(repairs, ["negation"] * 3)

    def test_diner_b(self):
        clean, repairs = self._gate("identity_edit", DINER_B)
        self.assertEqual(clean, DINER_B_FIXED)
        self.assertEqual(repairs, ["negation", "negation"])

    def test_fisherman_b(self):
        clean, repairs = self._gate("realism", FISHERMAN_B)
        self.assertEqual(clean, FISHERMAN_B_FIXED)
        self.assertEqual(repairs, ["negation", "negation"])

    def test_barista_b(self):
        clean, repairs = self._gate("realism", BARISTA_B)
        self.assertEqual(clean, BARISTA_B_FIXED)
        self.assertEqual(repairs, ["negation"])

    def test_fresh_official_roti(self):
        clean, repairs = self._gate("realism", ROTI_O)
        self.assertEqual(clean, ROTI_O_FIXED)
        self.assertEqual(repairs, ["negation", "tool field"])

    def test_fresh_kimi_blocks(self):
        for raw, fixed in ((ARMCHAIR_K, ARMCHAIR_K_FIXED),
                           (PLATFORM_K, PLATFORM_K_FIXED)):
            with self.subTest(scene=raw[:30]):
                clean, repairs = self._gate("realism", raw)
                self.assertEqual(clean, fixed)
                self.assertEqual(repairs, ["negation"])


class NegationPassTests(unittest.TestCase):
    """Pass 1, clause by clause - the quoted forms from the brief."""

    def test_chained_list_before_a_just_remainder(self):
        fixed, repairs = server.repair_scene(
            "The background is a blur of soft indigo and peach tones — no "
            "buildings, no crowd, just sky and haze fading into dusk.",
            "identity_edit")
        self.assertEqual(fixed, "The background is a blur of soft indigo "
                                "and peach tones — just sky and haze fading "
                                "into dusk.")
        self.assertEqual(repairs, ["negation"])

    def test_clause_with_no_remainder_takes_its_separator(self):
        fixed, repairs = server.repair_scene(
            "Low afternoon sun bathes the armchair’s fabric and the cat’s "
            "fur in warm amber light; no shadowed corners. The room has "
            "plain walls and a wooden floor.", "realism")
        self.assertEqual(fixed, "Low afternoon sun bathes the armchair’s "
                                "fabric and the cat’s fur in warm amber "
                                "light. The room has plain walls and a "
                                "wooden floor.")
        self.assertEqual(repairs, ["negation"])

    def test_makeup_clause_keeps_the_dash_and_the_just_remainder(self):
        fixed, _ = server.repair_scene(
            "Her brown eyes are wide and focused forward—no makeup, no "
            "contouring, just natural skin tone and unedited features. In "
            "her right hand she holds a plastic cup of instant noodles.",
            "identity_edit")
        self.assertEqual(fixed, "Her brown eyes are wide and focused "
                                "forward—just natural skin tone and unedited "
                                "features. In her right hand she holds a "
                                "plastic cup of instant noodles.")

    def test_whole_sentence_negation_with_an_only_remainder(self):
        fixed, _ = server.repair_scene(
            "The dock’s planks creak underfoot, worn smooth by tide and "
            "time. No boats, no birds, no sky visible beyond the mist — "
            "only water, wood, and his steady presence. All light comes "
            "from above-left, faint and gold.", "realism")
        self.assertIn("Only water, wood, and his steady presence.", fixed)
        self.assertNotIn("No boats", fixed)

    def test_sentence_initial_clause_with_a_just_remainder(self):
        fixed, _ = server.repair_scene(
            "She wears a dark coat with frayed cuffs and a subtle patterned "
            "scarf wrapped loosely around her neck. No crowd nearby — just "
            "the platform’s quiet hum and distant train whistle.", "realism")
        self.assertTrue(fixed.endswith(
            "Just the platform’s quiet hum and distant train whistle."))

    def test_existential_negation_sentence(self):
        fixed, repairs = server.repair_scene(
            "There is no crowd nearby. She waits alone on the bench.",
            "realism")
        self.assertEqual(fixed, "She waits alone on the bench.")
        self.assertEqual(repairs, ["negation"])

    def test_the_positive_openers_stay(self):
        for scene in ("A no-parking sign leans against the curb in the rain.",
                      "She has a no-nonsense stance, arms crossed, watching "
                      "the door.",
                      "Nothing but a white tee covers her.",
                      "No one but the night guard walks the platform.",
                      "She could no longer see the shore through the fog."):
            with self.subTest(scene=scene):
                fixed, repairs = server.repair_scene(scene, "realism")
                self.assertEqual((fixed, repairs), (scene, []))

    def test_nsfw_skips_the_negation_pass(self):
        scene = ("She lies nude on the bed, no underwear, one knee raised. "
                 "A single lamp lights her from the left.")
        fixed, repairs = server.repair_scene(scene, "realism", nsfw=True)
        self.assertEqual((fixed, repairs), (scene, []))


class ToolFieldPassTests(unittest.TestCase):
    """Pass 2 - inline tool arguments and medium restatements."""

    def test_an_inline_field_dies_with_its_punctuation(self):
        fixed, repairs = server.repair_scene(
            "A street cook flips roti on a glowing griddle under a "
            "low-hanging streetlamp, steam curling from the sizzling dough, "
            "medium close-up focusing on hands and roti, standing = true",
            "realism")
        self.assertTrue(fixed.endswith("medium close-up focusing on hands "
                                       "and roti"))
        self.assertNotIn("standing", fixed)
        self.assertEqual(repairs, ["tool field"])

    def test_a_short_inline_seed(self):
        fixed, repairs = server.repair_scene(
            "A fox curls in fresh snow under a pine tree, tail over its "
            "nose, whiskers forward, seed = 42", "realism")
        self.assertTrue(fixed.endswith("whiskers forward"))
        self.assertEqual(repairs, ["tool field"])

    def test_a_trailing_medium_restatement_on_a_photo_recipe(self):
        fixed, repairs = server.repair_scene(
            "The floor reflects faint glimmers of overhead lighting in long "
            "streaks toward the back wall of the laundromat, pooling beneath "
            "the machines, all rendered in a realistic photograph style "
            "with warm, moody color tones that emphasize solitude and quiet "
            "comfort.", "realism")
        self.assertEqual(fixed, "The floor reflects faint glimmers of "
                                "overhead lighting in long streaks toward "
                                "the back wall of the laundromat, pooling "
                                "beneath the machines.")
        self.assertEqual(repairs, ["meta echo"])

    def test_a_named_medium_on_zimage_is_the_users_ask_and_stays(self):
        fixed, repairs = server.repair_scene(PLATFORM_O, "zimage")
        self.assertIn("The scene is rendered in realism style", fixed)
        self.assertEqual(repairs, ["negation"])   # the negation still goes

    def test_a_user_requested_medium_on_zimage_never_matches(self):
        scene = ("A dragon circles a spire above the clouds, wings wide over "
                 "the valley, rendered in realism style.")
        fixed, repairs = server.repair_scene(scene, "zimage")
        self.assertEqual((fixed, repairs), (scene, []))


class MetaEchoPassTests(unittest.TestCase):
    """Pass 3 - the writer narrating its rulebook instead of the scene."""

    def test_this_moment_captures_is_a_whole_sentence_drop(self):
        fixed, repairs = server.repair_scene(BOWLING_P, "realism")
        self.assertEqual(fixed, BOWLING_P_FIXED)
        self.assertEqual(repairs, ["meta echo"])

    def test_the_scene_feels_drops_the_claim_and_keeps_the_drawable_tail(self):
        fixed, repairs = server.repair_scene(PLATFORM_P, "realism")
        self.assertEqual(fixed, PLATFORM_P_FIXED)
        self.assertEqual(repairs, ["meta echo"])

    def test_the_scene_is_rendered_keeps_a_capitalized_with_tail(self):
        fixed, repairs = server.repair_scene(PLATFORM_O, "realism_ii")
        self.assertEqual(fixed, PLATFORM_O_FIXED)
        self.assertEqual(repairs, ["negation", "meta echo"])

    def test_the_rulebook_clauses_die_and_the_evidence_list_stays(self):
        fixed, repairs = server.repair_scene(BOWLING_O, "realism")
        self.assertEqual(fixed, BOWLING_O_FIXED)
        self.assertEqual(repairs, ["meta echo", "meta echo"])

    def test_evokes_tranquility_and_solitude(self):
        fixed, repairs = server.repair_scene(
            "his worn boots resting near the edge of the dock, the scene "
            "rendered in muted coastal tones—grays, blues, and earthy "
            "browns—with a painterly realism that evokes tranquility and "
            "solitude; the net’s frayed edges catch faint reflections of "
            "the pale sky", "realism")
        self.assertEqual(fixed, "his worn boots resting near the edge of "
                                "the dock, the scene rendered in muted "
                                "coastal tones—grays, blues, and earthy "
                                "browns—with a painterly realism; the net’s "
                                "frayed edges catch faint reflections of "
                                "the pale sky")
        self.assertEqual(repairs, ["meta echo"])

    def test_an_essence_claim_leaves_no_stub_behind(self):
        fixed, repairs = server.repair_scene(
            "Lights hang from the awning above the stalls, warm and low "
            "over the crowd. The scene captures the essence of the "
            "festival.", "realism")
        self.assertEqual(fixed, "Lights hang from the awning above the "
                                "stalls, warm and low over the crowd.")
        self.assertEqual(repairs, ["meta echo"])

    def test_a_scene_sentence_with_a_drawable_predicate_stays(self):
        scene = "The scene is lit by one bulb over the counter."
        fixed, repairs = server.repair_scene(scene, "realism")
        self.assertEqual((fixed, repairs), (scene, []))


class GateAndGuardTests(unittest.TestCase):
    """The gate contract: verbatim is sacred, the guard refuses gutting."""

    def test_verbatim_never_repairs(self):
        repairs = []
        clean, err = server.scene_gate("identity_edit", LAUNDROMAT_B,
                                       verbatim=True, repairs=repairs)
        self.assertEqual((clean, err), (LAUNDROMAT_B, None))
        self.assertEqual(repairs, [])

    def test_the_gate_collects_the_repairs(self):
        repairs = []
        clean, err = server.scene_gate("identity_edit", LAUNDROMAT_B,
                                       repairs=repairs)
        self.assertIsNone(err)
        self.assertEqual(clean, LAUNDROMAT_B_FIXED)
        self.assertEqual(repairs, ["negation"] * 3)

    def test_the_gate_threads_the_nsfw_flag(self):
        scene = ("She lies nude on the bed, no underwear, one knee raised. "
                 "A single lamp lights her from the left.")
        repairs = []
        clean, err = server.scene_gate("realism", scene, nsfw=True,
                                       repairs=repairs)
        self.assertEqual((clean, err), (scene, None))
        self.assertEqual(repairs, [])

    def test_a_clean_scene_is_byte_identical(self):
        repairs = []
        clean, err = server.scene_gate("identity_edit", KIMI_ROOFTOP,
                                       repairs=repairs)
        self.assertEqual((clean, err), (KIMI_ROOFTOP, None))
        self.assertEqual(repairs, [])

    def test_the_guard_refuses_a_repair_that_guts_the_scene(self):
        scene = "No crowd. No buildings. No sky. No birds."
        fixed, repairs = server.repair_scene(scene, "realism")
        self.assertEqual(fixed, scene)
        self.assertEqual(repairs, ["kept: repair would gut the scene"])

    def test_exactly_half_is_not_gutting(self):
        fixed, repairs = server.repair_scene(
            "No crowd, no signs, no dogs. She waits alone on the platform.",
            "realism")
        self.assertEqual(fixed, "She waits alone on the platform.")
        self.assertEqual(repairs, ["negation"])


class _FakeComfyResp:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return {"prompt_id": "deadbeefcafe1234"}


class _FakeComfySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, *args, **kwargs):
        return _FakeComfyResp()


def _submit(scene, spec_args=None):
    """HUB.submit with the real scene gate and every side effect stubbed:
    graph build, VRAM butler, the ComfyUI POST and the completion watcher."""
    hub = server.Hub()
    seen, events = [], []
    hub.broadcast = lambda **kw: events.append(kw)

    async def _no_op(*a, **k):
        return None

    hub.ensure_vram = _no_op
    hub.watch = _no_op

    def fake_builder(scene, seed, **kw):
        seen.append(scene)
        return ({"1": {"class_type": "Stub", "inputs": {}}}, "full",
                {"model": "stub.safetensors"})

    with patch.dict(server.BUILDERS, {"realism": fake_builder}), \
         patch.object(server, "validate_job_model_info", lambda *a, **k: None), \
         patch.object(server, "_lora_warning_text", lambda _w: ""), \
         patch.object(server, "_h3_warning_text", lambda _w: ""), \
         patch.object(server.aiohttp, "ClientSession",
                      lambda *a, **k: _FakeComfySession()):
        job = asyncio.run(hub.submit("cid00000", "chat", "realism", scene,
                                     spec_args or {}))
        return job, seen, events


class SubmitStampTests(unittest.TestCase):
    """The repairs ride the job beside the scene, for the card and the A/B
    driver; the encoder and history only ever see the repaired text."""

    def test_a_repaired_job_carries_the_stamp(self):
        job, _seen, _events = _submit(ROTI_O)
        self.assertEqual(job["scene"], ROTI_O_FIXED)
        self.assertEqual(job["scene_repairs"], ["negation", "tool field"])

    def test_the_builder_and_broadcast_see_the_repaired_scene(self):
        job, seen, events = _submit(ROTI_O)
        self.assertEqual(seen, [ROTI_O_FIXED])          # the encoder's text
        card = next(e for e in events if e.get("type") == "job")
        self.assertEqual(card["scene"], ROTI_O_FIXED)   # the card's text

    def test_a_clean_job_carries_no_stamp(self):
        job, _seen, _events = _submit(KIMI_ROOFTOP)
        self.assertEqual(job["scene"], KIMI_ROOFTOP)
        self.assertNotIn("scene_repairs", job)


if __name__ == "__main__":
    unittest.main()
