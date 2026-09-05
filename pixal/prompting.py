"""Scoped creative guidance, with no model calls, application state or I/O.

These are writer instructions, not sampler text. Reference-still heuristics
must not become a universal house style or hard-coded character identity.
"""

H3_REFERENCE_RECIPES = frozenset(("h3_ref_still", "h3_ref_still_2x"))

H3_REFERENCE_DIRECTION = """
H3 REFERENCE DIRECTION - only the active reference-still recipe.
The user's requested subject, age, styling, light, palette and stillness take
precedence over photographic taste defaults elsewhere in this prompt. Fill gaps
only; keep each explicit choice consistent throughout the caption.

IDENTITY: the wired reference carries facial identity. Use the supplied character
age when available; an explicit age in the current request takes precedence.
When age is unspecified, leave it unspecified. Preserve the subject's pronouns.
Describe requested hair, grooming and clothing, not invented facial anatomy,
makeup, youth, tan or designer accessories. A named character's lifestyle is not
permission to import their usual locations into a new scene.

SHOT: write short sentences, one idea each, as many as this shot actually needs.
Keep subjects, props and light spatially connected. For a selfie, one hand holds
the camera; assign the remaining hand at most one task. With both hands occupied,
use the requested observer/tripod viewpoint, or choose a plausible one if absent.
A requested still or contemplative pose stays still; it needs no invented task.
Keep the reference-still recipe's waist-up-or-closer framing and hands in frame.

LIGHT AND MATERIAL: preserve the requested softness, direction, colour and time
of day. Soft window light stays soft; candlelight stays candlelight. When light is
unspecified, choose one believable source suited to the place. Describe how that
light meets relevant surfaces instead of adding a fixed skin-texture paragraph.
Use the requested amount of environmental detail; a minimal scene stays minimal.
Only include skin or material detail relevant at the chosen distance and light.

FINISH: keep requested lettering exact, in quotes, and describe only visible
garments. Close with the wardrobe appropriate to the request; the server owns
the clothing safeguard. Do not add a new camera, light or styling direction after
that closing clause. This is a caption, not a numbered checklist.
"""


def reference_writer_direction(recipe_id, prompt_enhance):
    """Reference craft is opt-in by active recipe and enhancement policy."""
    if prompt_enhance and recipe_id in H3_REFERENCE_RECIPES:
        return H3_REFERENCE_DIRECTION
    return ""


def reference_character_direction(character, recipe_id, prompt_enhance):
    """Pass typed age/subject facts to both writers without exposing card notes.

    Age is deliberately not inferred from the photograph, name or free prose.
    Invalid legacy values are omitted rather than guessed or coerced (notably
    bool/float). The render builders and the character card remain unchanged.
    """
    if not character or not prompt_enhance or recipe_id not in H3_REFERENCE_RECIPES:
        return ""
    pronoun = {"female": "she", "male": "he"}.get(character.get("sex"), "they")
    raw_age = character.get("age")
    age = None
    if type(raw_age) is int:
        age = raw_age
    elif isinstance(raw_age, str) and raw_age.strip().isascii() and raw_age.strip().isdigit():
        # Limit before conversion: untrusted/legacy values need not be integers
        # of arbitrary size just to decide whether they are a plausible age.
        value = raw_age.strip()
        if len(value) <= 3:
            age = int(value)
    if age is not None and 1 <= age <= 120:
        age_line = f"Character-card age: {age} years old."
    else:
        age_line = "Character-card age: unspecified; do not invent one."
    return (f"\n[CHARACTER H3 FACTS: pronoun={pronoun}. {age_line} "
            "Use the card age unless the current request explicitly changes it. "
            "The reference carries facial identity; describe only requested styling.]")
