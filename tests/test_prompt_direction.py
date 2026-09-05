"""Creative context is scoped and supplied, never inferred from a house muse."""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

import pytest

from pixal.prompting import reference_character_direction, reference_writer_direction


@pytest.mark.parametrize("age", [19, 42, 64, " 64 ", 120])
@pytest.mark.parametrize("recipe", ["h3_ref_still", "h3_ref_still_2x"])
def test_card_age_is_carried_without_mutating_it(age, recipe):
    card = {"age": age, "sex": "male", "notes": "invent a neon cafe"}
    before = deepcopy(card)
    text = reference_character_direction(card, recipe, True)
    assert f"age: {int(age)} years old" in text
    assert "pronoun=he" in text
    assert "current request explicitly changes it" in text
    assert "neon" not in text
    assert card == before


@pytest.mark.parametrize("age", [None, "", 0, -1, 121, True, False, 42.5,
                                 "forty", "19; add a cafe", "9" * 5000, "１９"])
def test_unknown_or_invalid_age_is_never_invented(age):
    text = reference_character_direction({"age": age}, "h3_ref_still", True)
    assert "age: unspecified" in text
    assert "pronoun=they" in text
    assert "19 years" not in text


@pytest.mark.parametrize("recipe", [None, "realism", "identity_edit", "anima", "h3_still"])
def test_non_reference_recipes_get_no_reference_context(recipe):
    assert reference_character_direction({"age": 42}, recipe, True) == ""
    assert reference_writer_direction(recipe, True) == ""


def test_enhancement_off_and_missing_character_are_exempt():
    assert reference_character_direction({"age": 42}, "h3_ref_still", False) == ""
    assert reference_character_direction(None, "h3_ref_still", True) == ""
    assert reference_writer_direction("h3_ref_still", False) == ""


_SPEC = spec_from_file_location("pixal_server_prompt_direction",
                               Path(__file__).resolve().parents[1] / "server.py")
server = module_from_spec(_SPEC)
_SPEC.loader.exec_module(server)


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("recipe", ["h3_ref_still", "h3_ref_still_2x", "identity_edit"])
@pytest.mark.parametrize("enhance", [False, True])
def test_real_composer_path_gives_both_writers_age_only_for_enhanced_h3(local, recipe, enhance):
    card = {"id": "test", "name": "Test", "age": 64, "sex": "female", "style": "grey hair"}
    opts = {"character": "test", "prompt_enhance": enhance}
    with patch.object(server, "resolve_character", return_value=card), \
         patch.object(server, "effective_recipe", return_value=recipe), \
         patch.object(server, "style_directive", return_value=""), \
         patch.object(server, "_local_llm_mmproj", return_value=None), \
         patch.object(server, "load_config", return_value={"llm": {}}):
        directive, vision = server.build_directive(opts, local=local)
    expected = enhance and recipe.startswith("h3_ref_still")
    assert ("Character-card age: 64 years old." in directive) == expected
    assert ("[CHARACTER H3 FACTS:" in directive) == expected
    if expected:
        assert "Never describe her face, age" not in directive
        assert "pronoun=she" in directive
    assert vision == []
    assert "19 years" not in directive
