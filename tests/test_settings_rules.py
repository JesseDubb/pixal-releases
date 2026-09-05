"""Frozen old/new settings behavior; no server import or installed assets needed."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from pixal.config.settings import InvalidSetting, SettingsChoices, apply_settings_patch

FIXTURE = json.loads((Path(__file__).parent / "fixtures/settings_patch_1_3_1b.json").read_text(encoding="utf-8"))
CHOICES = SettingsChoices(**{k: tuple(v) for k, v in FIXTURE["policy"].items()})


class FixtureCatalog:
    def __init__(self):
        self.data = FIXTURE["catalog"]

    def resolve_upscaler(self, name):
        if name in ("synthetic.pth", self.data["upscalers"][0]):
            return self.data["upscalers"][0]
        raise ValueError("synthetic upscaler not installed: " + name)

    def model_names(self, recipe):
        return self.data["models"][recipe]

    def has_vae(self, name):
        return name in self.data["vae"]

    def h3_model_names(self, lane):
        return self.data["h3_models"][lane]

    def h3_encoder_available(self, name):
        return name in self.data["h3_encoders"]

    def video_engines(self):
        return self.data["video_engines"]


@pytest.mark.parametrize("case", FIXTURE["cases"])
def test_settings_patch_matches_committed_baseline(case):
    cfg = copy.deepcopy(FIXTURE["defaults"])
    body = copy.deepcopy(case["body"])
    try:
        apply_settings_patch(cfg, body, choices=CHOICES, catalog=FixtureCatalog())
    except InvalidSetting as error:
        assert (case["status"], case["response"]) == (400, {"ok": False, "error": str(error)})
        assert case["saved_sha256"] is None
    else:
        assert (case["status"], case["response"]) == (200, {"ok": True})
        result = hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert result == case["saved_sha256"]
    assert body == case["body"]


def test_unrelated_flags_do_not_access_the_catalog():
    class ForbiddenCatalog:
        def __getattr__(self, key):
            pytest.fail(f"Unexpected catalog access: {key}")

    cfg = copy.deepcopy(FIXTURE["defaults"])
    apply_settings_patch(cfg, {"still": {"film_grain": True}, "comfy_console": "plain"},
                         choices=CHOICES, catalog=ForbiddenCatalog())
    assert cfg["still"]["film_grain"] is True
    assert cfg["comfy_console"] == "plain"


def test_patch_does_not_require_or_create_unrelated_sections():
    cfg = {"llm": {}}
    apply_settings_patch(cfg, {"llm": {"local_model": "synthetic.gguf"},
                               "still": {"unknown_future": True}},
                         choices=CHOICES, catalog=FixtureCatalog())
    assert cfg == {"llm": {"local_model": "synthetic.gguf"}}


def test_known_finisher_can_populate_a_pre_finisher_config():
    cfg = {"llm": {}}
    apply_settings_patch(cfg, {"still": {"film_grain": False}},
                         choices=CHOICES, catalog=FixtureCatalog())
    assert cfg == {"llm": {}, "still": {"film_grain": False}}
